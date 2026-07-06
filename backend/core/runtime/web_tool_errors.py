from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class WebToolFailure:
    category: str
    action: str
    retryable: bool
    recommended_next_tool: str
    message: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def classify_web_tool_failure(error_text: Any, *, tool_name: str = "") -> WebToolFailure:
    text = _stringify(error_text)
    lowered = text.lower()
    tool_name = str(tool_name or "").strip()

    if _is_rate_limited(lowered):
        return WebToolFailure(
            category="rate_limited",
            action="switch_path_or_wait",
            retryable=False,
            recommended_next_tool=_alternate_tool(tool_name),
            message=(
                "The web/browser path hit an API rate limit. Do not retry the same "
                "LLM-backed browser path immediately; switch to a non-LLM browser "
                "scan/JS path if available, or report the blocker with retry timing."
            ),
        )

    if _is_browser_unavailable(lowered):
        return WebToolFailure(
            category="browser_unavailable",
            action="repair_browser_bridge",
            retryable=False,
            recommended_next_tool=(
                "browser_agent"
                if tool_name in {"web_search", "web_scan", "web_execute_js"}
                else _alternate_tool(tool_name)
            ),
            message=(
                "The local browser bridge has no connected tab/session. Start or "
                "reconnect the browser extension/profile before using web_scan or "
                "web_execute_js, or use browser_agent if an LLM-backed browser is allowed."
            ),
        )

    if _is_dependency_missing(lowered):
        return WebToolFailure(
            category="browser_dependency_missing",
            action="install_or_disable_tool",
            retryable=False,
            recommended_next_tool=_alternate_tool(tool_name),
            message=(
                "The browser automation dependency is missing or not installed. "
                "Install the dependency, or avoid this tool and use an available path."
            ),
        )

    if _is_network_error(lowered):
        return WebToolFailure(
            category="network_error",
            action="check_network_or_proxy",
            retryable=True,
            recommended_next_tool=_alternate_tool(tool_name),
            message=(
                "The web/browser path failed due to connectivity, proxy, DNS, or timeout. "
                "Check the network path before repeating broad online search."
            ),
        )

    return WebToolFailure(
        category="browser_tool_error",
        action="inspect_error",
        retryable=False,
        recommended_next_tool=_alternate_tool(tool_name),
        message="The browser/search tool failed. Inspect the exact error before retrying.",
    )


def enrich_web_tool_result(tool_name: str, result: Any) -> Any:
    if not _looks_failed(result):
        return result
    if not isinstance(result, dict):
        result = {"status": "error", "msg": _stringify(result)}
    failure = classify_web_tool_failure(result, tool_name=tool_name)
    enriched = dict(result)
    enriched.update(
        {
            "status": enriched.get("status") or "error",
            "error_category": failure.category,
            "recovery_action": failure.action,
            "retryable": failure.retryable,
            "recommended_next_tool": failure.recommended_next_tool,
            "recovery_hint": failure.message,
        }
    )
    return enriched


def web_tool_failure_prompt(tool_name: str, failure_or_result: WebToolFailure | dict[str, Any]) -> str:
    if isinstance(failure_or_result, WebToolFailure):
        failure = failure_or_result
    else:
        failure = WebToolFailure(
            category=str(failure_or_result.get("error_category") or "browser_tool_error"),
            action=str(failure_or_result.get("recovery_action") or "inspect_error"),
            retryable=bool(failure_or_result.get("retryable")),
            recommended_next_tool=str(failure_or_result.get("recommended_next_tool") or _alternate_tool(tool_name)),
            message=str(failure_or_result.get("recovery_hint") or "Inspect the browser/search error."),
        )
    return (
        "[WEB TOOL FAILURE]\n"
        f"{tool_name} failed: category={failure.category}, action={failure.action}, "
        f"retryable={str(failure.retryable).lower()}.\n"
        f"{failure.message}\n"
        f"Do not retry {tool_name} immediately with the same inputs. "
        f"Recommended next tool/path: {failure.recommended_next_tool}.\n"
        "If all online paths are unavailable, state the blocker explicitly and ask for "
        "permission to continue with local/offline evidence only."
    )


def _looks_failed(result: Any) -> bool:
    if isinstance(result, dict):
        status = str(result.get("status") or "").strip().lower()
        if status in {"error", "failed", "timeout"}:
            return True
        if result.get("success") is False:
            return True
        text = _stringify(result)
    else:
        text = _stringify(result)
    lowered = text.lower()
    return (
        _is_rate_limited(lowered)
        or _is_browser_unavailable(lowered)
        or _is_dependency_missing(lowered)
        or _is_network_error(lowered)
    )


def _is_rate_limited(lowered: str) -> bool:
    return any(
        token in lowered
        for token in (
            "http 429",
            "status 429",
            " 429",
            "rate limit",
            "rate_limit",
            "rate-limit",
            "too many requests",
            "quota exceeded",
        )
    )


def _is_browser_unavailable(lowered: str) -> bool:
    return any(
        token in lowered
        for token in (
            "no available browser",
            "no connected browser",
            "no available browser tabs",
            "extension is not connected",
            "browser extension",
            "session id",
            "sessionid",
            "not connected",
            "connection refused",
            "websocket",
            "没有可用",
            "未连接",
        )
    )


def _is_dependency_missing(lowered: str) -> bool:
    return any(
        token in lowered
        for token in (
            "browser-use is not installed",
            "no module named",
            "playwright install",
            "executable doesn't exist",
            "chromium",
        )
    )


def _is_network_error(lowered: str) -> bool:
    return any(
        token in lowered
        for token in (
            "timeout",
            "timed out",
            "dns",
            "proxy",
            "connection reset",
            "connection aborted",
            "temporarily unavailable",
            "name resolution",
        )
    )


def _alternate_tool(tool_name: str) -> str:
    if tool_name == "browser_agent":
        return "web_search(engine='bing')"
    if tool_name == "web_search":
        return "web_search(engine='bing' or engine='duckduckgo') / local-offline evidence"
    if tool_name in {"web_scan", "web_execute_js"}:
        return "web_search(engine='bing') for search; browser_agent only for rendered workflows"
    return "local/offline evidence"


def _stringify(value: Any) -> str:
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, ensure_ascii=False, default=str)
    except Exception:
        return str(value)


__all__ = [
    "WebToolFailure",
    "classify_web_tool_failure",
    "enrich_web_tool_result",
    "web_tool_failure_prompt",
]
