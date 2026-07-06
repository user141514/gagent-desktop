from __future__ import annotations

import os


ANSWER_QUALITY_ENV_VAR = "GENERIC_AGENT_ANSWER_QUALITY"

_PLANNING_TRIGGERS = [
    "下一步",
    "怎么优化",
    "架构",
    "架构优化",
    "重构",
    "短板",
    "提升",
    "技术路线",
    "路线",
    "规划",
    "现在做什么",
    "项目定位",
    "能力分析",
    "多智能体",
    "输出质量",
    "回答质量",
    "改进",
    "skill",
    "memory",
    "hooks",
    "runtime",
    "profiler",
    "audit",
]

_READ_EXCLUDES = [
    "读取",
    "第一行",
    "标题",
    "readme 第一行",
    "只用一句话",
]

_EXECUTION_MARKERS = [
    "修改",
    "实现",
    "修复",
    "写代码",
    "运行测试",
    "安装",
    "启动",
    "部署",
]

_QUALITY_BLOCK_TEMPLATE = (
    "### Answer Quality Guard\n"
    "When answering project roadmap / architecture / next-step questions:\n"
    "1. Separate active capabilities from switch-gated, infra-only, and concept-only items.\n"
    "2. Do not recommend capabilities that already exist unless the problem is rollout or integration quality.\n"
    "3. Prefer measured next steps that reduce llm calls, prompt chars, tools schema chars, and invalid handoffs.\n"
    "4. Use current project state:\n"
    "   - Active: RouterRules, planner/chat/classic handoff, profiler, LLM audit, tool slimming, direct answer, read shortcut, planner skill SOP, memory write gate.\n"
    "   - Switch-gated: skill SOP, slim tools, direct answer, read shortcut, early stop, profiler export.\n"
    "   - Infra-only: ExecutionPolicy dry-run, SkillEffects, SkillActivation preview, structured memory store/indexer, LLM cache reuse disabled.\n"
    "   - Concept-only: reviewer injection, tool-backed skill runtime, dynamic/parallel agents, trust-policy marketplace.\n"
    "5. Answer with: current facts -> judgment -> next step -> what not to do.\n"
    "6. Do not default to AutoGen, CrewAI, MemGPT, OpenHands, Cline, parallel agents, or long-term agent memory.\n"
    "7. For project-roadmap / architecture-quality questions, answer from current runtime state first; do not call the classic executor unless the user explicitly asks for file-level evidence or implementation work.\n"
    "8. Memory rule: skills/agents/tools may not write durable memory_items; only candidates/evidence are allowed."
)


def answer_quality_enabled() -> bool:
    value = str(os.environ.get(ANSWER_QUALITY_ENV_VAR, "1")).strip().lower()
    return value not in {"0", "false", "no", "off"}


def _contains_any(query: str, phrases: list[str]) -> bool:
    return any(phrase.lower() in query for phrase in phrases)


def should_inject_answer_quality_context(user_input: str, route_target: str | None = None) -> bool:
    query = str(user_input or "").strip().lower()
    if not query:
        return False
    if route_target and str(route_target).strip().lower() == "chat":
        return False
    if _contains_any(query, _READ_EXCLUDES):
        return False
    planning_hit = _contains_any(query, _PLANNING_TRIGGERS)
    if not planning_hit:
        return False
    if _contains_any(query, _EXECUTION_MARKERS):
        # Allow architecture / roadmap style questions that mention execution terms,
        # but avoid injecting into plain implementation requests.
        meta_override = _contains_any(
            query,
            [
                "架构",
                "重构",
                "路线",
                "技术路线",
                "规划",
                "项目定位",
                "能力分析",
                "多智能体",
                "输出质量",
                "回答质量",
            ],
        )
        if not meta_override:
            return False
    return True


def _truncate_text(text: str, max_chars: int) -> str:
    limit = max(int(max_chars or 0), 1)
    if len(text) <= limit:
        return text
    marker = "\n[truncated]"
    if limit <= len(marker):
        return text[:limit]
    return text[: limit - len(marker)].rstrip() + marker


def build_answer_quality_context(
    user_input: str,
    max_chars: int = 1800,
) -> dict:
    matched = should_inject_answer_quality_context(user_input)
    if not matched:
        return {
            "block": "",
            "chars": 0,
            "matched": False,
            "reason": "query did not match roadmap, architecture, or capability-planning triggers",
        }
    block = _truncate_text(_QUALITY_BLOCK_TEMPLATE, max_chars=max_chars)
    return {
        "block": block,
        "chars": len(block),
        "matched": True,
        "reason": "matched roadmap, architecture, optimization, or capability-analysis intent",
    }
