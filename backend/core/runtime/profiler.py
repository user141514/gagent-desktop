"""Lightweight in-memory runtime profiler."""

from __future__ import annotations

import json
import os
import time
import uuid
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


PROFILE_ENV_VAR = "GENERIC_AGENT_PROFILE"
VALID_KINDS = {
    "run",
    "agent",
    "llm",
    "tool",
    "memory",
    "io",
    "frontend",
    "unknown",
}


def _normalize_kind(kind: str | None) -> str:
    value = str(kind or "unknown").strip().lower()
    return value if value in VALID_KINDS else "unknown"


def _new_id() -> str:
    return uuid.uuid4().hex


def profiling_enabled() -> bool:
    return str(os.environ.get(PROFILE_ENV_VAR, "")).strip() == "1"


def build_profile_path(base_dir: str | Path, run_id: str, timestamp: str | None = None) -> Path:
    stamp = timestamp or time.strftime("%Y%m%d_%H%M%S")
    safe_run_id = str(run_id or "run").replace(os.sep, "_").replace(":", "_")
    return Path(base_dir) / f"profile_{safe_run_id}_{stamp}.json"


def format_profile_summary(summary: dict[str, Any], top_n: int = 10) -> str:
    by_kind = summary.get("by_kind") or {}
    slowest = list(summary.get("slowest_spans") or [])[:top_n]

    def _kind_total(kind: str) -> float:
        bucket = by_kind.get(kind) or {}
        return float(bucket.get("total_duration_ms") or 0.0)

    lines = [
        f"[PROFILE] run_id={summary.get('run_id')} total_duration_ms={summary.get('total_duration_ms')}",
        f"[PROFILE] by_kind={json.dumps(by_kind, ensure_ascii=False, sort_keys=True)}",
        f"[PROFILE] llm_total_ms={round(_kind_total('llm'), 3)} tool_total_ms={round(_kind_total('tool'), 3)} "
        f"memory_total_ms={round(_kind_total('memory'), 3)} agent_total_ms={round(_kind_total('agent'), 3)}",
        "[PROFILE] slowest_spans=",
    ]
    if not slowest:
        lines.append("  - none")
    else:
        for item in slowest:
            lines.append(
                f"  - {item.get('name')} [{item.get('kind')}] {item.get('duration_ms')} ms"
            )
    return "\n".join(lines)


@dataclass
class SpanRecord:
    id: str
    parent_id: str | None
    run_id: str
    name: str
    kind: str
    start_time: float
    end_time: float | None = None
    duration_ms: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    _perf_start: float = 0.0

    def finish(self) -> None:
        if self.end_time is not None:
            return
        self.end_time = time.time()
        self.duration_ms = round((time.perf_counter() - self._perf_start) * 1000.0, 3)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data.pop("_perf_start", None)
        return data


