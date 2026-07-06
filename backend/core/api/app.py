from __future__ import annotations

import asyncio
import base64
import json
import os
import threading
import time
import uuid
from dataclasses import dataclass
from typing import Any, Dict, List

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from core.agent_factory import load_agent
from core.api.frontier_bridge import (
    FrontierRunState,
    build_frontier_state_event,
    create_frontier_run_state,
)
from core.api.llm_config import (
    apply_llm_config_to_env,
    check_llm_config,
    public_llm_config,
    save_llm_config,
)
from core.protocol.agent import AgentBackend
from core.protocol.channel import AgentOutputChannel, QueueOutputChannel
from core.protocol.events import AgentOutputEvent
from core.protocol.input import AgentInput
from frontends.file_processor import build_attachment_prompt
from frontends.services.file_upload_service import FileUploadService
from frontends.services.history_restore_service import HistoryRestoreService


class RunCreateRequest(BaseModel):
    query: str = Field(min_length=1)
    attachments: List[Dict[str, Any]] = Field(default_factory=list)
    routing_mode: str = "auto"


class RunCreateResponse(BaseModel):
    run_id: str
    status: str = "running"


class StopRunResponse(BaseModel):
    run_id: str
    status: str


class AttachmentUploadItem(BaseModel):
    name: str
    data_base64: str
    mime_type: str = ""


class AttachmentUploadRequest(BaseModel):
    files: List[AttachmentUploadItem] = Field(default_factory=list)


class SettingsPatch(BaseModel):
    routing_mode: str | None = None
    compact_assistant_history: bool | None = None
    autonomous_enabled: bool | None = None


class LlmConfigPatch(BaseModel):
    provider: str | None = None
    api_key: str | None = None
    base_url: str | None = None
    model: str | None = None


class LlmConfigCheckRequest(LlmConfigPatch):
    probe_chat: bool = True


class SwitchKeyRequest(BaseModel):
    index: int = Field(ge=0)


class AutonomousTriggerRequest(BaseModel):
    mode: str = "manual"


@dataclass
class ActiveRun:
    run_id: str
    channel: AgentOutputChannel
    frontier: FrontierRunState
    terminal: bool = False


class _UploadedBytes:
    def __init__(self, name: str, data: bytes, mime_type: str = "") -> None:
        self.name = name
        self._data = data
        self.type = mime_type
        self.size = len(data)

    def getvalue(self) -> bytes:
        return self._data


class UnconfiguredAgentBackend(AgentBackend):
    """Fallback backend that lets the desktop API boot before API keys exist."""

    def __init__(self, reason: str) -> None:
        self.reason = reason

    def submit(self, task: AgentInput) -> AgentOutputChannel:
        channel = QueueOutputChannel()
        channel.put(
            AgentOutputEvent(
                kind="error",
                text="Backend is not configured. Set GA_API_KEY or create a local key configuration, then restart.",
                task_id=task.run_id,
                error=self.reason,
                metadata={"configuration_required": True},
            )
        )
        channel.close()
        return channel

    def abort(self) -> None:
        return None

    @property
    def is_running(self) -> bool:
        return False

    def get_llm_name(self) -> str:
        return "unconfigured"

    def get_key_labels(self) -> list[str]:
        return []

    def switch_to_key(self, index: int) -> str:
        return ""


