import json, re, os, time
from contextlib import nullcontext
from dataclasses import dataclass
from typing import Any, Optional
from urllib.parse import urlparse

from .runtime import (
    direct_answer_enabled,
    early_stop_enabled,
    should_stop_classic_executor,
    try_direct_answer_from_tool_result,
)


@dataclass
class StepOutcome:
    data: Any
    next_prompt: Optional[str] = None
    should_exit: bool = False


def try_call_generator(func, *args, **kwargs):
    ret = func(*args, **kwargs)
    if hasattr(ret, "__iter__") and not isinstance(ret, (str, bytes, dict, list)):
        ret = yield from ret
    return ret


class BaseHandler:
    def tool_before_callback(self, tool_name, args, response):
        pass

    def tool_after_callback(self, tool_name, args, response, ret):
        pass

    def turn_end_callback(self, response, tool_calls, tool_results, turn, next_prompt, exit_reason):
        return next_prompt

    def status_callback(self, payload):
        return None

    def dispatch(self, tool_name, args, response, index=0):
        # Some Anthropic-compatible relays/models may emit an internal "thinking"
        # pseudo-tool call. Treat it as a no-op instead of derailing the turn.
        if tool_name == "thinking":
            yield "[Info] Ignoring compatibility pseudo-tool call: thinking\n"
            return StepOutcome(
                None,
                next_prompt="Ignored invalid tool call: thinking. Continue with the real tool list.",
                should_exit=False,
            )
        method_name = f"do_{tool_name}"
        if hasattr(self, method_name):
            args["_index"] = index
            _ = yield from try_call_generator(self.tool_before_callback, tool_name, args, response)
            ret = yield from try_call_generator(getattr(self, method_name), args, response)
            _ = yield from try_call_generator(self.tool_after_callback, tool_name, args, response, ret)
            return ret
        if tool_name == "bad_json":
            return StepOutcome(None, next_prompt=args.get("msg", "bad_json"), should_exit=False)
        yield f"Unknown tool: {tool_name}\n"
        return StepOutcome(None, next_prompt=f"Unknown tool {tool_name}", should_exit=False)


def json_default(o):
    if isinstance(o, set):
        return list(o)
    return str(o)


def exhaust(g):
    try:
        while True:
            next(g)
    except StopIteration as e:
        return e.value


def get_pretty_json(data):
    if isinstance(data, dict) and "script" in data:
        data = data.copy()
        data["script"] = data["script"].replace("; ", ";\n  ")
    return json.dumps(data, indent=2, ensure_ascii=False).replace("\\n", "\n")


def _profile_span(profiler, name, kind=None, metadata=None):
    if profiler is None:
        return nullcontext()
    return profiler.span(name, kind=kind, metadata=metadata)


def _emit_status(handler, payload):
    try:
        ret = handler.status_callback(payload)
        if hasattr(ret, "__iter__") and not isinstance(ret, (str, bytes, dict, list)):
            yield from ret
    except Exception:
        pass


def _tool_name(tool):
    if not isinstance(tool, dict):
        return ""
    fn = tool.get("function") or {}
    return str(fn.get("name") or tool.get("name") or "").strip()


def _tools_schema_chars(tools_schema):
    return len(json.dumps(tools_schema or [], ensure_ascii=False, separators=(",", ":")))


