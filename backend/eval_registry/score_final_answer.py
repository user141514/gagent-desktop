from __future__ import annotations

import re
from urllib.parse import urlparse

from eval_registry.registry import EvalCase


FAILURE_STATUSES = {"error", "failed", "blocked", "timeout"}
FINAL_ANSWER_SCORE_FIELDS = frozenset({"case_id", "total", "verdict", "reasons", "penalties"})
FAILURE_WORDS = (
    "failed",
    "failure",
    "blocked",
    "timeout",
    "unavailable",
    "error",
    "could not",
    "no successful",
    # Common Chinese failure words, kept escaped so this source stays ASCII.
    "\u5931\u8d25",
    "\u4e0d\u53ef\u7528",
    "\u8d85\u65f6",
    "\u963b\u585e",
)
FALSE_SUCCESS_PHRASES = (
    "here are the results",
    "successfully found",
    "i found",
    "found the repository",
    "\u6210\u529f\u627e\u5230",
    "\u6211\u627e\u5230",
    "\u627e\u5230\u4e86",
    "\u7ed3\u679c\u5982\u4e0b",
)
NEGATED_FOUND_PHRASES = (
    "not found",
    "no result found",
    "no results found",
    "no successful result",
    "nothing was found",
)


def make_default_final_answer(case: EvalCase, tool_result: dict) -> str:
    status = _status(tool_result)
    if status == "success":
        urls = _result_urls(tool_result)
        if urls:
            return f"{case.target_tool} succeeded. Source: {urls[0]}"
        if tool_result.get("contract_valid") is True:
            return f"{case.target_tool} contract validation succeeded."
        if tool_result.get("success") is True:
            return f"{case.target_tool} succeeded in {tool_result.get('steps_taken', 0)} steps."
        return f"{case.target_tool} succeeded."
    reason = tool_result.get("error_category") or tool_result.get("msg") or "structured failure"
    return f"{case.target_tool} returned a structured failure: {reason}. No successful result is available."


def score_final_answer(case: EvalCase, answer_text: str, tool_result: dict) -> dict:
    answer = str(answer_text or "").strip()
    lowered = answer.lower()
    total = 100
    reasons: list[str] = []
    penalties: list[str] = []
    status = _status(tool_result)

    if not answer:
        total -= 50
        penalties.append("final answer is empty")

    if status == "success":
        if any(word in lowered for word in FAILURE_WORDS):
            total -= 40
            penalties.append("answer claims failure despite successful tool result")
        urls = _result_urls(tool_result)
        if urls and not any(url in answer for url in urls):
            total -= 30
            penalties.append("answer omits successful source URL")
        if not penalties:
            reasons.append("answer is consistent with successful tool result")
    else:
        if _claims_success(lowered):
            total -= 70
            penalties.append("answer claims success despite failed tool result")
        if not any(word in lowered for word in FAILURE_WORDS):
            total -= 30
            penalties.append("answer does not disclose structured failure")
        if not penalties:
            reasons.append("answer discloses structured failure")

    forbidden_recommendations = _forbidden_tool_recommendations(case, lowered)
    if forbidden_recommendations:
        total -= 60
        penalties.append("answer recommends forbidden fallback tools: " + ", ".join(forbidden_recommendations))

    total = max(0, total)
    return {
        "case_id": case.id,
        "total": total,
        "verdict": "pass" if total >= 80 else "fail",
        "reasons": reasons,
        "penalties": penalties,
    }


def _claims_success(lowered_answer: str) -> bool:
    if any(phrase in lowered_answer for phrase in FALSE_SUCCESS_PHRASES):
        return True
    if not re.search(r"\bfound\b", lowered_answer):
        return False
    return not any(phrase in lowered_answer for phrase in NEGATED_FOUND_PHRASES)


def _forbidden_tool_recommendations(case: EvalCase, lowered_answer: str) -> list[str]:
    hits: list[str] = []
    for tool in [str(item).lower() for item in case.expected_tools.get("forbidden") or []]:
        escaped = re.escape(tool)
        if re.search(rf"\b(try|use|run|call|open|switch to|fall back to|fallback to)\s+{escaped}\b", lowered_answer):
            hits.append(tool)
        elif re.search(rf"\b{escaped}\s+(next|instead|as fallback|as a fallback)\b", lowered_answer):
            hits.append(tool)
    return hits


def _status(tool_result: dict) -> str:
    status = str((tool_result or {}).get("status") or "").strip().lower()
    if not status and (tool_result or {}).get("success") is True:
        return "success"
    if not status and (tool_result or {}).get("success") is False:
        return "error"
    if status in FAILURE_STATUSES:
        return "error"
    return status or "unknown"


def _result_urls(tool_result: dict) -> list[str]:
    urls: list[str] = []

    def walk(value) -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                if str(key).lower() in {"url", "link", "href", "source_url", "canonical_url"} and isinstance(child, str):
                    parsed = urlparse(child)
                    if parsed.scheme in {"http", "https"} and parsed.netloc:
                        urls.append(child)
                else:
                    walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)

    walk(tool_result or {})
    return urls
