"""Local JSON-file cache and audit helpers for LLM calls."""

from __future__ import annotations

import hashlib
import json
import queue
import re
import threading
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SAFE_CACHE_TYPES = {
    "file_summary",
    "project_structure_summary",
    "static_prompt_render",
    "sop_summary",
    "deterministic_planning_draft",
}

UNSAFE_CACHE_TYPES = {
    "final_answer",
    "user_chat_response",
    "streaming_response",
    "browser_result",
    "realtime_search",
    "tool_result_with_external_state",
}

PREVIEW_LIMIT = 500
HISTORY_BLOCK_PATTERNS = (
    r"<history>[\s\S]*?</history>",
    r"<conversation_history>[\s\S]*?</conversation_history>",
)
HISTORY_KEYWORDS = (
    "working memory",
    "conversation history",
    "chat history",
    "dialogue history",
    "recent context",
    "[working memory]",
)
MEMORY_BLOCK_PATTERNS = (
    r"<memory>[\s\S]*?</memory>",
    r"<global_mem>[\s\S]*?</global_mem>",
    r"<insight>[\s\S]*?</insight>",
    r"<key_info>[\s\S]*?</key_info>",
)
MEMORY_KEYWORDS = (
    "global_mem",
    "global memory",
    "insight",
    "sop",
    "memory management",
    "<memory",
    "key_info",
)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize_value(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(k): _normalize_value(value[k]) for k in sorted(value)}
    if isinstance(value, set):
        return sorted(_normalize_value(v) for v in value)
    if isinstance(value, (list, tuple)):
        return [_normalize_value(v) for v in value]
    return str(value)


