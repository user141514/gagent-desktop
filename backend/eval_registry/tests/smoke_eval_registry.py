#!/usr/bin/env python
from __future__ import annotations

import json
import sys
import tempfile
import time
from dataclasses import replace
from pathlib import Path


BACKEND = Path(__file__).resolve().parents[2]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from eval_registry.registry import load_eval_case, load_eval_cases  # noqa: E402
from eval_registry.run_eval_cases import _AgentLoopEvalHandler, _FakeAgentLoopClient, _FakeDriver, run_eval_cases  # noqa: E402
from eval_registry.score_final_answer import score_final_answer  # noqa: E402
from eval_registry.score_eval_result import score_case_result  # noqa: E402
from eval_registry.validate_eval_registry import _validate_loaded_case, validate  # noqa: E402
from core import ga  # noqa: E402
from core.agent_loop import agent_runner_loop, exhaust  # noqa: E402
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


def _assert_answer_score_rejects_false_success(cases) -> None:
    case = next(item for item in cases if item.id == "web_search_yobot_github_failure")
    score = score_final_answer(
        case,
        "I found the repository and here are the results.",
        {"status": "error", "msg": "All configured HTTP search engines failed.", "error_category": "search_backend_unavailable"},
    )
    if score.get("verdict") != "fail":
        raise AssertionError("final-answer score accepted a false success claim")


def _assert_answer_score_rejects_forbidden_fallback(cases) -> None:
    case = next(item for item in cases if item.id == "web_search_yobot_github_failure")
    score = score_final_answer(
        case,
        "web_search failed. Try web_scan or browser_agent next.",
        {"status": "error", "msg": "All configured HTTP search engines failed.", "error_category": "search_backend_unavailable"},
    )
    if score.get("verdict") != "fail":
        raise AssertionError("final-answer score accepted a forbidden fallback recommendation")


def _assert_score_rejects_disallowed_failure(cases) -> None:
    base_case = next(item for item in cases if item.id == "web_search_openai_docs")
    case = replace(base_case, expected_result={**base_case.expected_result, "allow_structured_failure": False})
    run_id = "smoke_disallowed_failure"
    ledger_events = [
        {"run_id": run_id, "event_type": "run_started"},
        {"run_id": run_id, "event_type": "tool_call", "tool": "web_search", "args": {"query": "OpenAI API docs"}},
        {
            "run_id": run_id,
            "event_type": "tool_result",
            "tool": "web_search",
            "result": {"status": "error", "msg": "blocked", "error_category": "network_error"},
        },
        {
            "run_id": run_id,
            "event_type": "decision",
            "decision": {
                "action": "report_blocker",
                "forbidden_actions": ["web_scan", "web_execute_js", "browser_agent"],
            },
        },
        {"run_id": run_id, "event_type": "run_finished", "final_status": "structured_failure"},
    ]
    score = score_case_result(
        case,
        {"status": "error", "msg": "blocked", "error_category": "network_error"},
        ledger_events,
        {"run_id": run_id, "final_status": "structured_failure"},
    )
    if score.get("verdict") != "fail":
        raise AssertionError("score accepted a structured failure when allow_structured_failure=false")


def _assert_score_rejects_required_final_status_mismatch(cases) -> None:
    case = next(item for item in cases if item.id == "agent_loop_runtime_mapper_web_search_failure")
    run_id = "smoke_final_status_mismatch"
    ledger_events = [
        {"run_id": run_id, "event_type": "run_started"},
        {"run_id": run_id, "event_type": "tool_call", "tool": "web_search", "args": {"query": "OpenAI API docs"}},
        {
            "run_id": run_id,
            "event_type": "tool_result",
            "tool": "web_search",
            "result": {"status": "error", "msg": "blocked", "error_category": "network_error"},
        },
        {
            "run_id": run_id,
            "event_type": "decision",
            "decision": {
                "action": "report_blocker",
                "forbidden_actions": ["web_scan", "web_execute_js", "browser_agent"],
            },
        },
        {"run_id": run_id, "event_type": "run_finished", "final_status": "success"},
    ]
    score = score_case_result(
        case,
        {"status": "error", "msg": "blocked", "error_category": "network_error"},
        ledger_events,
        {"run_id": run_id, "final_status": "success"},
    )
    if score.get("verdict") != "fail":
        raise AssertionError("score accepted a mismatched required final_status")


