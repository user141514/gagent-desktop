#!/usr/bin/env python
from __future__ import annotations

import sys
import time
from pathlib import Path


BACKEND = Path(__file__).resolve().parents[2]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from eval_registry.registry import load_eval_cases  # noqa: E402
from eval_registry.run_eval_cases import _FakeDriver, run_eval_cases  # noqa: E402
from eval_registry.score_eval_result import score_case_result  # noqa: E402
from eval_registry.validate_eval_registry import validate  # noqa: E402
from core import ga  # noqa: E402
from core.agent_loop import exhaust  # noqa: E402
from runtime_ledger import read_run_events  # noqa: E402


class _DummyParent:
    verbose = False


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


def _call_handler(value):
    if hasattr(value, "__iter__") and not isinstance(value, (str, bytes, dict, list, tuple)):
        return exhaust(value)
    return value


def _assert_handler_writes_browser_bridge_ledger() -> None:
    original_driver = ga.driver
    original_sleep = ga.time.sleep
    try:
        ga.driver = _FakeDriver()
        ga.time.sleep = lambda _seconds: None
        handler = ga.GenericAgentHandler(_DummyParent(), cwd=str(BACKEND.parent / "temp"))
        checks = [
            ("web_scan", handler.do_web_scan, {"tabs_only": True}),
            (
                "web_execute_js",
                handler.do_web_execute_js,
                {"script": "window.location.href = 'https://example.com/after-nav';"},
            ),
        ]
        required = {"run_started", "tool_call", "tool_result", "run_finished"}
        for tool_name, method, args in checks:
            run_id = f"smoke_handler_{tool_name}_{time.time_ns()}"
            tool_args = dict(args)
            tool_args["ledger_run_id"] = run_id
            _call_handler(method(tool_args, ""))
            event_types = {event.get("event_type") for event in read_run_events(run_id)}
            if not required.issubset(event_types):
                raise AssertionError(f"{tool_name}: handler ledger events missing: {sorted(required - event_types)}")
    finally:
        ga.driver = original_driver
        ga.time.sleep = original_sleep


def main() -> int:
    cases = load_eval_cases()
    errors = validate()
    if errors:
        print("[smoke_eval_registry] failed", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1

    _assert_score_rejects_nested_baidu(cases)
    _assert_handler_writes_browser_bridge_ledger()
    summary = run_eval_cases(write_report=True)
    results = summary.get("results") or []
    if len(cases) < 3:
        raise AssertionError("expected at least 3 eval cases")
    if len(results) < 3:
        raise AssertionError("expected at least 3 executed or skipped case results")
    skipped = [result.get("case_id") for result in results if result.get("verdict") == "skip"]
    forbidden_skips = {"web_scan_current_tab_boundary", "web_execute_js_navigation_boundary"} & set(skipped)
    if forbidden_skips:
        raise AssertionError("expected boundary eval cases to execute, skipped: " + ", ".join(sorted(forbidden_skips)))
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
