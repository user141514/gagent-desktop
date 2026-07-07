from __future__ import annotations

import json
import re
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


_ALLOWED_EVENT_TYPES = {
    "run_started",
    "context_injected",
    "tool_call",
    "tool_result",
    "decision",
    "quality_gate",
    "experience_candidate",
    "smoke_test",
    "file_change",
    "run_finished",
}

_SAFE_ID_RE = re.compile(r"[^A-Za-z0-9_.-]+")


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_run_id(prefix: str = "run") -> str:
    return f"{prefix}_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}_{uuid.uuid4().hex[:8]}"


def _safe_run_id(run_id: str) -> str:
    value = str(run_id or "").strip()
    if not value:
        raise ValueError("run_id is required")
    value = _SAFE_ID_RE.sub("_", value)
    return value[:160]


def default_ledger_dir(project_root: str | Path | None = None) -> Path:
    if project_root is None:
        # .../backend/runtime_ledger/ledger.py -> .../backend/runtime_ledger/runs
        return Path(__file__).resolve().parent / "runs"
    return Path(project_root).resolve() / "backend" / "runtime_ledger" / "runs"


def _jsonable(value: Any) -> Any:
    try:
        json.dumps(value, ensure_ascii=False, default=str)
        return value
    except Exception:
        return str(value)


@dataclass(frozen=True)
class LedgerEvent:
    run_id: str
    event_type: str
    ts: str = field(default_factory=_utc_now_iso)
    turn: int | None = None
    task: str = ""
    owner_layer: str = ""
    tool: str = ""
    args: dict[str, Any] = field(default_factory=dict)
    result: dict[str, Any] = field(default_factory=dict)
    decision: dict[str, Any] = field(default_factory=dict)
    experience_ids_used: list[str] = field(default_factory=list)
    smoke_tests: list[str] = field(default_factory=list)
    final_status: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        if self.event_type not in _ALLOWED_EVENT_TYPES:
            raise ValueError(f"unsupported event_type: {self.event_type}")
        payload = asdict(self)
        payload["run_id"] = _safe_run_id(payload["run_id"])
        payload["args"] = _jsonable(payload.get("args") or {})
        payload["result"] = _jsonable(payload.get("result") or {})
        payload["decision"] = _jsonable(payload.get("decision") or {})
        payload["metadata"] = _jsonable(payload.get("metadata") or {})
        payload["experience_ids_used"] = [str(x) for x in payload.get("experience_ids_used") or []]
        payload["smoke_tests"] = [str(x) for x in payload.get("smoke_tests") or []]
        return payload


def coerce_event(event: LedgerEvent | dict[str, Any]) -> dict[str, Any]:
    if isinstance(event, LedgerEvent):
        return event.to_dict()
    if not isinstance(event, dict):
        raise TypeError("event must be LedgerEvent or dict")
    payload = dict(event)
    payload.setdefault("ts", _utc_now_iso())
    payload.setdefault("args", {})
    payload.setdefault("result", {})
    payload.setdefault("decision", {})
    payload.setdefault("experience_ids_used", [])
    payload.setdefault("smoke_tests", [])
    payload.setdefault("metadata", {})
    if not payload.get("run_id"):
        raise ValueError("run_id is required")
    if payload.get("event_type") not in _ALLOWED_EVENT_TYPES:
        raise ValueError(f"unsupported event_type: {payload.get('event_type')}")
    payload["run_id"] = _safe_run_id(str(payload["run_id"]))
    return _jsonable(payload)


def event_path(run_id: str, ledger_dir: str | Path | None = None) -> Path:
    base = Path(ledger_dir) if ledger_dir is not None else default_ledger_dir()
    return base / f"{_safe_run_id(run_id)}.jsonl"


def write_event(event: LedgerEvent | dict[str, Any], ledger_dir: str | Path | None = None) -> Path:
    payload = coerce_event(event)
    path = event_path(payload["run_id"], ledger_dir=ledger_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, default=str, sort_keys=True) + "\n")
    return path


def read_run_events(run_id: str, ledger_dir: str | Path | None = None) -> list[dict[str, Any]]:
    path = event_path(run_id, ledger_dir=ledger_dir)
    if not path.exists():
        return []
    events = []
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid JSONL at {path}:{line_no}: {exc}") from exc
    return events


def iter_run_files(ledger_dir: str | Path | None = None) -> Iterable[Path]:
    base = Path(ledger_dir) if ledger_dir is not None else default_ledger_dir()
    if not base.exists():
        return []
    return sorted(base.glob("*.jsonl"))


def summarize_run(run_id: str, ledger_dir: str | Path | None = None) -> dict[str, Any]:
    events = read_run_events(run_id, ledger_dir=ledger_dir)
    tools: dict[str, int] = {}
    failures: list[dict[str, Any]] = []
    decisions: list[dict[str, Any]] = []
    smoke_tests: list[str] = []
    final_status = None
    task = ""
    owner_layer = ""

    for event in events:
        task = task or str(event.get("task") or "")
        owner_layer = owner_layer or str(event.get("owner_layer") or "")
        tool = str(event.get("tool") or "")
        if tool:
            tools[tool] = tools.get(tool, 0) + 1
        result = event.get("result") or {}
        if isinstance(result, dict) and str(result.get("status") or "").lower() in {"error", "failed", "timeout", "blocked"}:
            failures.append({
                "event_type": event.get("event_type"),
                "tool": tool,
                "status": result.get("status"),
                "msg": result.get("msg") or result.get("error") or "",
            })
        if event.get("decision"):
            decisions.append(event.get("decision") or {})
        smoke_tests.extend(str(x) for x in event.get("smoke_tests") or [])
        if event.get("final_status"):
            final_status = event.get("final_status")

    return {
        "run_id": _safe_run_id(run_id),
        "event_count": len(events),
        "task": task,
        "owner_layer": owner_layer,
        "tools": tools,
        "failure_count": len(failures),
        "failures": failures,
        "decisions": decisions,
        "smoke_tests": sorted(set(smoke_tests)),
        "final_status": final_status,
    }
