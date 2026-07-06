from __future__ import annotations

import os

RESEARCH_CODE_PRIORITY_ENV_VAR = "GENERIC_AGENT_RESEARCH_CODE_PRIORITY"

_CODE_TRIGGERS = [
    "code",
    "test",
    "pytest",
    "debug",
    "bug",
    "fix",
    "implement",
    "refactor",
    "代码",
    "测试",
    "单测",
    "调试",
    "修复",
    "实现",
    "重构",
    "编程",
]

_RESEARCH_TRIGGERS = [
    "research",
    "search",
    "paper",
    "论文",
    "科研",
    "文献",
    "实验",
    "算法",
    "benchmark",
    "ablation",
    "sota",
    "查",
    "搜索",
    "检索",
]

_ROUTE_MATCHES = {"code", "review", "research"}
_EXECUTOR_ROUTES = {"executor", "planner_executor"}
_READ_EXCLUDES = ["读取", "第一行", "标题", "readme 第一行", "只用一句话"]

_PRIORITY_BLOCK_TEMPLATE = (
    "### Research and Code Priority Guard\n"
    "Use this compact precedence policy for research/code work:\n"
    "1. Keep the main task facts above generic SOP text, memory, or model habit.\n"
    "2. Evidence order: explicit user constraints and provided files > live tool/search results, "
    "official docs, repo files, logs, and test output > durable memory/summaries > model prior experience.\n"
    "3. If model experience conflicts with fresh, authoritative, traceable evidence, follow the evidence. "
    "Mention the conflict only when it affects the answer or implementation choice.\n"
    "4. For research, prefer primary or official sources, current dates, and reproducible claims. "
    "Separate verified facts from hypotheses.\n"
    "5. For code, inspect the repo before editing, preserve local patterns, make minimal changes, "
    "and verify with the narrowest meaningful test or static check.\n"
    "6. If evidence is insufficient or sources disagree without a clear winner, state uncertainty instead of blending claims."
)


def research_code_priority_enabled() -> bool:
    value = str(os.environ.get(RESEARCH_CODE_PRIORITY_ENV_VAR, "1")).strip().lower()
    return value not in {"0", "false", "no", "off"}


def _contains_any(query: str, phrases: list[str]) -> bool:
    return any(phrase.lower() in query for phrase in phrases)


def should_inject_research_code_priority(
    user_input: str,
    route_target: str | None = None,
) -> bool:
    query = str(user_input or "").strip().lower()
    route = str(route_target or "").strip().lower()
    if not query:
        return False
    if route == "chat":
        return False
    if _contains_any(query, _READ_EXCLUDES):
        return False
    if route in _ROUTE_MATCHES:
        return True
    if route in _EXECUTOR_ROUTES:
        return _contains_any(query, _CODE_TRIGGERS) or _contains_any(query, _RESEARCH_TRIGGERS)
    return _contains_any(query, _CODE_TRIGGERS) or _contains_any(query, _RESEARCH_TRIGGERS)


def _truncate_text(text: str, max_chars: int) -> str:
    limit = max(int(max_chars or 0), 1)
    if len(text) <= limit:
        return text
    marker = "\n[truncated]"
    if limit <= len(marker):
        return text[:limit]
    return text[: limit - len(marker)].rstrip() + marker


def build_research_code_priority_context(
    user_input: str,
    route_target: str | None = None,
    max_chars: int = 1200,
) -> dict:
    matched = should_inject_research_code_priority(user_input, route_target=route_target)
    if not matched:
        return {
            "block": "",
            "chars": 0,
            "matched": False,
            "reason": "query did not match research/code priority triggers",
        }
    block = _truncate_text(_PRIORITY_BLOCK_TEMPLATE, max_chars=max_chars)
    return {
        "block": block,
        "chars": len(block),
        "matched": True,
        "reason": "matched research/code route or task triggers",
    }