def _stable_json(value: Any) -> str:
    return json.dumps(
        _normalize_value(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _preview_text(value: Any, limit: int = PREVIEW_LIMIT) -> str:
    text = value if isinstance(value, str) else _stable_json(value)
    text = str(text).strip()
    return text[:limit]


def _text_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return _stable_json(value)


def _char_len(value: Any) -> int:
    return len(_text_value(value))


def _message_content_chars(message: dict[str, Any]) -> int:
    total = _char_len(message.get("content"))
    total += _char_len(message.get("tool_calls"))
    return total


def _flatten_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "\n".join(part for part in (_flatten_text(item) for item in value) if part)
    if isinstance(value, dict):
        if isinstance(value.get("text"), str):
            return value["text"]
        pieces = []
        for key, item in value.items():
            if key == "cache_control":
                continue
            text = _flatten_text(item)
            if text:
                pieces.append(text)
        return "\n".join(pieces)
    return str(value)


def _messages_analysis_text(messages: list[dict[str, Any]] | str) -> str:
    if isinstance(messages, str):
        return messages
    sections = []
    for message in messages:
        if not isinstance(message, dict):
            text = _flatten_text(message)
            if text:
                sections.append(text)
            continue
        role = str(message.get("role") or "user").lower()
        parts = [f"[{role}]"]
        for key in ("content", "tool_results", "tool_calls"):
            text = _flatten_text(message.get(key))
            if text:
                parts.append(text)
        sections.append("\n".join(parts))
    return "\n\n".join(section for section in sections if section)


def _tool_payload_chars(message: dict[str, Any]) -> int:
    total = 0
    total += _char_len(message.get("tool_results"))
    if str(message.get("role") or "").strip().lower() == "tool":
        total += _char_len(message.get("content"))
        total += _char_len(message.get("tool_call_id"))
    return total


def _messages_breakdown(messages: list[dict[str, Any]] | str) -> dict[str, int]:
    if isinstance(messages, str):
        prompt_chars = len(messages)
        return {
            "prompt_chars": prompt_chars,
            "message_count": 1,
            "system_chars": 0,
            "user_chars": prompt_chars,
            "assistant_chars": 0,
            "tool_chars": 0,
        }

    prompt_chars = _char_len(messages)
    system_chars = 0
    user_chars = 0
    assistant_chars = 0
    tool_chars = 0

    for message in messages:
        if not isinstance(message, dict):
            user_chars += _char_len(message)
            continue
        role = str(message.get("role") or "").strip().lower()
        content_chars = _message_content_chars(message)
        tool_chars += _tool_payload_chars(message)
        if role == "system":
            system_chars += content_chars
        elif role == "assistant":
            assistant_chars += content_chars
        elif role == "tool":
            tool_chars += content_chars
        else:
            user_chars += content_chars

    return {
        "prompt_chars": prompt_chars,
        "message_count": len(messages),
        "system_chars": system_chars,
        "user_chars": user_chars,
        "assistant_chars": assistant_chars,
        "tool_chars": tool_chars,
    }


def _segment_chars(text: str, block_patterns: tuple[str, ...], keywords: tuple[str, ...]) -> int:
    if not text:
        return 0
    total = 0
    remaining = text
    for pattern in block_patterns:
        matches = list(re.finditer(pattern, remaining, flags=re.IGNORECASE))
        total += sum(len(match.group(0)) for match in matches)
        remaining = re.sub(pattern, "\n", remaining, flags=re.IGNORECASE)

    for paragraph in re.split(r"\n\s*\n", remaining):
        stripped = paragraph.strip()
        if not stripped:
            continue
        lowered = stripped.lower()
        if any(keyword in lowered for keyword in keywords):
            total += len(stripped)
    return total


def _audit_stats(
    *,
    messages: list[dict] | str,
    response: str | dict | None,
    tools: list[dict] | None,
    metadata: dict[str, Any] | None,
) -> dict[str, int | float]:
    prompt_text = _messages_analysis_text(messages)
    response_text = _text_value(response or "")
    msg_stats = _messages_breakdown(messages)
    if metadata and metadata.get("tools_schema_chars") is not None:
        try:
            tools_schema_chars = int(metadata.get("tools_schema_chars") or 0)
        except (TypeError, ValueError):
            tools_schema_chars = _char_len(tools or []) if tools else 0
    else:
        tools_schema_chars = _char_len(tools or []) if tools else 0
    prompt_chars = int(msg_stats["prompt_chars"])
    response_chars = len(response_text)
    return {
        **msg_stats,
        "prompt_chars": prompt_chars,
        "response_chars": response_chars,
        "history_chars": _segment_chars(prompt_text, HISTORY_BLOCK_PATTERNS, HISTORY_KEYWORDS),
        "memory_chars": _segment_chars(prompt_text, MEMORY_BLOCK_PATTERNS, MEMORY_KEYWORDS),
        "tools_schema_chars": tools_schema_chars,
        "estimated_prompt_tokens": round(prompt_chars / 4.0, 3),
        "estimated_response_tokens": round(response_chars / 4.0, 3),
    }


def _cache_namespace(metadata: dict[str, Any] | None) -> str:
    data = metadata or {}
    for key in ("cache_namespace", "task_type", "cache_type"):
        value = data.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def is_cache_safe(metadata: dict | None = None) -> bool:
    cache_type = str((metadata or {}).get("cache_type") or "").strip()
    if not cache_type:
        return False
    if cache_type in UNSAFE_CACHE_TYPES:
        return False
    return cache_type in SAFE_CACHE_TYPES


@dataclass
class LLMCallRecord:
    id: str
    model: str
    prompt_hash: str
    prompt_preview: str
    response_preview: str
    duration_ms: float
    created_at: str
    metadata: dict[str, Any] = field(default_factory=dict)
    prompt_chars: int = 0
    response_chars: int = 0
    message_count: int = 0
    system_chars: int = 0
    user_chars: int = 0
    assistant_chars: int = 0
    tool_chars: int = 0
    history_chars: int = 0
    memory_chars: int = 0
    tools_schema_chars: int = 0
    estimated_prompt_tokens: float = 0.0
    estimated_response_tokens: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class LLMCallCache:
    def __init__(self, cache_dir: str | Path = "temp/llm_cache") -> None:
        self.cache_dir = Path(cache_dir)
        self.entries_dir = self.cache_dir / "entries"
        self.records_path = self.cache_dir / "records.jsonl"
        self.entries_dir.mkdir(parents=True, exist_ok=True)
        self.records_path.parent.mkdir(parents=True, exist_ok=True)
        # Background queue for non-blocking audit writes.
        self._audit_queue: queue.Queue[dict[str, Any] | None] = queue.Queue()
        self._audit_thread = threading.Thread(target=self._audit_worker, daemon=True)
        self._audit_thread.start()

    def _audit_worker(self) -> None:
        """Daemon thread: consume audit tasks, compute stats, write to disk."""
        while True:
            task = self._audit_queue.get()
            if task is None:
                break
            try:
                record_dict = self._build_audit_record(
                    model=task["model"],
                    messages=task["messages"],
                    response=task["response"],
                    duration_ms=task["duration_ms"],
                    tools=task["tools"],
                    metadata=task["metadata"],
                )
                with self.records_path.open("a", encoding="utf-8") as f:
                    f.write(json.dumps(record_dict, ensure_ascii=False) + "\n")
            except Exception:
                pass

    def make_key(
        self,
        model: str,
        messages: list[dict] | str,
        tools: list[dict] | None = None,
        temperature: float | None = None,
        metadata: dict | None = None,
    ) -> str:
        payload = {
            "model": str(model or "").strip(),
            "messages": _normalize_value(messages),
            "tools": _normalize_value(tools or []),
            "temperature": temperature,
            "namespace": _cache_namespace(metadata),
        }
        return hashlib.sha256(_stable_json(payload).encode("utf-8")).hexdigest()

    def get(self, key: str) -> dict | None:
        path = self.entries_dir / f"{key}.json"
        if not path.exists():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        return payload.get("value") if isinstance(payload, dict) else None

    def set(self, key: str, value: dict, record: LLMCallRecord | None = None) -> None:
        path = self.entries_dir / f"{key}.json"
        payload = {
            "key": key,
            "value": _normalize_value(value),
            "record": record.to_dict() if record is not None else None,
            "updated_at": _utc_now_iso(),
        }
        tmp_path = path.with_suffix(".json.tmp")
        tmp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp_path.replace(path)

    def _build_audit_record(
        self,
        model: str,
        messages: list[dict] | str,
        response: str | dict | None,
        duration_ms: float,
        tools: list[dict] | None = None,
        metadata: dict | None = None,
    ) -> dict[str, Any]:
        """Compute stats and build a record dict (heavy work, runs in bg thread or sync)."""
        stats = _audit_stats(messages=messages, response=response, tools=tools, metadata=metadata)
        prompt_hash = self.make_key(
            model=model,
            messages=messages,
            tools=tools,
            temperature=(metadata or {}).get("temperature"),
            metadata=metadata,
        )
        record = LLMCallRecord(
            id=uuid.uuid4().hex,
            model=str(model or "").strip(),
            prompt_hash=prompt_hash,
            prompt_preview=_preview_text(messages),
            response_preview=_preview_text(response or ""),
            duration_ms=round(float(duration_ms), 3),
            created_at=_utc_now_iso(),
            metadata=dict(metadata or {}),
            prompt_chars=int(stats["prompt_chars"]),
            response_chars=int(stats["response_chars"]),
            message_count=int(stats["message_count"]),
            system_chars=int(stats["system_chars"]),
            user_chars=int(stats["user_chars"]),
            assistant_chars=int(stats["assistant_chars"]),
            tool_chars=int(stats["tool_chars"]),
            history_chars=int(stats["history_chars"]),
            memory_chars=int(stats["memory_chars"]),
            tools_schema_chars=int(stats["tools_schema_chars"]),
            estimated_prompt_tokens=float(stats["estimated_prompt_tokens"]),
            estimated_response_tokens=float(stats["estimated_response_tokens"]),
        )
        return record.to_dict()

    def audit(
        self,
        model: str,
        messages: list[dict] | str,
        response: str | dict | None,
        duration_ms: float,
        tools: list[dict] | None = None,
        metadata: dict | None = None,
    ) -> None:
        """Enqueue audit work to a background thread; returns immediately."""
        try:
            self._audit_queue.put_nowait({
                "model": model, "messages": messages, "response": response,
                "duration_ms": duration_ms, "tools": tools, "metadata": metadata,
            })
        except Exception:
            pass  # never block the caller on audit failures


__all__ = ["LLMCallCache", "LLMCallRecord", "is_cache_safe"]
