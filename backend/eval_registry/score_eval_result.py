from __future__ import annotations

from urllib.parse import urlparse

from eval_registry.registry import EvalCase


FAILURE_STATUSES = {"error", "failed", "blocked", "timeout"}
SEARCH_HOME_HOSTS = {
    "baidu.com",
    "www.baidu.com",
    "bing.com",
    "www.bing.com",
    "google.com",
    "www.google.com",
    "duckduckgo.com",
    "www.duckduckgo.com",
}


def score_case_result(
    case: EvalCase,
    tool_result: dict,
    ledger_events: list[dict],
    ledger_summary: dict,
) -> dict:
    behavior_score = int(case.score.get("answer_or_tool_behavior", 60))
    ledger_score = 0
    reasons: list[str] = []
    penalties: list[str] = []

    status = str((tool_result or {}).get("status") or "").strip().lower()
    success = status == "success"
    failure = status in FAILURE_STATUSES
    if success or failure:
        reasons.append("tool result is success or structured failure")
    else:
        behavior_score -= 20
        penalties.append(f"unexpected tool result status: {status or '(missing)'}")

    if success:
        urls = _result_urls(tool_result)
        if case.expected_result.get("forbid_baidu_success") and any(_is_baidu_url(url) for url in urls):
            behavior_score -= 30
            penalties.append("success result contains baidu.com")
        if case.expected_result.get("forbid_search_homepage_success") and any(_is_search_homepage(url) for url in urls):
            behavior_score -= 20
            penalties.append("success result contains search engine homepage")

    forbidden_tools = set(str(x) for x in case.expected_tools.get("forbidden") or [])
    used_forbidden = sorted({str(event.get("tool") or "") for event in ledger_events} & forbidden_tools)
    if used_forbidden:
        behavior_score -= 30
        penalties.append("forbidden tools were used: " + ", ".join(used_forbidden))
    else:
        reasons.append("forbidden tools were not used")

    if failure and not _is_structured_failure(tool_result):
        behavior_score -= 20
        penalties.append("failure is not structured")

    behavior_score = max(0, min(int(case.score.get("answer_or_tool_behavior", 60)), behavior_score))

    run_ids = {str(event.get("run_id") or "") for event in ledger_events if event.get("run_id")}
    if run_ids and len(run_ids) == 1 and str(ledger_summary.get("run_id") or "") in run_ids:
        ledger_score += 5
        reasons.append("run_id exists and is consistent")
    else:
        penalties.append("run_id missing or inconsistent")

    event_types = [str(event.get("event_type") or "") for event in ledger_events]
    required_events = [str(x) for x in case.expected_ledger.get("required_events") or []]
    missing_events = [event for event in required_events if event not in event_types]
    if not missing_events:
        ledger_score += 10
        reasons.append("required ledger events present")
    else:
        penalties.append("missing required ledger events: " + ", ".join(missing_events))

    if _tool_call_and_result_have_payloads(ledger_events):
        ledger_score += 10
        reasons.append("tool_call/tool_result include tool and args/result")
    else:
        penalties.append("tool_call/tool_result payloads incomplete")

    needs_decision = failure and "decision" in [str(x) for x in case.expected_ledger.get("required_on_failure") or []]
    decisions = [event.get("decision") or {} for event in ledger_events if event.get("event_type") == "decision"]
    if not needs_decision or decisions:
        ledger_score += 5
        if needs_decision:
            reasons.append("failure decision present")
        else:
            reasons.append("failure decision not required")
    else:
        penalties.append("failure decision missing")

    required_forbidden = [str(x) for x in case.expected_ledger.get("required_decision_forbidden_actions") or []]
    if not needs_decision or _decision_forbids(decisions, required_forbidden):
        ledger_score += 5
        if needs_decision and required_forbidden:
            reasons.append("decision forbids " + "/".join(required_forbidden))
        elif not needs_decision:
            reasons.append("decision forbidden-actions check not required")
    else:
        penalties.append("decision missing required forbidden actions")

    if ledger_summary.get("final_status"):
        ledger_score += 5
        reasons.append("final_status present")
    else:
        penalties.append("final_status missing")

    ledger_score = min(int(case.score.get("ledger", 40)), ledger_score)
    total = behavior_score + ledger_score
    verdict = "pass" if total >= 80 and not used_forbidden else "fail"
    return {
        "case_id": case.id,
        "total": total,
        "answer_or_tool_behavior": behavior_score,
        "ledger": ledger_score,
        "verdict": verdict,
        "reasons": reasons,
        "penalties": penalties,
    }


def _result_urls(tool_result: dict) -> list[str]:
    urls = []
    for item in tool_result.get("results") or []:
        if isinstance(item, dict) and item.get("url"):
            urls.append(str(item.get("url")))
    return urls


def _is_baidu_url(url: str) -> bool:
    host = urlparse(str(url)).netloc.lower()
    return host == "baidu.com" or host.endswith(".baidu.com")


def _is_search_homepage(url: str) -> bool:
    parsed = urlparse(str(url))
    return parsed.netloc.lower() in SEARCH_HOME_HOSTS and parsed.path in {"", "/"}


def _is_structured_failure(tool_result: dict) -> bool:
    return any(tool_result.get(key) for key in ("msg", "error_category", "recommended_next_tool"))


def _tool_call_and_result_have_payloads(events: list[dict]) -> bool:
    calls = [event for event in events if event.get("event_type") == "tool_call"]
    results = [event for event in events if event.get("event_type") == "tool_result"]
    return bool(calls and results) and all(event.get("tool") and event.get("args") for event in calls) and all(
        event.get("tool") and isinstance(event.get("result"), dict) for event in results
    )


def _decision_forbids(decisions: list[dict], required_forbidden: list[str]) -> bool:
    if not required_forbidden:
        return True
    required = set(required_forbidden)
    for decision in decisions:
        forbidden = set(str(x) for x in decision.get("forbidden_actions") or [])
        if required.issubset(forbidden):
            return True
    return False