def _assert_validator_rejects_impossible_expected_result(cases) -> None:
    base_case = next(item for item in cases if item.id == "web_search_openai_docs")
    bad_case = replace(
        base_case,
        expected_result={**base_case.expected_result, "allow_success": False, "allow_structured_failure": False},
    )
    errors = _validate_loaded_case(bad_case)
    if not any("expected_result must allow success or structured failure" in error for error in errors):
        raise AssertionError("validator accepted impossible expected_result outcomes")


def _assert_validator_rejects_unknown_expected_result_fields(cases) -> None:
    base_case = next(item for item in cases if item.id == "web_search_openai_docs")
    bad_case = replace(base_case, expected_result={**base_case.expected_result, "allow_succes": True})
    errors = _validate_loaded_case(bad_case)
    if not any("expected_result contains unknown field" in error for error in errors):
        raise AssertionError("validator accepted unknown expected_result field")


def _assert_validator_rejects_unknown_contract_fields(cases) -> None:
    base_case = next(item for item in cases if item.id == "web_search_openai_docs")
    checks = [
        ("expected_tools", replace(base_case, expected_tools={**base_case.expected_tools, "allowd": ["web_search"]})),
        ("expected_ledger", replace(base_case, expected_ledger={**base_case.expected_ledger, "required_event": []})),
        ("score", replace(base_case, score={**base_case.score, "ledgr": 0})),
    ]
    for field_name, bad_case in checks:
        errors = _validate_loaded_case(bad_case)
        if not any(f"{field_name} contains unknown field" in error for error in errors):
            raise AssertionError(f"validator accepted unknown {field_name} field")


def _assert_validator_rejects_invalid_score_weights(cases) -> None:
    base_case = next(item for item in cases if item.id == "web_search_openai_docs")
    checks = [
        {"answer_or_tool_behavior": -10, "ledger": 110},
        {"answer_or_tool_behavior": 0, "ledger": 100},
    ]
    for score in checks:
        bad_case = replace(base_case, score=score)
        errors = _validate_loaded_case(bad_case)
        if not any("score weights must be answer_or_tool_behavior=60 and ledger=40" in error for error in errors):
            raise AssertionError(f"validator accepted invalid score weights: {score}")


def _assert_loader_rejects_unknown_top_level_fields(cases) -> None:
    base_case = next(item for item in cases if item.id == "web_search_openai_docs")
    payload = json.loads(Path(base_case.source_path).read_text(encoding="utf-8"))
    payload["target_tooool"] = "web_search"
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir) / Path(base_case.source_path).name
        temp_path.write_text(json.dumps(payload), encoding="utf-8")
        try:
            load_eval_case(temp_path)
        except ValueError as exc:
            if "unknown fields" in str(exc):
                return
            raise AssertionError(f"loader rejected top-level field for the wrong reason: {exc}") from exc
    raise AssertionError("loader accepted unknown top-level eval case field")


def _assert_validator_rejects_unknown_input_fields(cases) -> None:
    checks = [
        (
            next(item for item in cases if item.id == "web_search_openai_docs"),
            "queri",
            "OpenAI API docs",
        ),
        (
            next(item for item in cases if item.id == "browser_agent_contract_boundary"),
            "task",
            "wrong contract input",
        ),
    ]
    for base_case, field_name, field_value in checks:
        bad_case = replace(base_case, input={**base_case.input, field_name: field_value})
        errors = _validate_loaded_case(bad_case)
        if not any("input contains unknown field" in error for error in errors):
            raise AssertionError(f"validator accepted unknown input field {base_case.id}.{field_name}")


def _assert_validator_rejects_unsupported_type_and_version(cases) -> None:
    base_case = next(item for item in cases if item.id == "web_search_openai_docs")
    checks = [
        (replace(base_case, type="tool_boundry_eval"), "type is unsupported"),
        (replace(base_case, version=2), "version is unsupported"),
    ]
    for bad_case, expected_error in checks:
        errors = _validate_loaded_case(bad_case)
        if not any(expected_error in error for error in errors):
            raise AssertionError(f"validator accepted unsupported eval case contract: {expected_error}")


