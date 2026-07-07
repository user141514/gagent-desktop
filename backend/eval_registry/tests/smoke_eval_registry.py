#!/usr/bin/env python
from __future__ import annotations

import sys
from pathlib import Path


BACKEND = Path(__file__).resolve().parents[2]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from eval_registry.registry import load_eval_cases  # noqa: E402
from eval_registry.run_eval_cases import run_eval_cases  # noqa: E402
from eval_registry.score_eval_result import score_case_result  # noqa: E402
from eval_registry.validate_eval_registry import validate  # noqa: E402


def _assert_score_rejects_nested_baidu(cases) -> None:
    case = next(item for item in cases if item.id == "web_search_openai_docs")
    run_id = "smoke_nested_baidu"
    ledger_events = [
        {"run_id": run_id, "event_type": "run_started"},
        {"run_id": run_id, "event_type": "tool_call", "tool": "web_search", "args": {"query": "OpenAI API docs"}},
        {
            "run_id": run_id,
            "event_type": "tool_result",
            "tool": "web_search",
            "result": {"status": "success", "data": {"results": [{"url": "https://www.baidu.com/"}]}},
        },
        {"run_id": run_id, "event_type": "run_finished", "final_status": "success"},
    ]
    score = score_case_result(
        case,
        {"status": "success", "data": {"results": [{"url": "https://www.baidu.com/"}]}},
        ledger_events,
        {"run_id": run_id, "final_status": "success"},
    )
    if score.get("verdict") != "fail" or not any("baidu.com" in item for item in score.get("penalties", [])):
        raise AssertionError("nested baidu success was not rejected")


def main() -> int:
    cases = load_eval_cases()
    errors = validate()
    if errors:
        print("[smoke_eval_registry] failed", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1

    _assert_score_rejects_nested_baidu(cases)
    summary = run_eval_cases(write_report=True)
    results = summary.get("results") or []
    if len(cases) < 3:
        raise AssertionError("expected at least 3 eval cases")
    if len(results) < 3:
        raise AssertionError("expected at least 3 executed or skipped case results")
    for result in results:
        if result.get("verdict") == "skip":
            continue
        for key in ("total", "verdict", "reasons", "penalties"):
            if key not in result:
                raise AssertionError(f"{result.get('case_id')}: missing {key}")
        if result.get("target_tool") == "web_search" and int(result.get("ledger_event_count") or 0) <= 0:
            raise AssertionError(f"{result.get('case_id')}: missing ledger events")
        if result.get("case_id") == "web_search_yobot_github_failure" and result.get("tool_status") != "success":
            if "github" not in (result.get("attempt_engines") or []):
                raise AssertionError("web_search_yobot_github_failure: missing github attempt in failure chain")
        if result.get("forbidden_tools_used"):
            raise AssertionError(f"{result.get('case_id')}: forbidden tool used: {result.get('forbidden_tools_used')}")
    if summary.get("case_count", 0) < 3:
        raise AssertionError("summary case_count is less than 3")
    print("[smoke_eval_registry] ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
