#!/usr/bin/env python
from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any


BACKEND = Path(__file__).resolve().parents[1]
ROOT = Path(__file__).resolve().parents[2]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from core import ga  # noqa: E402
from core.agent_loop import StepOutcome, exhaust  # noqa: E402
from eval_registry.registry import EvalCase, load_eval_cases  # noqa: E402
from eval_registry.score_eval_result import score_case_result  # noqa: E402
from runtime_ledger import read_run_events, summarize_run  # noqa: E402


RESULTS_DIR = ROOT / "backend" / "eval_registry" / "results"


class _DummyParent:
    verbose = False


def run_eval_cases(write_report: bool = True) -> dict[str, Any]:
    cases = load_eval_cases()
    results = []
    for case in cases:
        if case.target_tool != "web_search":
            results.append({
                "case_id": case.id,
                "verdict": "skip",
                "reason": f"target_tool {case.target_tool} is not supported in eval_registry step1",
            })
            continue
        results.append(_run_web_search_case(case))

    failed = [item for item in results if item.get("verdict") == "fail"]
    summary = {
        "status": "ok" if not failed else "failed",
        "case_count": len(cases),
        "passed": len([item for item in results if item.get("verdict") == "pass"]),
        "failed": len(failed),
        "skipped": len([item for item in results if item.get("verdict") == "skip"]),
        "results": results,
    }
    if write_report:
        RESULTS_DIR.mkdir(parents=True, exist_ok=True)
        (RESULTS_DIR / "latest_eval_report.json").write_text(
            json.dumps(summary, indent=2, ensure_ascii=False, default=str),
            encoding="utf-8",
        )
    return summary


def _run_web_search_case(case: EvalCase) -> dict[str, Any]:
    run_id = f"eval_{case.id}_{time.time_ns()}"
    args = dict(case.input)
    args["ledger_run_id"] = run_id
    handler = ga.GenericAgentHandler(_DummyParent(), cwd=str(ROOT / "backend" / "temp"))
    outcome = _call_handler(handler.do_web_search(args, ""))
    tool_result = outcome.data if isinstance(outcome, StepOutcome) else outcome
    if not isinstance(tool_result, dict):
        tool_result = {"status": "error", "msg": str(tool_result)}
    ledger_events = read_run_events(run_id)
    ledger_summary = summarize_run(run_id)
    score = score_case_result(case, tool_result, ledger_events, ledger_summary)
    forbidden = set(str(x) for x in case.expected_tools.get("forbidden") or [])
    forbidden_used = sorted({str(event.get("tool") or "") for event in ledger_events} & forbidden)
    score.update({
        "run_id": run_id,
        "target_tool": case.target_tool,
        "tool_status": str(tool_result.get("status") or ""),
        "ledger_event_count": len(ledger_events),
        "final_status": ledger_summary.get("final_status"),
        "forbidden_tools_used": forbidden_used,
    })
    return score


def _call_handler(value: Any) -> Any:
    if hasattr(value, "__iter__") and not isinstance(value, (str, bytes, dict, list, tuple)):
        return exhaust(value)
    return value


def main() -> int:
    summary = run_eval_cases(write_report=True)
    print(json.dumps(summary, indent=2, ensure_ascii=False, default=str))
    return 0 if summary.get("status") == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