def _safe_preview(text, max_chars=120):
    value = str(text or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if len(value) <= max_chars:
        return value
    return value[:max_chars] + "..."


def _normalize_tool_target_path(path_value):
    raw = str(path_value or "").strip()
    if not raw:
        return None
    normalized = raw.replace("\\", "/")
    try:
        cwd = os.path.abspath(os.getcwd())
        abs_path = os.path.abspath(raw)
        common = os.path.commonpath([cwd, abs_path])
        if common == cwd:
            rel_path = os.path.relpath(abs_path, cwd)
            return rel_path.replace("\\", "/")
    except Exception:
        pass
    return normalized


def _tool_args_chars(args):
    safe_args = {k: v for k, v in (args or {}).items() if k != "_index"}
    try:
        return len(json.dumps(safe_args, ensure_ascii=False, default=json_default))
    except Exception:
        return len(str(safe_args))


def _safe_tool_arg_metadata(tool_name: str, args: dict) -> dict:
    safe_args = {k: v for k, v in (args or {}).items() if k != "_index"}
    meta: dict[str, Any] = {}
    target_path = None

    if tool_name == "file_read":
        target_path = _normalize_tool_target_path(safe_args.get("path") or safe_args.get("target_path"))
        meta["target_path"] = target_path
        if "start" in safe_args:
            meta["start"] = safe_args.get("start")
        if "count" in safe_args:
            meta["count"] = safe_args.get("count")
        if "keyword" in safe_args:
            meta["keyword_present"] = bool(str(safe_args.get("keyword") or "").strip())
        if "show_linenos" in safe_args:
            meta["show_linenos"] = bool(safe_args.get("show_linenos"))
    elif tool_name == "code_run":
        script = safe_args.get("script") or safe_args.get("code") or ""
        meta["script_chars"] = len(str(script or ""))
        if script:
            meta["script_preview"] = _safe_preview(script, max_chars=120)
        if "type" in safe_args:
            meta["type"] = str(safe_args.get("type") or "")
        if "timeout" in safe_args:
            meta["timeout"] = safe_args.get("timeout")
        if "cwd" in safe_args:
            meta["cwd"] = _normalize_tool_target_path(safe_args.get("cwd"))
    elif tool_name in {"file_write", "file_patch"}:
        target_path = _normalize_tool_target_path(safe_args.get("path") or safe_args.get("target_path"))
        meta["target_path"] = target_path
        if tool_name == "file_write":
            content = safe_args.get("content") or safe_args.get("file_content")
            if content is not None:
                meta["content_chars"] = len(str(content))
            if "mode" in safe_args:
                meta["mode"] = safe_args.get("mode")
        else:
            old_content = safe_args.get("old_content")
            new_content = safe_args.get("new_content")
            if old_content is not None or new_content is not None:
                meta["patch_chars"] = len(str(old_content or "")) + len(str(new_content or ""))
    elif tool_name.startswith("web_"):
        url = safe_args.get("url") or safe_args.get("page_url")
        if url:
            url_str = str(url)
            meta["url"] = _safe_preview(url_str, max_chars=200)
            parsed = urlparse(url_str)
            if parsed.netloc:
                meta["domain"] = parsed.netloc
        for key in ("switch_tab_id", "tab_id", "text_only", "tabs_only", "save_to_file", "no_monitor"):
            if key in safe_args:
                meta[key] = safe_args.get(key)
        if tool_name == "web_execute_js":
            script = safe_args.get("script") or ""
            meta["script_chars"] = len(str(script or ""))
    else:
        maybe_path = safe_args.get("path") or safe_args.get("target_path")
        maybe_url = safe_args.get("url") or safe_args.get("page_url")
        if maybe_path:
            meta["target_path"] = _normalize_tool_target_path(maybe_path)
        if maybe_url:
            url_str = str(maybe_url)
            meta["url"] = _safe_preview(url_str, max_chars=200)
            parsed = urlparse(url_str)
            if parsed.netloc:
                meta["domain"] = parsed.netloc

    return {k: v for k, v in meta.items() if v is not None}


def _outcome_result_text(outcome: StepOutcome) -> str:
    if outcome is None or outcome.data is None:
        return ""
    if isinstance(outcome.data, (dict, list)):
        try:
            return json.dumps(outcome.data, ensure_ascii=False, default=json_default)
        except Exception:
            return str(outcome.data)
    return str(outcome.data)


def _is_error_like_outcome(outcome: StepOutcome) -> bool:
    if outcome is None:
        return False
    result_text = _outcome_result_text(outcome).strip().lower()
    next_prompt = str(outcome.next_prompt or "").strip().lower()
    data = outcome.data
    if isinstance(data, dict) and str(data.get("status") or "").strip().lower() == "error":
        return True
    if result_text.startswith("error:") or result_text.startswith("[error]"):
        return True
    if "unknown tool" in next_prompt or next_prompt.startswith("error:"):
        return True
    return any(token in result_text for token in ("traceback", "exception", '"status": "error"', "'status': 'error'"))


def _set_llm_audit_context(client, handler, turn, tools_schema):
    backend = getattr(client, "backend", None)
    parent = getattr(handler, "parent", None)
    if backend is None:
        return
    selected_tool_names = [_tool_name(tool) for tool in (tools_schema or []) if _tool_name(tool)]
    metadata = {
        "run_id": getattr(parent, "_profile_run_id", None),
        "agent_name": "classic_executor",
        "turn": turn,
        "flow": "classic_agent_loop",
        "llm_client": getattr(client, "name", ""),
        "selected_tool_count": len(selected_tool_names),
        "available_tool_count": getattr(parent, "_available_tool_count", len(tools_schema or [])),
        "selected_tool_names": selected_tool_names,
        "tools_schema_chars": _tools_schema_chars(tools_schema),
    }
    try:
        setattr(backend, "_audit_context", {k: v for k, v in metadata.items() if v is not None})
    except Exception:
        pass


def _tool_results_text(tool_results):
    parts = []
    for item in tool_results or []:
        if isinstance(item, dict) and item.get("content") is not None:
            parts.append(str(item.get("content")))
        elif item is not None:
            parts.append(str(item))
    return "\n".join(part for part in parts if part)


def _maybe_apply_direct_answer(handler, tool_calls, tool_results, turn):
    parent = getattr(handler, "parent", None)
    profiler = getattr(parent, "active_profiler", None)
    if not direct_answer_enabled():
        return None
    if not tool_calls or all(tc.get("tool_name") == "no_tool" for tc in tool_calls):
        return None
    try:
        decision = try_direct_answer_from_tool_result(
            user_input=getattr(parent, "_current_user_input", ""),
            tool_results=tool_results,
            metadata={
                "tool_names": [tc.get("tool_name") for tc in tool_calls if tc.get("tool_name")],
                "turn": turn,
            },
        )
    except Exception as exc:
        print(f"[DIRECT_ANSWER] decision failed: {type(exc).__name__}: {exc}")
        return None
    if not decision.should_answer or not decision.answer:
        return None

    event_payload = {
        "turn": turn,
        "reason": decision.reason,
        "confidence": decision.confidence,
        "signals": decision.signals,
    }
    if profiler is not None:
        try:
            profiler.record_event("classic_executor_direct_answer", kind="agent", metadata=event_payload)
        except Exception:
            pass
    if parent is not None:
        try:
            parent._last_direct_answer = dict(event_payload)
        except Exception:
            pass
    print(
        f"[DIRECT_ANSWER] turn={turn} confidence={decision.confidence} "
        f"reason={decision.reason}"
    )
    return {
        "result": "DIRECT_ANSWER",
        "data": decision.answer,
        "meta": event_payload,
        "answer": decision.answer,
    }


def _maybe_apply_early_stop(client, handler, response, tool_calls, tool_results, turn):
    parent = getattr(handler, "parent", None)
    profiler = getattr(parent, "active_profiler", None)
    if not early_stop_enabled():
        return None
    if not tool_calls or all(tc.get("tool_name") == "no_tool" for tc in tool_calls):
        return None
    try:
        decision = should_stop_classic_executor(
            user_input=getattr(parent, "_current_user_input", ""),
            last_assistant_text=getattr(response, "content", "") or "",
            tool_results=tool_results,
            turn_index=turn,
            metadata={
                "tool_names": [tc.get("tool_name") for tc in tool_calls if tc.get("tool_name")],
                "tool_results_chars": len(_tool_results_text(tool_results)),
            },
        )
    except Exception as exc:
        print(f"[EARLY_STOP] decision failed: {type(exc).__name__}: {exc}")
        return None
    if not decision.should_stop:
        return None

    event_payload = {
        "turn": turn,
        "reason": decision.reason,
        "confidence": decision.confidence,
        "signals": decision.signals,
    }
    if profiler is not None:
        try:
            profiler.record_event("classic_executor_early_stop", kind="agent", metadata=event_payload)
        except Exception:
            pass
    if parent is not None:
        try:
            parent._last_early_stop = dict(event_payload)
        except Exception:
            pass
    print(
        f"[EARLY_STOP] turn={turn} confidence={decision.confidence} "
        f"reason={decision.reason}"
    )
    return {"result": "EARLY_STOP", "data": response, "meta": event_payload}


def agent_runner_loop(client, system_prompt, user_input, handler, tools_schema, max_turns=80, verbose=True, initial_user_content=None, stop_event=None, runtime_mapper=None, formatter=None, turn_gap=0.0):
    # ── Formatter: backward-compat construction from verbose flag ──
    if formatter is None:
        if verbose:
            from core.protocol.formatter import VerboseFormatter
            formatter = VerboseFormatter()
        else:
            from core.protocol.formatter import CompactFormatter
            formatter = CompactFormatter()

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": initial_user_content if initial_user_content is not None else user_input},
    ]
    profiler = getattr(getattr(handler, "parent", None), "active_profiler", None)
    turn = 0
    exit_reason = None
    handler._done_hooks = []
    handler.max_turns = max_turns
    handler._last_user_input = user_input

    # ── M7: Tool Event Ledger initialization ──
    import os as _os_m7
    if _os_m7.environ.get("GA_TOOL_EVENT_LEDGER", "").strip() == "1":
        try:
            from core.context.tool_event_ledger import ToolEventLedger
            handler._tool_event_ledger = ToolEventLedger()
        except Exception:
            handler._tool_event_ledger = None
    else:
        handler._tool_event_ledger = None

    def _stopped():
        return stop_event and stop_event.is_set()

    while turn < handler.max_turns:
        if _stopped():
            yield "\n\n[已停止输出]\n"
            break
        turn += 1
        handler.current_turn = turn
        # ── Runtime: emit turn_start event ──
        if runtime_mapper is not None:
            runtime_mapper.on_turn_start(turn)
        with _profile_span(profiler, f"agent_turn_{turn}", kind="agent", metadata={"turn": turn}):
            status_payload = {
                "type": "status",
                "event_type": "classic_turn_started",
                "scope": "classic_executor",
                "agent_name": "classic_executor",
                "classic_turn": turn,
                "max_turns": handler.max_turns,
                "message": f"Classic executor running turn {turn}",
            }
            if profiler is not None:
                try:
                    profiler.record_event(
                        "classic_executor_turn_started",
                        kind="agent",
                        metadata={
                            "classic_turn": turn,
                            "max_turns": handler.max_turns,
                            "scope": "classic_executor",
                            "agent_name": "classic_executor",
                        },
                    )
                except Exception:
                    pass
            yield from _emit_status(handler, status_payload)
            yield formatter.format_turn_start(turn)
            if turn % 10 == 0:
                client.last_tools = ""
            _set_llm_audit_context(client, handler, turn, tools_schema)
            with _profile_span(
                profiler,
                f"llm_call_turn_{turn}",
                kind="llm",
                metadata={"turn": turn, "model": getattr(getattr(client, "backend", None), "name", "")},
            ):
                if _stopped():
                    yield "\n\n[已停止输出]\n"
                    break
                response_gen = client.chat(messages=messages, tools=tools_schema)
                if formatter.is_verbose():
                    _resp = None
                    while True:
                        if _stopped():
                            break
                        try:
                            chunk = next(response_gen)
                            if isinstance(chunk, dict) and "_thinking_delta" in chunk:
                                yield from _emit_status(handler, {
                                    "type": "status",
                                    "event_type": "thinking_delta",
                                    "scope": "classic_executor",
                                    "message": chunk["_thinking_delta"],
                                    "classic_turn": turn,
                                })
                            else:
                                yield chunk
                        except StopIteration as e:
                            _resp = e.value
                            break
                    if _stopped():
                        yield "\n\n[已停止输出]\n"
                        break
                    response = _resp
                    yield "\n\n"
                else:
                    response = exhaust(response_gen)
                    if response.thinking:
                        yield from _emit_status(handler, {
                            "type": "status",
                            "event_type": "thinking_blocks",
                            "scope": "classic_executor",
                            "message": response.thinking,
                            "classic_turn": turn,
                        })
                    cleaned = formatter.clean_content(response.content)
                    if cleaned:
                        yield cleaned + "\n"

            if _stopped():
                break

            if not response.tool_calls:
                tool_calls = [{"tool_name": "no_tool", "args": {}}]
            else:
                tool_calls = [
                    {"tool_name": tc.function.name, "args": json.loads(tc.function.arguments), "id": tc.id}
                    for tc in response.tool_calls
                ]

            tool_results = []
            all_tool_results = []
            next_prompts = set()
            for ii, tc in enumerate(tool_calls):
                if _stopped():
                    break
                tool_name, args, tid = tc["tool_name"], tc["args"], tc.get("id", "")
                tool_args_summary = _safe_tool_arg_metadata(tool_name, args)
                tool_target_path = (
                    tool_args_summary.get("target_path")
                    or tool_args_summary.get("path")
                )
                tool_args_chars = _tool_args_chars(args)
                if runtime_mapper is not None:
                    runtime_mapper.on_tool_requested(tool_name, args)
                if tool_name != "no_tool":
                    yield formatter.format_tool_call(tool_name, args)
                _ledger = getattr(handler, "_tool_event_ledger", None)
                _ledger_event_id = ""
                if _ledger is not None and tool_name != "no_tool":
                    try:
                        _ledger_event_id = _ledger.start_call(
                            tool_name=tool_name,
                            args=args,
                            target_path=tool_target_path,
                            turn=turn,
                            index=ii,
                        )
                    except Exception:
                        _ledger_event_id = ""
                with _profile_span(
                    profiler,
                    f"tool_call:{tool_name}",
                    kind="tool",
                    metadata={
                        "turn": turn,
                        "tool": tool_name,
                        "index": ii,
                        "tool_args_summary": tool_args_summary or None,
                        "tool_target_path": tool_target_path,
                        "tool_args_chars": tool_args_chars,
                    },
                ):
                    gen = handler.dispatch(tool_name, args, response, index=ii)
                    try:
                        first_value = next(gen)

                        def proxy():
                            yield first_value
                            if _stopped():
                                return None
                            return (yield from gen)

                        if formatter.is_verbose() and not formatter.hide_tool_calls():
                            yield "`````\n"
                        outcome = (yield from proxy()) if (formatter.is_verbose() and not formatter.hide_tool_calls()) else exhaust(proxy())
                        if formatter.is_verbose() and not formatter.hide_tool_calls():
                            yield "`````\n"
                    except StopIteration as e:
                        outcome = e.value
                    except BaseException as e:
                        if _ledger is not None and _ledger_event_id:
                            try:
                                _ledger.complete_call(
                                    event_id=_ledger_event_id,
                                    result=f"{type(e).__name__}: {e}",
                                    status="error",
                                    result_chars=len(str(e)),
                                    error_like=True,
                                )
                            except Exception:
                                pass
                        raise

                if profiler is not None:
                    try:
                        profiler.record_event(
                            "tool_call_result",
                            kind="tool",
                            metadata={
                                "turn": turn,
                                "tool": tool_name,
                                "index": ii,
                                "tool_target_path": tool_target_path,
                                "result_chars": len(_outcome_result_text(outcome)),
                                "error_like": _is_error_like_outcome(outcome),
                            },
                        )
                    except Exception:
                        pass
                # ── Runtime: emit tool_completed event ──
                if runtime_mapper is not None:
                    outcome_text = _outcome_result_text(outcome)
                    runtime_mapper.on_tool_completed(
                        tool_name,
                        outcome_text[:200] if outcome_text else "",
                    )

                # ── M7: Tool Event Ledger recording hook ──
                # Minimal, gated, non-blocking. Records executed facts only.
                if _ledger is not None and _ledger_event_id:
                    try:
                        _result_text = _outcome_result_text(outcome)
                        _ledger.complete_call(
                            event_id=_ledger_event_id,
                            result=_result_text,
                            status="error" if _is_error_like_outcome(outcome) else "success",
                            result_chars=len(_result_text),
                            error_like=_is_error_like_outcome(outcome),
                        )
                    except Exception:
                        pass  # ledger failure must never block agent loop

                if outcome.should_exit:
                    exit_reason = {"result": "EXITED", "data": outcome.data}
                    break
                if not outcome.next_prompt:
                    exit_reason = {"result": "CURRENT_TASK_DONE", "data": outcome.data}
                    break
                if outcome.next_prompt.startswith("Unknown tool"):
                    client.last_tools = ""
                if outcome.data is not None and tool_name != "no_tool":
                    datastr = (
                        json.dumps(outcome.data, ensure_ascii=False, default=json_default)
                        if type(outcome.data) in [dict, list]
                        else str(outcome.data)
                    )
                    result_item = {"tool_use_id": tid, "content": datastr}
                    all_tool_results.append(result_item)
                    tool_results.append(result_item)
                    if len(all_tool_results) > 20 and len(tool_results) > 10:
                        tool_results[:] = tool_results[-10:]
                next_prompts.add(outcome.next_prompt)

            if not exit_reason and next_prompts:
                direct_answer_reason = _maybe_apply_direct_answer(
                    handler,
                    tool_calls,
                    all_tool_results,
                    turn,
                )
                if direct_answer_reason is not None:
                    yield "\n[Info] Direct answer from tool results.\n"
                    yield str(direct_answer_reason.get("answer") or "").rstrip() + "\n"
                    exit_reason = direct_answer_reason

            if not exit_reason and next_prompts:
                early_stop_reason = _maybe_apply_early_stop(
                    client,
                    handler,
                    response,
                    tool_calls,
                    all_tool_results,
                    turn,
                )
                if early_stop_reason is not None:
                    exit_reason = early_stop_reason

            if exit_reason:
                if runtime_mapper is not None:
                    runtime_mapper.on_turn_end(turn)
                break
            if len(next_prompts) == 0:
                if len(handler._done_hooks) == 0:
                    break
                next_prompts.add(handler._done_hooks.pop(0))

            # ── Runtime: emit turn_end event ──
            if runtime_mapper is not None:
                runtime_mapper.on_turn_end(turn)
            with _profile_span(profiler, f"frontend_turn_gap_{turn}", kind="frontend", metadata={"turn": turn}):
                if turn_gap > 0:
                    time.sleep(turn_gap)
            with _profile_span(profiler, f"turn_end_{turn}", kind="agent", metadata={"turn": turn}):
                next_prompt = handler.turn_end_callback(
                    response,
                    tool_calls,
                    tool_results,
                    turn,
                    "\n".join(next_prompts),
                    exit_reason,
                )
            messages = [{"role": "user", "content": next_prompt, "tool_results": tool_results}]
    if exit_reason:
        handler.turn_end_callback(response, tool_calls, tool_results, turn, "", exit_reason)
    return exit_reason or {"result": "MAX_TURNS_EXCEEDED"}