@dataclass
class EventRecord:
    id: str
    parent_id: str | None
    run_id: str
    name: str
    kind: str
    timestamp: float
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class RuntimeProfiler:
    def __init__(self) -> None:
        self._run_span_id: str | None = None
        self._run_id: str | None = None
        self._run_name: str | None = None
        self._spans: list[SpanRecord] = []
        self._events: list[EventRecord] = []
        self._span_index: dict[str, SpanRecord] = {}
        self._active_stack: list[str] = []

    def start_run(
        self,
        run_id: str | None = None,
        name: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        self._reset()
        self._run_id = run_id or _new_id()
        self._run_name = name or "run"
        run_span = self._create_span(
            name=self._run_name,
            kind="run",
            metadata=metadata,
            parent_id=None,
        )
        self._run_span_id = run_span.id
        self._active_stack.append(run_span.id)
        return self._run_id

    def end_run(self, status: str = "success") -> dict[str, Any]:
        if self._run_id is None or self._run_span_id is None:
            raise RuntimeError("No active run. Call start_run() first.")
        run_span = self._span_index[self._run_span_id]
        run_span.metadata = {**run_span.metadata, "status": status}
        while self._active_stack:
            span_id = self._active_stack.pop()
            self._span_index[span_id].finish()
        return self.get_summary()

    @contextmanager
    def span(
        self,
        name: str,
        kind: str | None = None,
        metadata: dict[str, Any] | None = None,
    ):
        if self._run_id is None:
            raise RuntimeError("No active run. Call start_run() before creating spans.")
        parent_id = self._active_stack[-1] if self._active_stack else None
        span = self._create_span(
            name=name,
            kind=_normalize_kind(kind),
            metadata=metadata,
            parent_id=parent_id,
        )
        self._active_stack.append(span.id)
        try:
            yield span
        finally:
            if self._active_stack and self._active_stack[-1] == span.id:
                self._active_stack.pop()
            span.finish()

    def record_event(
        self,
        name: str,
        kind: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        if self._run_id is None:
            raise RuntimeError("No active run. Call start_run() first.")
        event = EventRecord(
            id=_new_id(),
            parent_id=self._active_stack[-1] if self._active_stack else None,
            run_id=self._run_id,
            name=name,
            kind=_normalize_kind(kind),
            timestamp=time.time(),
            metadata=dict(metadata or {}),
        )
        self._events.append(event)
        return event.id

    def get_summary(self, slowest_limit: int = 10) -> dict[str, Any]:
        run_span = self._span_index.get(self._run_span_id or "")
        spans = [span for span in self._spans if span.duration_ms is not None]
        by_kind: dict[str, dict[str, Any]] = {}
        for span in spans:
            bucket = by_kind.setdefault(
                span.kind,
                {"count": 0, "total_duration_ms": 0.0, "avg_duration_ms": 0.0},
            )
            bucket["count"] += 1
            bucket["total_duration_ms"] += float(span.duration_ms or 0.0)
        for bucket in by_kind.values():
            if bucket["count"]:
                bucket["total_duration_ms"] = round(bucket["total_duration_ms"], 3)
                bucket["avg_duration_ms"] = round(
                    bucket["total_duration_ms"] / bucket["count"], 3
                )

        slowest = sorted(
            (span for span in spans if span.kind != "run"),
            key=lambda item: float(item.duration_ms or 0.0),
            reverse=True,
        )[:slowest_limit]
        return {
            "run_id": self._run_id,
            "name": self._run_name,
            "status": run_span.metadata.get("status") if run_span else None,
            "total_duration_ms": run_span.duration_ms if run_span else None,
            "span_count": len(spans),
            "event_count": len(self._events),
            "by_kind": by_kind,
            "slowest_spans": [
                {
                    "id": span.id,
                    "name": span.name,
                    "kind": span.kind,
                    "duration_ms": span.duration_ms,
                    "parent_id": span.parent_id,
                }
                for span in slowest
            ],
        }

    def export_json(self, path: str | Path) -> Path:
        output_path = Path(path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "run": {
                "run_id": self._run_id,
                "name": self._run_name,
            },
            "summary": self.get_summary(),
            "spans": [span.to_dict() for span in self._spans],
            "events": [event.to_dict() for event in self._events],
        }
        output_path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        return output_path

    def _create_span(
        self,
        *,
        name: str,
        kind: str,
        metadata: dict[str, Any] | None,
        parent_id: str | None,
    ) -> SpanRecord:
        if self._run_id is None:
            raise RuntimeError("No active run. Call start_run() first.")
        span = SpanRecord(
            id=_new_id(),
            parent_id=parent_id,
            run_id=self._run_id,
            name=name,
            kind=_normalize_kind(kind),
            start_time=time.time(),
            metadata=dict(metadata or {}),
            _perf_start=time.perf_counter(),
        )
        self._spans.append(span)
        self._span_index[span.id] = span
        return span

    def _reset(self) -> None:
        self._run_span_id = None
        self._run_id = None
        self._run_name = None
        self._spans = []
        self._events = []
        self._span_index = {}
        self._active_stack = []
