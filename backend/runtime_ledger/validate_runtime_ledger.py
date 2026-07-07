#!/usr/bin/env python
"""Validate the Runtime Ledger module with deterministic local checks."""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime_ledger import LedgerEvent, new_run_id, read_run_events, summarize_run, write_event  # noqa: E402


def validate() -> list[str]:
    errors: list[str] = []
    with tempfile.TemporaryDirectory(prefix="runtime_ledger_validate_") as tmp:
        ledger_dir = Path(tmp)
        run_id = new_run_id("validate")
        path = write_event(
            LedgerEvent(
                run_id=run_id,
                event_type="run_started",
                task="validate runtime ledger",
                owner_layer="Layer 3 runtime controller",
                metadata={"validator": True},
            ),
            ledger_dir=ledger_dir,
        )
        write_event(
            LedgerEvent(
                run_id=run_id,
                event_type="tool_result",
                tool="web_search",
                result={"status": "error", "msg": "synthetic timeout"},
                decision={"action": "switch_same_capability", "next_tool": "web_search"},
                smoke_tests=["backend/tool_registry/tests/smoke_web_tools.py"],
            ),
            ledger_dir=ledger_dir,
        )
        write_event(
            {"run_id": run_id, "event_type": "run_finished", "final_status": "blocked_network"},
            ledger_dir=ledger_dir,
        )

        if not path.exists():
            errors.append("ledger JSONL file was not created")
        raw_lines = path.read_text(encoding="utf-8").splitlines()
        if len(raw_lines) != 3:
            errors.append(f"expected 3 JSONL lines, got {len(raw_lines)}")
        for line in raw_lines:
            try:
                json.loads(line)
            except json.JSONDecodeError as exc:
                errors.append(f"invalid JSONL line: {exc}")

        events = read_run_events(run_id, ledger_dir=ledger_dir)
        if len(events) != 3:
            errors.append(f"read_run_events expected 3 events, got {len(events)}")
        summary = summarize_run(run_id, ledger_dir=ledger_dir)
        if summary.get("failure_count") != 1:
            errors.append(f"expected one failure, got {summary.get('failure_count')}")
        if summary.get("tools", {}).get("web_search") != 1:
            errors.append("web_search tool count missing from summary")
        if summary.get("final_status") != "blocked_network":
            errors.append("final_status was not preserved")

        try:
            write_event({"run_id": run_id, "event_type": "unknown_event"}, ledger_dir=ledger_dir)
            errors.append("unknown event_type was accepted")
        except ValueError:
            pass

    return errors


def main() -> int:
    errors = validate()
    if errors:
        print("[validate_runtime_ledger] failed", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1
    print("[validate_runtime_ledger] ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
