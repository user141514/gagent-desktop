#!/usr/bin/env python
"""Smoke test for Runtime Ledger trajectory recording.

This test is intentionally local and deterministic. It does not require network,
browser sessions, LLM calls, or CTest.
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime_ledger import LedgerEvent, new_run_id, read_run_events, summarize_run, write_event  # noqa: E402
from runtime_ledger.ledger import event_path  # noqa: E402


def _assert_openai_helper_writes_runtime_ledger() -> dict[str, object]:
    from core.openai_agentmain import OpenAIOrchestratedAgent

    run_id = new_run_id("smoke_openai")
    path = event_path(run_id)
    path.unlink(missing_ok=True)
    agent = object.__new__(OpenAIOrchestratedAgent)
    agent._profile_run_id = run_id
    agent._runtime_session_id = None
    try:
        agent._write_runtime_ledger_event("run_started", task="openai helper smoke")
        agent._write_runtime_ledger_event(
            "tool_call",
            task="openai helper smoke",
            turn=1,
            tool="run_genericagent_executor",
            args={"event_name": "tool_called"},
        )
        agent._write_runtime_ledger_event(
            "tool_result",
            task="openai helper smoke",
            turn=1,
            tool="run_genericagent_executor",
            result={"status": "success", "summary": "ok"},
        )
        agent._write_runtime_ledger_event(
            "run_finished",
            task="openai helper smoke",
            final_status="success",
            result={"status": "success"},
        )
        events = read_run_events(run_id)
        summary = summarize_run(run_id)
        event_types = [event.get("event_type") for event in events]
        assert event_types == ["run_started", "tool_call", "tool_result", "run_finished"], event_types
        assert [event.get("turn") for event in events if event.get("tool")] == [1, 1], events
        assert summary["tools"].get("run_genericagent_executor") == 2, summary
        assert summary["final_status"] == "success", summary
        return {"run_id": run_id, "summary": summary}
    finally:
        path.unlink(missing_ok=True)


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="runtime_ledger_smoke_") as tmp:
        ledger_dir = Path(tmp)
        run_id = new_run_id("smoke")
        events = [
            LedgerEvent(
                run_id=run_id,
                event_type="run_started",
                task="web search failure recovery",
                owner_layer="Layer 3 runtime controller",
            ),
            LedgerEvent(
                run_id=run_id,
                event_type="tool_call",
                turn=1,
                tool="web_search",
                args={"query": "yobot GitHub code", "engine": "github"},
            ),
            LedgerEvent(
                run_id=run_id,
                event_type="tool_result",
                turn=1,
                tool="web_search",
                result={"status": "error", "msg": "github timeout"},
            ),
            LedgerEvent(
                run_id=run_id,
                event_type="decision",
                decision={
                    "action": "switch_same_capability",
                    "next_tool": "web_search",
                    "next_args": {"engine": "auto"},
                    "forbidden_actions": ["web_scan", "browser_agent"],
                },
                experience_ids_used=["web_search_github_timeout"],
            ),
            LedgerEvent(
                run_id=run_id,
                event_type="smoke_test",
                smoke_tests=["backend/tool_registry/tests/smoke_web_tools.py"],
                result={"status": "passed"},
            ),
            LedgerEvent(
                run_id=run_id,
                event_type="run_finished",
                final_status="structured_failure_allowed",
            ),
        ]
        for event in events:
            write_event(event, ledger_dir=ledger_dir)

        loaded = read_run_events(run_id, ledger_dir=ledger_dir)
        summary = summarize_run(run_id, ledger_dir=ledger_dir)
        assert len(loaded) == len(events), (len(loaded), len(events))
        assert summary["failure_count"] == 1, summary
        assert summary["tools"].get("web_search") == 2, summary
        assert summary["final_status"] == "structured_failure_allowed", summary
        assert summary["smoke_tests"] == ["backend/tool_registry/tests/smoke_web_tools.py"], summary
        agentmain = (ROOT / "core" / "agentmain.py").read_text(encoding="utf-8")
        assert "runtime_ledger_run_id=run_id" in agentmain, "classic agentmain must pass run_id into agent_runner_loop runtime_ledger"
        openai_agentmain = (ROOT / "core" / "openai_agentmain.py").read_text(encoding="utf-8")
        for marker in (
            '_write_runtime_ledger_event("run_started"',
            '_write_runtime_ledger_event("tool_call"',
            '_write_runtime_ledger_event("tool_result"',
            '_write_runtime_ledger_event("run_finished"',
        ):
            assert marker in openai_agentmain, f"openai_agentmain runtime_ledger marker missing: {marker}"
        openai_helper = _assert_openai_helper_writes_runtime_ledger()
        print(json.dumps({
            "status": "passed",
            "run_id": run_id,
            "summary": summary,
            "openai_helper": openai_helper,
        }, indent=2, ensure_ascii=False))
    print("[smoke_runtime_ledger] ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
