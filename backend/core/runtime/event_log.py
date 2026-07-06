from __future__ import annotations

import json
import os
from typing import Any

from .event_schema import RuntimeEvent


class RuntimeEventLog:
    """Append-only event log with JSONL persistence per session."""

    def __init__(self, session_id: str, logs_root: str, agent_name: str = "runtime_host") -> None:
        self.session_id = session_id
        self.agent_name = agent_name
        self.logs_root = logs_root
        self.session_dir = os.path.join(logs_root, session_id)
        self.diffs_dir = os.path.join(self.session_dir, "diffs")
        self.diagnostics_dir = os.path.join(self.session_dir, "diagnostics")
        self.reviews_dir = os.path.join(self.session_dir, "reviews")
        self.events_path = os.path.join(self.session_dir, "events.jsonl")
        self.snapshot_path = os.path.join(self.session_dir, "snapshot.json")
        self._events: list[RuntimeEvent] = []
        self._persisted_event_count = 0

        os.makedirs(self.diffs_dir, exist_ok=True)
        os.makedirs(self.diagnostics_dir, exist_ok=True)
        os.makedirs(self.reviews_dir, exist_ok=True)
        if os.path.exists(self.events_path):
            with open(self.events_path, "r", encoding="utf-8") as handle:
                self._persisted_event_count = sum(1 for _ in handle)

    def append(self, event: RuntimeEvent) -> RuntimeEvent:
        self._events.append(event)
        with open(self.events_path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(event.to_dict(), ensure_ascii=False) + "\n")
        return event

    def write_snapshot(self, snapshot: dict[str, Any]) -> None:
        with open(self.snapshot_path, "w", encoding="utf-8") as handle:
            json.dump(snapshot, handle, ensure_ascii=False, indent=2)

    def recent(self, limit: int = 20) -> list[RuntimeEvent]:
        return self._events[-limit:]

    def event_count(self) -> int:
        return self._persisted_event_count + len(self._events)
