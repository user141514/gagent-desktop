#!/usr/bin/env python
from __future__ import annotations

import sys
from pathlib import Path
from typing import get_args


BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from eval_registry.registry import default_cases_dir, load_eval_case, load_eval_cases  # noqa: E402
from core.runtime.event_schema import RuntimeEventType  # noqa: E402
from runtime_ledger.ledger import _ALLOWED_EVENT_TYPES  # noqa: E402


ROOT = Path(__file__).resolve().parents[2]
RUNTIME_EVENT_TYPES = set(str(event) for event in get_args(RuntimeEventType))
EXPECTED_TOOLS_FIELDS = {"allowed", "forbidden"}
EXPECTED_LEDGER_FIELDS = {"required_decision_forbidden_actions", "required_events", "required_on_failure"}
EXPECTED_RESULT_FIELDS = {
    "allow_success",
    "allow_structured_failure",
    "forbid_baidu_success",
    "forbid_page_content_success",
    "forbid_search_homepage_success",
    "forbid_search_shaped_success",
    "require_balanced_turn_events",
    "require_browser_agent_success",
    "require_contract_terms",
    "require_contract_valid",
    "require_final_status",
    "require_navigation_success",
    "require_runtime_events",
}
SCORE_FIELDS = {"answer_or_tool_behavior", "ledger"}


def validate() -> list[str]:
    errors: list[str] = []
    cases_dir = default_cases_dir(ROOT)
    if not cases_dir.exists():
        return [f"cases directory does not exist: {cases_dir}"]

    case_paths = sorted(cases_dir.glob("*.json"))
    if len(case_paths) < 3:
        errors.append(f"expected at least 3 eval cases, found {len(case_paths)}")

    try:
        cases = load_eval_cases(cases_dir)
    except ValueError as exc:
        return [str(exc)]

    for case in cases:
        try:
            loaded = load_eval_case(case.source_path)
        except ValueError as exc:
            errors.append(str(exc))
            continue
        errors.extend(_validate_loaded_case(loaded))

    return errors