def _assert_validator_rejects_tool_specific_expected_result_drift(cases) -> None:
    base_case = next(item for item in cases if item.id == "web_search_openai_docs")
    checks = [
        ("require_navigation_success", "requires target_tool web_execute_js"),
        ("require_contract_valid", "requires browser_agent tool_contract_eval"),
        ("require_browser_agent_success", "requires browser_agent tool_handler_eval"),
        ("forbid_search_shaped_success", "requires target_tool web_scan"),
    ]
    for field_name, expected_error in checks:
        bad_case = replace(
            base_case,
            expected_result={**base_case.expected_result, field_name: True},
        )
        errors = _validate_loaded_case(bad_case)
        if not any(expected_error in error for error in errors):
            raise AssertionError(f"validator accepted misplaced expected_result.{field_name}")


def _assert_validator_rejects_unknown_runtime_events(cases) -> None:
    base_case = next(item for item in cases if item.id == "agent_loop_runtime_mapper_web_search")
    bad_case = replace(
        base_case,
        expected_result={
            **base_case.expected_result,
            "require_runtime_events": [
                *base_case.expected_result.get("require_runtime_events", []),
                "mind_read_started",
            ],
        },
    )
    errors = _validate_loaded_case(bad_case)
    if not any("expected_result.require_runtime_events contains unsupported runtime event" in error for error in errors):
        raise AssertionError("validator accepted unknown required RuntimeHost event")


def _assert_validator_rejects_unobservable_balanced_turns(cases) -> None:
    base_case = next(item for item in cases if item.id == "agent_loop_runtime_mapper_web_search")
    bad_case = replace(
        base_case,
        expected_result={
            **base_case.expected_result,
            "require_runtime_events": ["tool_requested", "tool_completed"],
            "require_balanced_turn_events": True,
        },
    )
    errors = _validate_loaded_case(bad_case)
    if not any("require_balanced_turn_events requires llm_call_started and llm_call_completed" in error for error in errors):
        raise AssertionError("validator accepted balanced-turn check without LLM turn events")


def _assert_validator_requires_allowed_target_tool(cases) -> None:
    base_case = next(item for item in cases if item.id == "web_search_tool_boundary")
    bad_case = replace(base_case, expected_tools={**base_case.expected_tools, "allowed": ["web_scan"]})
    errors = _validate_loaded_case(bad_case)
    if not any("allowed must include target_tool" in error for error in errors):
        raise AssertionError("validator accepted allowed tools without target_tool")


def _assert_validator_rejects_allowed_forbidden_overlap(cases) -> None:
    base_case = next(item for item in cases if item.id == "web_search_tool_boundary")
    bad_case = replace(
        base_case,
        expected_tools={
            **base_case.expected_tools,
            "forbidden": [*base_case.expected_tools.get("forbidden", []), base_case.target_tool],
        },
    )
    errors = _validate_loaded_case(bad_case)
    if not any("allowed and forbidden must not overlap" in error for error in errors):
        raise AssertionError("validator accepted overlapping allowed/forbidden tools")


def _assert_validator_rejects_unknown_expected_tools(cases) -> None:
    base_case = next(item for item in cases if item.id == "web_search_tool_boundary")
    for field_name in ("allowed", "forbidden"):
        bad_case = replace(
            base_case,
            expected_tools={
                **base_case.expected_tools,
                field_name: [*base_case.expected_tools.get(field_name, []), "web_teleport"],
            },
        )
        errors = _validate_loaded_case(bad_case)
        if not any(f"expected_tools.{field_name} contains unknown tool" in error for error in errors):
            raise AssertionError(f"validator accepted unknown expected_tools.{field_name} tool")


