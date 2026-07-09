from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

from .ledger import _safe_run_id, read_run_events, summarize_run


TOOL_RUNTIME_EVENTS = {"tool_requested", "tool_allowed", "tool_started", "tool_completed", "tool_failed", "tool_blocked"}
RUNTIME_HOST_SUMMARY_FIELDS = frozenset({
    "event_count",
    "event_types",
    "session_ids",
    "tools",
    "started_turns",
    "completed_turns",
    "final_status",
})
RUNTIME_OBSERVABILITY_ALIGNED_FIELDS = frozenset({
    "has_ledger_events",
    "has_runtime_host_events",
    "ledger_run_id_matches_requested",
    "runtime_session_matches_run_id",
})
RUNTIME_OBSERVABILITY_FIELDS = frozenset({
    "run_id",
    "ledger",
    "runtime_host",
    "aligned",
})


def runtime_host_events_path(run_id: str, runtime_host_logs_root: str | Path) -> Path:
    base = Path(runtime_host_logs_root).resolve()
    path = (base / _safe_run_id(run_id) / "events.jsonl").resolve()
    if base != path and base not in path.parents:
        raise ValueError("runtime_host events path escaped logs root")
    return path


def read_runtime_host_events(run_id: str, runtime_host_logs_root: str | Path | None = None) -> list[dict[str, Any]]:
    if runtime_host_logs_root is None:
        return []
    path = runtime_host_events_path(run_id, runtime_host_logs_root)
    if not path.exists():
        return []
    events: list[dict[str, Any]] = []
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid RuntimeHost JSONL at {path}:{line_no}: {exc}") from exc
    return events


def summarize_runtime_host_events(events: list[dict[str, Any]]) -> dict[str, Any]:
    event_types = [str(event.get("event_type") or "") for event in events]
    tools: Counter[str] = Counter()
    started_turns: list[int] = []
    completed_turns: list[int] = []
    for event in events:
        event_type = str(event.get("event_type") or "")
        payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
        tool_name = str(payload.get("tool_name") or "")
        if event_type in TOOL_RUNTIME_EVENTS and tool_name:
            tools[tool_name] += 1
        if event_type == "llm_call_started":
            _append_turn(started_turns, event, payload)
        elif event_type == "llm_call_completed":
            _append_turn(completed_turns, event, payload)
    final_status = ""
    if "session_completed" in event_types:
        final_status = "completed"
    elif "session_failed" in event_types:
        final_status = "failed"
    elif "session_stopped" in event_types:
        final_status = "stopped"
    return {
        "event_count": len(events),
        "event_types": event_types,
        "session_ids": sorted({str(event.get("session_id") or "") for event in events if event.get("session_id")}),
        "tools": dict(sorted(tools.items())),
        "started_turns": started_turns,
        "completed_turns": completed_turns,
        "final_status": final_status,
    }


def summarize_observability(
    run_id: str,
    *,
    ledger_dir: str | Path | None = None,
    runtime_host_logs_root: str | Path | None = None,
) -> dict[str, Any]:
    ledger_events = read_run_events(run_id, ledger_dir=ledger_dir)
    ledger_summary = summarize_run(run_id, ledger_dir=ledger_dir)
    runtime_events = read_runtime_host_events(run_id, runtime_host_logs_root)
    runtime_summary = summarize_runtime_host_events(runtime_events)
    safe_run_id = _safe_run_id(run_id)
    runtime_session_ids = set(runtime_summary.get("session_ids") or [])
    return {
        "run_id": safe_run_id,
        "ledger": ledger_summary,
        "runtime_host": runtime_summary,
        "aligned": {
            "has_ledger_events": bool(ledger_events),
            "has_runtime_host_events": bool(runtime_events),
            "ledger_run_id_matches_requested": ledger_summary.get("run_id") == safe_run_id,
            "runtime_session_matches_run_id": runtime_session_ids == {safe_run_id} if runtime_events else False,
        },
    }


def _append_turn(target: list[int], event: dict[str, Any], payload: dict[str, Any]) -> None:
    value = payload.get("turn")
    if value is None:
        value = payload.get("turn_id")
    if value is None:
        value = event.get("turn_id")
    if value is not None:
        target.append(int(value))
