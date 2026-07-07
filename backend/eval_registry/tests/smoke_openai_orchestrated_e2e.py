#!/usr/bin/env python
from __future__ import annotations

import json
import os
import queue
import sys
import threading
import time
from pathlib import Path
from typing import Any


BACKEND = Path(__file__).resolve().parents[2]
PROJECT_ROOT = BACKEND.parent
RESULTS_DIR = BACKEND / "eval_registry" / "results"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from runtime_ledger import new_run_id, read_run_events, summarize_observability, summarize_run  # noqa: E402


def main() -> int:
    if os.environ.get("GAGENT_RUN_OPENAI_E2E") != "1":
        report = {
            "status": "skipped",
            "reason": "set GAGENT_RUN_OPENAI_E2E=1 to run the real OpenAI orchestrated SDK smoke",
            "required": ["configured model variant", "openai-agents SDK", "network/API access"],
        }
        _emit_report(report)
        print(json.dumps(report, indent=2, ensure_ascii=False))
        print("[smoke_openai_orchestrated_e2e] skipped")
        return 0

    from core.openai_agentmain import OpenAIOrchestratedAgent

    agent = OpenAIOrchestratedAgent()
    if not getattr(agent, "ready", False):
        report = {
            "status": "failed",
            "failure_class": "readiness_failure",
            "reason": "OpenAIOrchestratedAgent is not ready",
            "startup_error": getattr(agent, "startup_error", ""),
        }
        _emit_report(report)
        print(json.dumps(report, indent=2, ensure_ascii=False), file=sys.stderr)
        print("[smoke_openai_orchestrated_e2e] failed", file=sys.stderr)
        return 1

    run_id = new_run_id("openai_e2e")
    timeout = float(os.environ.get("GAGENT_OPENAI_E2E_TIMEOUT", "180"))
    thread = threading.Thread(target=agent.run, daemon=True, name="openai-e2e-smoke")
    thread.start()
    output = agent.put_task(
        "Reply with exactly: OPENAI_E2E_OK. Do not call tools.",
        source="eval_openai_e2e",
        run_id=run_id,
    )
    try:
        done_item = _wait_for_done(output, timeout)
    except Exception as exc:
        events = read_run_events(run_id)
        report = {
            "status": "failed",
            "failure_class": "runtime_failure",
            "run_id": run_id,
            "reason": str(exc),
            "ledger_event_count": len(events),
            "ledger_summary": summarize_run(run_id),
        }
        _emit_report(report)
        print(json.dumps(report, indent=2, ensure_ascii=False, default=str), file=sys.stderr)
        print("[smoke_openai_orchestrated_e2e] failed", file=sys.stderr)
        return 1
    events = read_run_events(run_id)
    ledger_summary = summarize_run(run_id)
    observability = summarize_observability(
        run_id,
        runtime_host_logs_root=PROJECT_ROOT / "backend" / "logs" / "sessions",
    )
    result = {
        "status": "passed",
        "run_id": run_id,
        "done": done_item.get("done", ""),
        "ledger_summary": ledger_summary,
        "observability": observability,
    }
    event_types = {str(event.get("event_type") or "") for event in events}
    required_events = {"run_started", "run_finished"}
    if not required_events.issubset(event_types):
        result["status"] = "failed"
        result["reason"] = "runtime_ledger missing required OpenAI run events"
        result["missing_events"] = sorted(required_events - event_types)
    elif "OPENAI_E2E_OK" not in str(done_item.get("done") or ""):
        result["status"] = "failed"
        result["reason"] = "model did not return expected sentinel"
    elif observability.get("aligned", {}).get("has_ledger_events") is not True:
        result["status"] = "failed"
        result["failure_class"] = "observability_failure"
        result["reason"] = "observability summary missing runtime_ledger events"

    _emit_report(result)
    print(json.dumps(result, indent=2, ensure_ascii=False, default=str))
    if result["status"] == "passed":
        print("[smoke_openai_orchestrated_e2e] ok")
        return 0
    print("[smoke_openai_orchestrated_e2e] failed", file=sys.stderr)
    return 1


def _emit_report(report: dict[str, Any]) -> None:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    (RESULTS_DIR / "latest_openai_e2e_report.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )


def _wait_for_done(output: "queue.Queue[dict[str, Any]]", timeout: float) -> dict[str, Any]:
    deadline = time.time() + timeout
    last_item: dict[str, Any] = {}
    while time.time() < deadline:
        try:
            item = output.get(timeout=min(1.0, max(0.1, deadline - time.time())))
        except queue.Empty:
            continue
        if isinstance(item, dict):
            last_item = item
            if "done" in item:
                return item
    raise TimeoutError(f"OpenAI orchestrated e2e smoke timed out after {timeout:g}s; last_item={last_item}")


if __name__ == "__main__":
    raise SystemExit(main())