def _assert_validator_rejects_decision_forbidden_drift(cases) -> None:
    base_case = next(item for item in cases if item.id == "web_search_yobot_github_failure")
    bad_case = replace(
        base_case,
        expected_tools={**base_case.expected_tools, "forbidden": ["web_scan"]},
        expected_ledger={
            **base_case.expected_ledger,
            "required_decision_forbidden_actions": ["web_scan", "browser_agent"],
        },
    )
    errors = _validate_loaded_case(bad_case)
    if not any("required_decision_forbidden_actions must be a subset" in error for error in errors):
        raise AssertionError("validator accepted decision forbidden-actions outside expected_tools.forbidden")


def _assert_validator_rejects_unknown_ledger_events(cases) -> None:
    base_case = next(item for item in cases if item.id == "web_search_yobot_github_failure")
    checks = {
        "required_events": [*base_case.expected_ledger.get("required_events", []), "telepathy_started"],
        "required_on_failure": [*base_case.expected_ledger.get("required_on_failure", []), "telepathy_failed"],
    }
    for field_name, field_value in checks.items():
        bad_case = replace(
            base_case,
            expected_ledger={**base_case.expected_ledger, field_name: field_value},
        )
        errors = _validate_loaded_case(bad_case)
        if not any(f"expected_ledger.{field_name} contains unsupported event" in error for error in errors):
            raise AssertionError(f"validator accepted unknown expected_ledger.{field_name} event")