class ReactApiRuntime:
    """Small HTTP-facing runtime wrapper around the existing AgentBackend."""

    def __init__(self, agent: AgentBackend, *, project_root: str) -> None:
        self.agent = agent
        self.project_root = project_root
        self.active_run: ActiveRun | None = None
        self.upload_cache: dict[str, dict[str, Any]] = {}
        self.tools_injected = False
        self._run_lock = threading.Lock()
        self.ui_state: dict[str, Any] = {
            "routing_mode": "auto",
            "compact_assistant_history": True,
            "autonomous_enabled": False,
            "last_reply_time": 0,
        }

    def create_run(self, request: RunCreateRequest) -> RunCreateResponse:
        with self._run_lock:
            if self.active_run is not None and not self.active_run.terminal:
                raise HTTPException(status_code=409, detail="A run is already active")

            run_id = f"run_{uuid.uuid4().hex[:12]}"
            query = self._query_with_attachments(request.query, request.attachments)
            channel = self.agent.submit(
                AgentInput(
                    query=query,
                    run_id=run_id,
                    metadata={"attachments": request.attachments, "routing_mode": request.routing_mode},
                )
            )
            self.active_run = ActiveRun(
                run_id=run_id,
                channel=channel,
                frontier=create_frontier_run_state(request.query, request.routing_mode),
            )
        return RunCreateResponse(run_id=run_id)

    def stop_run(self, run_id: str) -> StopRunResponse:
        run = self._get_run(run_id)
        self.agent.abort()
        run.channel.put(
            AgentOutputEvent(
                kind="stopped",
                text="已停止模型输出，可以继续提问。",
                source="system",
                task_id=run_id,
            )
        )
        run.channel.close()
        run.terminal = True
        return StopRunResponse(run_id=run_id, status="stopped")

    async def stream_events(self, run_id: str):
        run = self._get_run(run_id)
        initial_frontier = build_frontier_state_event(run.run_id, run.frontier)
        if initial_frontier is not None:
            yield _sse_payload(initial_frontier)
        while True:
            event = await _to_thread(run.channel.get, 0.2)
            if event is None:
                if run.channel.closed or run.terminal:
                    break
                yield _sse_payload(AgentOutputEvent(kind="status", task_id=run_id, metadata={"state": "waiting"}))
                await asyncio.sleep(0.2)
                continue
            if not event.task_id:
                event.task_id = run_id
            frontier_event = build_frontier_state_event(run.run_id, run.frontier, event)
            if frontier_event is not None and event.kind != "frontier_state":
                yield _sse_payload(frontier_event)
            yield _sse_payload(event)
            if event.is_terminal():
                run.terminal = True
                self.ui_state["last_reply_time"] = int(time.time())
                break

    def upload_attachments(self, request: AttachmentUploadRequest) -> dict[str, Any]:
        service = FileUploadService(cache=self.upload_cache)
        uploaded = []
        for item in request.files:
            try:
                data = base64.b64decode(item.data_base64.encode("ascii"), validate=True)
            except Exception as exc:
                raise HTTPException(status_code=400, detail=f"Invalid base64 for {item.name}") from exc
            uploaded.append(_UploadedBytes(item.name, data, item.mime_type))
        return {"attachments": [info.to_dict() for info in service.process(uploaded)]}

    def list_history(self) -> dict[str, Any]:
        service = HistoryRestoreService(project_root=self.project_root)
        items = []
        for info in service.list_files():
            if not info.title:
                info.title = service.extract_title(info.filepath)
            items.append(info.__dict__)
        return {"items": items}

    def get_history(self, history_id: str) -> dict[str, Any]:
        service, info = self._find_history(history_id)
        preview = service.preview(info.filepath, max_lines=80)
        return {"item": info.__dict__, "preview": preview}

    def restore_history(self, history_id: str) -> dict[str, Any]:
        service, info = self._find_history(history_id)
        restored = service.restore(info.filepath)
        if restored is None:
            raise HTTPException(status_code=422, detail="History file could not be restored")
        messages = _restored_to_chat_messages(restored.restored, restored.fmt_type)
        self._restore_agent_history(restored.restored, restored.fmt_type)
        self.active_run = None
        return {
            "item": info.__dict__,
            "messages": messages,
            "count": restored.count,
            "fmt_type": restored.fmt_type,
        }

    def distill_delete_history(self, history_id: str) -> dict[str, Any]:
        from frontends.chatapp_common import (
            delete_history_file,
            distill_conversation,
            save_distilled_memory,
        )

        service, info = self._find_history(history_id)
        summary, err = distill_conversation(info.filepath)
        save_result = None
        save_err = None
        if summary:
            inbox_path = os.path.join(self.project_root, "memory", "history_memory_inbox.md")
            save_result, save_err = save_distilled_memory(summary, info.filepath, inbox_path=inbox_path)
            if save_err:
                raise HTTPException(status_code=500, detail=save_err)
        deleted, delete_err = delete_history_file(info.filepath)
        if not deleted:
            raise HTTPException(status_code=500, detail=delete_err or "Delete failed")
        self.active_run = None
        return {
            "ok": True,
            "deleted": True,
            "filename": info.filename,
            "summary": summary,
            "save_result": save_result,
            "save_error": save_err,
        }

    def memory(self) -> dict[str, Any]:
        return {"items": _get_memory_content(self.project_root)}

    def settings(self) -> dict[str, Any]:
        return {
            **self.ui_state,
            "idle_seconds": self._idle_seconds(),
            "backend": self.agent.get_llm_name(),
            "current_key_index": self._current_key_index(),
            "key_labels": self.agent.get_key_labels(),
        }

    def update_settings(self, patch: SettingsPatch) -> dict[str, Any]:
        if patch.routing_mode is not None:
            if patch.routing_mode not in {"auto", "classic", "multi_agent"}:
                raise HTTPException(status_code=400, detail="Invalid routing_mode")
            self.ui_state["routing_mode"] = patch.routing_mode
        if patch.compact_assistant_history is not None:
            self.ui_state["compact_assistant_history"] = bool(patch.compact_assistant_history)
        if patch.autonomous_enabled is not None:
            self.ui_state["autonomous_enabled"] = bool(patch.autonomous_enabled)
        return self.settings()

    def llm_config(self) -> dict[str, Any]:
        return {
            **public_llm_config(),
            "backend": self.agent.get_llm_name(),
        }

    def update_llm_config(self, patch: LlmConfigPatch) -> dict[str, Any]:
        if self.active_run is not None and not self.active_run.terminal:
            raise HTTPException(status_code=409, detail="Cannot change LLM config while a run is active")
        if hasattr(patch, "model_dump"):
            patch_data = patch.model_dump(exclude_unset=True)
        else:
            patch_data = patch.dict(exclude_unset=True)
        saved = save_llm_config(patch_data)
        apply_llm_config_to_env(saved)
        try:
            self.agent.abort()
        except Exception:
            pass
        try:
            self.agent = load_agent(os.getenv("GA_REACT_BACKEND", "classic"))
        except Exception as exc:
            if not _is_configuration_error(exc):
                raise
            self.agent = UnconfiguredAgentBackend(str(exc))
        self.active_run = None
        return self.llm_config()

    def check_llm_config(self, request: LlmConfigCheckRequest) -> dict[str, Any]:
        if hasattr(request, "model_dump"):
            data = request.model_dump(exclude_unset=True)
        else:
            data = request.dict(exclude_unset=True)
        probe_chat = bool(data.pop("probe_chat", True))
        return check_llm_config(data, probe_chat=probe_chat)

    def reset_conversation(self) -> dict[str, Any]:
        from frontends.services.conversation_reset_service import reset_agent_conversation_state

        reset_agent_conversation_state(self.agent)
        self.active_run = None
        return {"ok": True}

    def switch_key(self, request: SwitchKeyRequest) -> dict[str, Any]:
        labels = self.agent.get_key_labels()
        if labels and request.index >= len(labels):
            raise HTTPException(status_code=400, detail="Key index out of range")
        name = self.agent.switch_to_key(request.index)
        return {"ok": True, "backend": name or self.agent.get_llm_name(), "settings": self.settings()}

    def reinject_tools(self) -> dict[str, Any]:
        injected = 0
        llmclient = getattr(self.agent, "llmclient", None)
        if llmclient is not None:
            try:
                llmclient.last_tools = ""
            except Exception:
                pass
            if not self.tools_injected:
                hist_path = os.path.join(self.project_root, "assets", "tool_usable_history.json")
                backend = getattr(llmclient, "backend", None)
                history = getattr(backend, "history", None)
                if os.path.exists(hist_path) and isinstance(history, list):
                    try:
                        with open(hist_path, "r", encoding="utf-8") as f:
                            tool_hist = json.load(f)
                        if isinstance(tool_hist, list):
                            history.extend(tool_hist)
                            injected = len(tool_hist)
                            self.tools_injected = True
                    except Exception as exc:
                        raise HTTPException(status_code=500, detail=f"Failed to inject tool history: {exc}") from exc
        return {"ok": True, "injected": injected, "tools_injected": self.tools_injected}

    def trigger_autonomous(self, request: AutonomousTriggerRequest) -> RunCreateResponse:
        if request.mode == "idle":
            prompt = "[AUTO]🤖 用户已经离开超过30分钟，作为自主智能体，请阅读自动化sop，执行自动任务。"
        else:
            prompt = "[AUTO]🤖 用户触发了自主行动，请阅读自动化sop，选择并执行一项有价值的任务。"
        return self.create_run(
            RunCreateRequest(
                query=prompt,
                attachments=[],
                routing_mode="classic",
            )
        )

    def status(self) -> dict[str, Any]:
        return {
            "backend": self.agent.get_llm_name(),
            "running": bool(self.agent.is_running),
            "active_run_id": self.active_run.run_id if self.active_run else "",
            "active_run_terminal": bool(self.active_run.terminal) if self.active_run else True,
            "settings": self.settings(),
        }

    def _get_run(self, run_id: str) -> ActiveRun:
        if self.active_run is None or self.active_run.run_id != run_id:
            raise HTTPException(status_code=404, detail="Run not found")
        return self.active_run

    def _find_history(self, history_id: str) -> tuple[HistoryRestoreService, Any]:
        service = HistoryRestoreService(project_root=self.project_root)
        wanted = os.path.basename(history_id)
        for info in service.list_files():
            if info.filename == wanted:
                if not info.title:
                    info.title = service.extract_title(info.filepath)
                return service, info
        raise HTTPException(status_code=404, detail="History file not found")

    def _restore_agent_history(self, restored: list[Any], fmt_type: str) -> None:
        from frontends.chatapp_common import (
            input_items_to_backend_history,
            input_items_to_lines,
            restored_lines_to_backend_history,
        )

        is_input_items = fmt_type == "input_items"
        if hasattr(self.agent, "restore_history"):
            try:
                self.agent.restore_history(restored, is_input_items=is_input_items)  # type: ignore[attr-defined]
                return
            except TypeError:
                self.agent.restore_history(restored)  # type: ignore[attr-defined]
                return
        if hasattr(self.agent, "abort"):
            self.agent.abort()
        if hasattr(self.agent, "history"):
            self.agent.history = input_items_to_lines(restored) if is_input_items else list(restored)  # type: ignore[attr-defined]
        llmclient = getattr(self.agent, "llmclient", None)
        backend = getattr(llmclient, "backend", None)
        if backend is not None:
            backend.history = (
                input_items_to_backend_history(restored)
                if is_input_items
                else restored_lines_to_backend_history(restored)
            )
            try:
                llmclient.last_tools = ""
            except Exception:
                pass

    @staticmethod
    def _query_with_attachments(query: str, attachments: list[dict[str, Any]]) -> str:
        attachment_prompt = build_attachment_prompt(attachments)
        if not attachment_prompt:
            return query
        return f"{query}\n\n{attachment_prompt}"

    def _idle_seconds(self) -> int:
        last = int(self.ui_state.get("last_reply_time") or 0)
        return max(0, int(time.time()) - last) if last else 0

    def _current_key_index(self) -> int:
        try:
            return int(getattr(self.agent, "llm_no", 0) or 0)
        except Exception:
            return 0


