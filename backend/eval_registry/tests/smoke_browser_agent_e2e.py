#!/usr/bin/env python
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Any


BACKEND = Path(__file__).resolve().parents[2]
RESULTS_DIR = BACKEND / "eval_registry" / "results"
PROJECT_ROOT = BACKEND.parent
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))
_e2e_deps = os.environ.get("GAGENT_E2E_DEPS")
if _e2e_deps and Path(_e2e_deps).exists():
    sys.path.insert(0, str(Path(_e2e_deps).resolve()))

from core import ga  # noqa: E402
from core.agent_loop import StepOutcome, exhaust  # noqa: E402
from runtime_ledger import new_run_id, read_run_events, summarize_run  # noqa: E402


class _DummyParent:
    verbose = False


def main() -> int:
    if os.environ.get("GAGENT_RUN_BROWSER_AGENT_E2E") != "1":
        report = {
            "status": "skipped",
            "reason": "set GAGENT_RUN_BROWSER_AGENT_E2E=1 to run the real browser_agent smoke",
            "required": ["browser-use", "Playwright Chromium", "LLM API key/network access"],
        }
        _emit_report(report)
        print(json.dumps(report, indent=2, ensure_ascii=False))
        print("[smoke_browser_agent_e2e] skipped")
        return 0

    run_id = new_run_id("browser_agent_e2e")
    task = os.environ.get("GAGENT_BROWSER_AGENT_E2E_TASK") or "Open https://example.com and report the page title."
    args = {
        "task": task,
        "max_steps": int(os.environ.get("GAGENT_BROWSER_AGENT_E2E_MAX_STEPS", "3")),
        "headless": os.environ.get("GAGENT_BROWSER_AGENT_E2E_HEADLESS", "1") != "0",
        "ledger_run_id": run_id,
    }
    try:
        handler = ga.GenericAgentHandler(_DummyParent(), cwd=str(PROJECT_ROOT / "backend" / "temp"))
        tool_result = _coerce_handler_result(_call_handler(handler.do_browser_agent(args, "")))
    except Exception as exc:
        report = {
            "status": "failed",
            "failure_class": _classify_failure(str(exc)),
            "run_id": run_id,
            "reason": str(exc),
            "ledger_summary": summarize_run(run_id),
        }
        _emit_report(report)
        print(json.dumps(report, indent=2, ensure_ascii=False, default=str), file=sys.stderr)
        print("[smoke_browser_agent_e2e] failed", file=sys.stderr)
        return 1

    events = read_run_events(run_id)
    ledger_summary = summarize_run(run_id)
    success = tool_result.get("success") is True or str(tool_result.get("status") or "").lower() == "success"
    report = {
        "status": "passed" if success else "failed",
        "run_id": run_id,
        "tool_result": tool_result,
        "ledger_summary": ledger_summary,
        "ledger_event_count": len(events),
    }
    if not success:
        report["failure_class"] = _classify_failure(json.dumps(tool_result, ensure_ascii=False, default=str))
        report["reason"] = tool_result.get("result") or tool_result.get("msg") or tool_result.get("error") or "browser_agent failed"
    elif not {"run_started", "tool_call", "tool_result", "run_finished"}.issubset(
        {str(event.get("event_type") or "") for event in events}
    ):
        report["status"] = "failed"
        report["failure_class"] = "ledger_failure"
        report["reason"] = "browser_agent runtime_ledger events missing"

    _emit_report(report)
    print(json.dumps(report, indent=2, ensure_ascii=False, default=str))
    if report["status"] == "passed":
        print("[smoke_browser_agent_e2e] ok")
        return 0
    print("[smoke_browser_agent_e2e] failed", file=sys.stderr)
    return 1


def _call_handler(value: Any) -> Any:
    if hasattr(value, "__iter__") and not isinstance(value, (str, bytes, dict, list, tuple)):
        return exhaust(value)
    return value


def _coerce_handler_result(outcome: Any) -> dict[str, Any]:
    value = outcome.data if isinstance(outcome, StepOutcome) else outcome
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            pass
    return {"success": False, "result": str(value)}


def _classify_failure(text: str) -> str:
    lowered = text.lower()
    if any(marker in lowered for marker in ("browser-use", "playwright", "chromium", "api key", "no module named")):
        return "readiness_failure"
    return "runtime_failure"


def _emit_report(report: dict[str, Any]) -> None:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    (RESULTS_DIR / "latest_browser_agent_e2e_report.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )


if __name__ == "__main__":
    raise SystemExit(main())