def _validate_loaded_case(loaded) -> list[str]:
    errors: list[str] = []
    if loaded.id != Path(loaded.source_path).stem:
        errors.append(f"{loaded.source_path}: id and filename mismatch")
    tool_dir = ROOT / "backend" / "tool_registry" / "tools"
    registry_tools = {path.stem for path in tool_dir.glob("*.yml")}
    tool_path = tool_dir / f"{loaded.target_tool}.yml"
    if not tool_path.exists():
        errors.append(f"{loaded.id}: target_tool registry missing: {tool_path}")
    for field_name, payload, allowed_fields in (
        ("expected_tools", loaded.expected_tools, EXPECTED_TOOLS_FIELDS),
        ("expected_ledger", loaded.expected_ledger, EXPECTED_LEDGER_FIELDS),
        ("score", loaded.score, SCORE_FIELDS),
    ):
        unknown = sorted(set(str(key) for key in payload) - allowed_fields)
        if unknown:
            errors.append(f"{loaded.id}: {field_name} contains unknown field: {', '.join(unknown)}")
    allowed = loaded.expected_tools.get("allowed")
    forbidden = loaded.expected_tools.get("forbidden")
    if not isinstance(allowed, list) or not allowed:
        errors.append(f"{loaded.id}: expected_tools.allowed must be a non-empty list")
    elif loaded.target_tool not in [str(tool) for tool in allowed]:
        errors.append(f"{loaded.id}: expected_tools.allowed must include target_tool {loaded.target_tool}")
    if not isinstance(forbidden, list) or not forbidden:
        errors.append(f"{loaded.id}: expected_tools.forbidden must be a non-empty list")
    if isinstance(allowed, list) and isinstance(forbidden, list):
        overlap = sorted(set(str(tool) for tool in allowed) & set(str(tool) for tool in forbidden))
        if overlap:
            errors.append(f"{loaded.id}: expected_tools.allowed and forbidden must not overlap: {', '.join(overlap)}")
    for field_name, tools in (("allowed", allowed), ("forbidden", forbidden)):
        if isinstance(tools, list):
            unknown = sorted({str(tool) for tool in tools if str(tool) not in registry_tools})
            if unknown:
                errors.append(f"{loaded.id}: expected_tools.{field_name} contains unknown tool: {', '.join(unknown)}")
    required_decision_forbidden = loaded.expected_ledger.get("required_decision_forbidden_actions")
    if isinstance(forbidden, list) and isinstance(required_decision_forbidden, list):
        drift = sorted(set(str(tool) for tool in required_decision_forbidden) - set(str(tool) for tool in forbidden))
        if drift:
            errors.append(
                f"{loaded.id}: required_decision_forbidden_actions must be a subset of expected_tools.forbidden: {', '.join(drift)}"
            )
    total_score = int(loaded.score.get("answer_or_tool_behavior", 0)) + int(loaded.score.get("ledger", 0))
    if total_score != 100:
        errors.append(f"{loaded.id}: score weights must sum to 100, got {total_score}")
    unknown_expected_result = sorted(set(str(key) for key in loaded.expected_result) - EXPECTED_RESULT_FIELDS)
    if unknown_expected_result:
        errors.append(f"{loaded.id}: expected_result contains unknown field: {', '.join(unknown_expected_result)}")
    allow_success = loaded.expected_result.get("allow_success")
    allow_structured_failure = loaded.expected_result.get("allow_structured_failure")
    if not isinstance(allow_success, bool):
        errors.append(f"{loaded.id}: expected_result.allow_success must be a boolean")
    if not isinstance(allow_structured_failure, bool):
        errors.append(f"{loaded.id}: expected_result.allow_structured_failure must be a boolean")
    if allow_success is False and allow_structured_failure is False:
        errors.append(f"{loaded.id}: expected_result must allow success or structured failure")
    if loaded.expected_result.get("forbid_baidu_success") is True and loaded.target_tool != "web_search":
        errors.append(f"{loaded.id}: expected_result.forbid_baidu_success requires target_tool web_search")
    if loaded.expected_result.get("forbid_search_homepage_success") is True and loaded.target_tool != "web_search":
        errors.append(f"{loaded.id}: expected_result.forbid_search_homepage_success requires target_tool web_search")
    if loaded.expected_result.get("forbid_search_shaped_success") is True and loaded.target_tool != "web_scan":
        errors.append(f"{loaded.id}: expected_result.forbid_search_shaped_success requires target_tool web_scan")
    if loaded.expected_result.get("forbid_page_content_success") is True and loaded.target_tool != "web_scan":
        errors.append(f"{loaded.id}: expected_result.forbid_page_content_success requires target_tool web_scan")
    if loaded.expected_result.get("require_navigation_success") is True and loaded.target_tool != "web_execute_js":
        errors.append(f"{loaded.id}: expected_result.require_navigation_success requires target_tool web_execute_js")
    if loaded.expected_result.get("require_contract_valid") is True and (
        loaded.target_tool != "browser_agent" or loaded.type != "tool_contract_eval"
    ):
        errors.append(f"{loaded.id}: expected_result.require_contract_valid requires browser_agent tool_contract_eval")
    if loaded.expected_result.get("require_contract_terms") and (
        loaded.target_tool != "browser_agent" or loaded.type != "tool_contract_eval"
    ):
        errors.append(f"{loaded.id}: expected_result.require_contract_terms requires browser_agent tool_contract_eval")
    if loaded.expected_result.get("require_browser_agent_success") is True and (
        loaded.target_tool != "browser_agent" or loaded.type != "tool_handler_eval"
    ):
        errors.append(f"{loaded.id}: expected_result.require_browser_agent_success requires browser_agent tool_handler_eval")
    if loaded.expected_result.get("require_runtime_events") and loaded.type != "agent_loop_eval":
        errors.append(f"{loaded.id}: expected_result.require_runtime_events requires agent_loop_eval")
    if isinstance(loaded.expected_result.get("require_runtime_events"), list):
        unknown_runtime_events = sorted(
            {
                str(event)
                for event in loaded.expected_result.get("require_runtime_events") or []
                if str(event) not in RUNTIME_EVENT_TYPES
            }
        )
        if unknown_runtime_events:
            errors.append(
                f"{loaded.id}: expected_result.require_runtime_events contains unsupported runtime event: {', '.join(unknown_runtime_events)}"
            )
    if loaded.expected_result.get("require_balanced_turn_events") is True and loaded.type != "agent_loop_eval":
        errors.append(f"{loaded.id}: expected_result.require_balanced_turn_events requires agent_loop_eval")
    if loaded.expected_result.get("require_balanced_turn_events") is True:
        required_runtime_events = set(str(event) for event in loaded.expected_result.get("require_runtime_events") or [])
        required_turn_events = {"llm_call_started", "llm_call_completed"}
        if not required_turn_events.issubset(required_runtime_events):
            errors.append(
                f"{loaded.id}: expected_result.require_balanced_turn_events requires llm_call_started and llm_call_completed"
            )
    if "require_final_status" in loaded.expected_result:
        required_final_status = loaded.expected_result.get("require_final_status")
        if not isinstance(required_final_status, str) or not required_final_status.strip():
            errors.append(f"{loaded.id}: expected_result.require_final_status must be a non-empty string")
    required_events = loaded.expected_ledger.get("required_events")
    if not isinstance(required_events, list):
        errors.append(f"{loaded.id}: expected_ledger.required_events must be a list")
    else:
        unknown_required_events = sorted({str(event) for event in required_events if str(event) not in _ALLOWED_EVENT_TYPES})
        if unknown_required_events:
            errors.append(
                f"{loaded.id}: expected_ledger.required_events contains unsupported event: {', '.join(unknown_required_events)}"
            )
        for event_name in ("tool_call", "tool_result"):
            if event_name not in required_events:
                errors.append(f"{loaded.id}: required_events must include {event_name}")
    required_on_failure = loaded.expected_ledger.get("required_on_failure")
    if isinstance(required_on_failure, list):
        unknown_failure_events = sorted(
            {str(event) for event in required_on_failure if str(event) not in _ALLOWED_EVENT_TYPES}
        )
        if unknown_failure_events:
            errors.append(
                f"{loaded.id}: expected_ledger.required_on_failure contains unsupported event: {', '.join(unknown_failure_events)}"
            )
    return errors


def main() -> int:
    errors = validate()
    if errors:
        print("[validate_eval_registry] failed", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1
    print("[validate_eval_registry] ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