def _sse_payload(event: AgentOutputEvent) -> str:
    data = {
        "kind": event.kind,
        "text": event.text,
        "source": event.source,
        "turn": event.turn,
        "task_id": event.task_id,
        "error": event.error,
        "metadata": event.metadata,
    }
    return f"event: agent\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


async def _to_thread(func, *args):
    to_thread = getattr(asyncio, "to_thread", None)
    if callable(to_thread):
        return await to_thread(func, *args)
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, lambda: func(*args))


def _get_memory_content(project_root: str) -> dict[str, str]:
    mem_dir = os.path.join(project_root, "memory")
    result: dict[str, str] = {}
    for name in ("global_mem_insight.txt", "global_mem.txt"):
        path = os.path.join(mem_dir, name)
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                result[name] = f.read()

    inbox_name = "history_memory_inbox.md"
    inbox_path = os.path.join(mem_dir, inbox_name)
    if os.path.exists(inbox_path):
        with open(inbox_path, "r", encoding="utf-8", errors="ignore") as f:
            result[inbox_name] = f.read()
    return result


def _restored_to_chat_messages(restored: list[Any], fmt_type: str) -> list[dict[str, str]]:
    from frontends.chatapp_common import input_items_to_messages, restored_lines_to_messages

    raw_messages = (
        input_items_to_messages(restored)
        if fmt_type == "input_items"
        else restored_lines_to_messages(restored)
    )
    return [
        {"role": str(msg.get("role", "")), "text": str(msg.get("content", ""))}
        for msg in raw_messages
        if msg.get("role") in ("user", "assistant")
    ]