def _assert_agent_loop_writes_runtime_ledger(cases) -> None:
    from core.protocol.formatter import NullFormatter

    case = next(item for item in cases if item.id == "agent_loop_runtime_mapper_web_search")
    run_id = f"smoke_agent_loop_runtime_ledger_{time.time_ns()}"
    exhaust(agent_runner_loop(
        _FakeAgentLoopClient(dict(case.input)),
        "You are an eval fake agent.",
        case.task,
        _AgentLoopEvalHandler(),
        tools_schema=[],
        max_turns=3,
        verbose=False,
        formatter=NullFormatter(),
        turn_gap=0.0,
        runtime_ledger_run_id=run_id,
    ))
    events = read_run_events(run_id)
    event_types = [event.get("event_type") for event in events]
    required = {"run_started", "tool_call", "tool_result", "run_finished"}
    if not required.issubset(event_types):
        raise AssertionError(f"agent_loop runtime_ledger events missing: {sorted(required - set(event_types))}")
    tool_events = [event for event in events if event.get("event_type") in {"tool_call", "tool_result"}]
    if not tool_events or any(event.get("turn") is None for event in tool_events):
        raise AssertionError("agent_loop runtime_ledger tool events must include turn")


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
    _assert_answer_score_rejects_false_success(cases)
    _assert_answer_score_rejects_forbidden_fallback(cases)
    _assert_score_rejects_disallowed_failure(cases)
    _assert_score_rejects_required_final_status_mismatch(cases)
    _assert_validator_rejects_impossible_expected_result(cases)
    _assert_validator_rejects_unknown_expected_result_fields(cases)
    _assert_validator_rejects_unknown_contract_fields(cases)
    _assert_validator_rejects_invalid_score_weights(cases)
    _assert_loader_rejects_unknown_top_level_fields(cases)
    _assert_validator_rejects_unknown_input_fields(cases)
    _assert_validator_rejects_unsupported_type_and_version(cases)
    _assert_validator_rejects_tool_specific_expected_result_drift(cases)
    _assert_validator_rejects_unknown_runtime_events(cases)
    _assert_validator_rejects_unobservable_balanced_turns(cases)
    _assert_validator_requires_allowed_target_tool(cases)
    _assert_validator_rejects_allowed_forbidden_overlap(cases)
    _assert_validator_rejects_unknown_expected_tools(cases)
    _assert_validator_rejects_decision_forbidden_drift(cases)
    _assert_validator_rejects_unknown_ledger_events(cases)
    _assert_agent_loop_writes_runtime_ledger(cases)
    summary = run_eval_cases(write_report=True)
    results = summary.get("results") or []
    if summary.get("status") != "ok" or int(summary.get("failed") or 0) != 0:
        raise AssertionError(f"eval summary failed: {summary.get('failed')} failed")
    if len(cases) < 3:
        raise AssertionError("expected at least 3 eval cases")
    if len(results) < 3:
        raise AssertionError("expected at least 3 executed or skipped case results")
    skipped = [result.get("case_id") for result in results if result.get("verdict") == "skip"]
    forbidden_skips = {
        "browser_agent_contract_boundary",
        "browser_agent_handler_stub_boundary",
        "web_scan_current_tab_boundary",
        "web_execute_js_navigation_boundary",
    } & set(skipped)
    if forbidden_skips:
        raise AssertionError("expected boundary eval cases to execute, skipped: " + ", ".join(sorted(forbidden_skips)))
    for result in results:
        if result.get("verdict") == "skip":
            continue
        for key in ("total", "verdict", "reasons", "penalties"):
            if key not in result:
                raise AssertionError(f"{result.get('case_id')}: missing {key}")
        final_answer = result.get("final_answer") or {}
        if final_answer.get("verdict") != "pass" or "total" not in final_answer:
            raise AssertionError(f"{result.get('case_id')}: final_answer score missing or failed")
        if result.get("target_tool") == "web_search" and int(result.get("ledger_event_count") or 0) <= 0:
            raise AssertionError(f"{result.get('case_id')}: missing ledger events")
        if result.get("case_id") == "web_search_yobot_github_failure" and result.get("tool_status") != "success":
            if "github" not in (result.get("attempt_engines") or []):
                raise AssertionError("web_search_yobot_github_failure: missing github attempt in failure chain")
        if result.get("case_id") == "browser_agent_contract_boundary" and result.get("contract_valid") is not True:
            raise AssertionError("browser_agent_contract_boundary: contract_valid is not true")
        if result.get("case_id") == "browser_agent_handler_stub_boundary" and result.get("tool_status") != "success":
            raise AssertionError("browser_agent_handler_stub_boundary: expected success")
        if result.get("case_id") == "agent_loop_runtime_mapper_web_search":
            if result.get("tool_status") != "success":
                raise AssertionError("agent_loop_runtime_mapper_web_search: expected success")
            if "FINAL_LOOP_ANSWER" not in str((result.get("final_answer") or {}).get("text") or ""):
                raise AssertionError("agent_loop_runtime_mapper_web_search: final answer must come from the loop output")
            if result.get("runtime_started_turns") != result.get("runtime_completed_turns"):
                raise AssertionError("agent_loop_runtime_mapper_web_search: runtime turn events are unbalanced")
            if not result.get("ledger_tool_turns") or any(turn is None for turn in result.get("ledger_tool_turns")):
                raise AssertionError("agent_loop_runtime_mapper_web_search: runtime_ledger tool events must include turn")
            observability = result.get("observability") or {}
            aligned = observability.get("aligned") or {}
            if aligned.get("has_ledger_events") is not True or aligned.get("has_runtime_host_events") is not True:
                raise AssertionError("agent_loop_runtime_mapper_web_search: observability summary must include both ledgers")
            if aligned.get("runtime_session_matches_run_id") is not True:
                raise AssertionError("agent_loop_runtime_mapper_web_search: RuntimeHost session must match ledger run_id")
        if result.get("case_id") == "agent_loop_runtime_mapper_web_search_failure":
            if result.get("tool_status") != "error":
                raise AssertionError("agent_loop_runtime_mapper_web_search_failure: expected structured error")
            if result.get("final_status") != "structured_failure":
                raise AssertionError("agent_loop_runtime_mapper_web_search_failure: expected structured_failure final_status")
            ledger = (result.get("observability") or {}).get("ledger") or {}
            if not ledger.get("decisions"):
                raise AssertionError("agent_loop_runtime_mapper_web_search_failure: expected failure decision")
            final_answer = result.get("final_answer") or {}
            if final_answer.get("verdict") != "pass" or "structured failure" not in str(final_answer.get("text") or ""):
                raise AssertionError("agent_loop_runtime_mapper_web_search_failure: final answer must disclose failure")
        if result.get("forbidden_tools_used"):
            raise AssertionError(f"{result.get('case_id')}: forbidden tool used: {result.get('forbidden_tools_used')}")
    if summary.get("case_count", 0) < 3:
        raise AssertionError("summary case_count is less than 3")
    print("[smoke_eval_registry] ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