def create_app(
    *,
    agent: AgentBackend | None = None,
    project_root: str | None = None,
    backend: str | None = None,
) -> FastAPI:
    root = os.path.abspath(project_root or os.getcwd())
    apply_llm_config_to_env()
    if agent is None:
        try:
            agent = load_agent(backend or os.getenv("GA_REACT_BACKEND", "classic"))
        except Exception as exc:
            if os.getenv("GA_REACT_ALLOW_UNCONFIGURED", "1") == "0" or not _is_configuration_error(exc):
                raise
            agent = UnconfiguredAgentBackend(str(exc))
    runtime = ReactApiRuntime(agent, project_root=root)
    app = FastAPI(title="GenericAgent React API")
    app.state.runtime = runtime

    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://127.0.0.1:5173",
            "http://localhost:5173",
            "app://.",
        ],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/api/status")
    def status():
        return runtime.status()

    @app.get("/api/settings")
    def settings():
        return runtime.settings()

    @app.patch("/api/settings")
    def update_settings(patch: SettingsPatch):
        return runtime.update_settings(patch)

    @app.get("/api/llm-config")
    def llm_config():
        return runtime.llm_config()

    @app.patch("/api/llm-config")
    def update_llm_config(patch: LlmConfigPatch):
        return runtime.update_llm_config(patch)

    @app.post("/api/llm-config/check")
    def check_llm_config_endpoint(request: LlmConfigCheckRequest):
        return runtime.check_llm_config(request)

    @app.post("/api/runs", response_model=RunCreateResponse)
    def create_run(request: RunCreateRequest):
        return runtime.create_run(request)

    @app.get("/api/runs/{run_id}/events")
    def run_events(run_id: str):
        return StreamingResponse(runtime.stream_events(run_id), media_type="text/event-stream")

    @app.post("/api/runs/{run_id}/stop", response_model=StopRunResponse)
    def stop_run(run_id: str):
        return runtime.stop_run(run_id)

    @app.post("/api/actions/new-chat")
    def new_chat():
        return runtime.reset_conversation()

    @app.post("/api/actions/switch-key")
    def switch_key(request: SwitchKeyRequest):
        return runtime.switch_key(request)

    @app.post("/api/actions/reinject-tools")
    def reinject_tools():
        return runtime.reinject_tools()

    @app.post("/api/autonomous/trigger", response_model=RunCreateResponse)
    def autonomous_trigger(request: AutonomousTriggerRequest):
        return runtime.trigger_autonomous(request)

    @app.post("/api/attachments")
    def upload_attachments(request: AttachmentUploadRequest):
        return runtime.upload_attachments(request)

    @app.get("/api/history")
    def history():
        return runtime.list_history()

    @app.get("/api/history/{history_id}")
    def history_detail(history_id: str):
        return runtime.get_history(history_id)

    @app.post("/api/history/{history_id}/restore")
    def history_restore(history_id: str):
        return runtime.restore_history(history_id)

    @app.post("/api/history/{history_id}/distill-delete")
    def history_distill_delete(history_id: str):
        return runtime.distill_delete_history(history_id)

    @app.get("/api/memory")
    def memory():
        return runtime.memory()

    return app


def _is_configuration_error(exc: Exception) -> bool:
    text = str(exc).lower()
    return any(
        marker in text
        for marker in (
            "api key",
            "mykey",
            "key configuration",
            "llm config",
            "no valid backend",
            "no backend",
        )
    )
