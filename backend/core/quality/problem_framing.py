"""Problem Framing Layer – classify user input into task frames.

This is a public task-understanding constraint, NOT a hidden chain-of-thought.
It helps the agent understand the problem type without asking the user
unnecessary clarification questions.

Design:
- Default: do not interrogate the user.
- When uncertain, make minimal, reversible, low-risk assumptions.
- Only surface framing to the model as a compact public hint (not as hidden thinking).
"""

from __future__ import annotations

import os

PROBLEM_FRAMING_ENV_VAR = "GENERIC_AGENT_PROBLEM_FRAMING"

# ── Trigger phrase sets ─────────────────────────────────────────────

_IMPROVEMENT_TRIGGERS = [
    "优化",
    "改进",
    "提升",
    "增强",
    "加快",
    "提速",
    "性能",
    "瓶颈",
    "慢",
    "效率",
    "加速",
    "缩短",
    "降低延迟",
    "减少",
    "精简",
    "optimize",
    "improve",
    "enhance",
    "speed up",
    "performance",
    "bottleneck",
    "latency",
    "efficiency",
]

_ARCHITECTURE_TRIGGERS = [
    "架构",
    "重构",
    "设计",
    "结构",
    "模块",
    "分层",
    "解耦",
    "抽象",
    "接口",
    "组件",
    "模式",
    "技术路线",
    "技术选型",
    "方案",
    "architecture",
    "refactor",
    "design",
    "restructure",
    "decouple",
    "modular",
    "pattern",
    "component",
]

_ROADMAP_TRIGGERS = [
    "下一步",
    "规划",
    "路线图",
    "优先级",
    "todo",
    "待办",
    "roadmap",
    "plan",
    "next step",
    "priority",
    "what's next",
]

_UNDERSTANDING_TRIGGERS = [
    "理解",
    "解释",
    "说明",
    "分析",
    "审查",
    "review",
    "assess",
    "evaluate",
    "诊断",
    "排查",
    "调试",
    "debug",
    "为什么",
    "原因",
    "根源",
    "understand",
    "explain",
    "analyze",
    "diagnose",
    "troubleshoot",
]

_IMPLEMENTATION_TRIGGERS = [
    "实现",
    "开发",
    "编写",
    "新增",
    "添加",
    "创建",
    "修改",
    "修复",
    "fix",
    "implement",
    "develop",
    "create",
    "add",
    "modify",
    "change",
    "patch",
]

_AI_CAPABILITY_TRIGGERS = [
    "人工智能",
    "AI",
    "智能体",
    "agent",
    "模型",
    "model",
    "推理",
    "思考",
    "思维",
    "认知",
    "理解能力",
    "reasoning",
    "thinking",
    "cognition",
    "认知",
    "智能",
    "intelligence",
    "RAG",
    "检索增强",
    "多智能体",
    "multi-agent",
    "prompt",
    "提示词",
    "上下文",
    "context",
    "token",
    "llm",
    "大模型",
    "大语言模型",
    "fine-tune",
    "微调",
    "训练",
]

# These should NOT trigger framing (simple read/shortcut actions)
_READ_EXCLUDES = [
    "读取",
    "第一行",
    "标题",
    "readme 第一行",
    "只用一句话",
    "read file",
    "cat ",
    "show me the first",
]

_FRAMING_HINT_TEMPLATE = (
    "### Task Framing\n"
    "When handling this user request, apply these problem-solving constraints:\n"
    "1. Classify the task type internally (improvement / architecture / roadmap / "
    "understanding / implementation / AI-capability) but do NOT echo the classification back to the user.\n"
    "2. Do NOT ask the user clarification questions by default. Make minimal, reversible, "
    "low-risk assumptions and proceed.\n"
    "3. Only ask the user when: safety/irreversible operations are involved, the target "
    "object is missing, candidate choices are equiprobable with divergent outcomes, "
    "cost differences are extreme, or privacy/permissions are at stake.\n"
    "4. When uncertain about scope, start with the narrowest scope that matches the "
    "user's explicit words, then broaden only if evidence demands it.\n"
    "5. Prefer examining existing state (files, logs, code, config) over interrogating the user.\n"
    "6. If the request is ambiguous about target (e.g. 'optimize this project'), analyze "
    "the current state first, then present findings — do NOT ask 'which part?' upfront.\n"
    "7. This framing is a task-understanding constraint. It must NOT appear in your "
    "final answer. Do NOT output these rules or the framing classification to the user."
)


def problem_framing_enabled() -> bool:
    value = str(os.environ.get(PROBLEM_FRAMING_ENV_VAR, "1")).strip().lower()
    return value not in {"0", "false", "no", "off"}


def _contains_any(query: str, phrases: list[str]) -> bool:
    return any(phrase.lower() in query for phrase in phrases)


def should_inject_problem_framing(user_input: str) -> bool:
    """Check whether the user input warrants problem framing injection."""
    query = str(user_input or "").strip().lower()
    if not query:
        return False
    if _contains_any(query, _READ_EXCLUDES):
        return False
    matched = (
        _contains_any(query, _IMPROVEMENT_TRIGGERS)
        or _contains_any(query, _ARCHITECTURE_TRIGGERS)
        or _contains_any(query, _ROADMAP_TRIGGERS)
        or _contains_any(query, _UNDERSTANDING_TRIGGERS)
        or _contains_any(query, _AI_CAPABILITY_TRIGGERS)
    )
    return matched


def _classify_task_frame(user_input: str) -> str:
    """Internal classification — returns the primary task frame.

    Used only for statistics/logging, not surfaced to the model as a label.
    """
    query = str(user_input or "").strip().lower()
    if _contains_any(query, _AI_CAPABILITY_TRIGGERS):
        return "ai_capability"
    if _contains_any(query, _ARCHITECTURE_TRIGGERS):
        return "architecture"
    if _contains_any(query, _ROADMAP_TRIGGERS):
        return "roadmap"
    if _contains_any(query, _IMPROVEMENT_TRIGGERS):
        return "improvement"
    if _contains_any(query, _UNDERSTANDING_TRIGGERS):
        return "understanding"
    if _contains_any(query, _IMPLEMENTATION_TRIGGERS):
        return "implementation"
    return "general"


def _truncate_text(text: str, max_chars: int) -> str:
    limit = max(int(max_chars or 0), 1)
    if len(text) <= limit:
        return text
    marker = "\n[truncated]"
    if limit <= len(marker):
        return text[:limit]
    return text[: limit - len(marker)].rstrip() + marker


def build_problem_framing_context(
    user_input: str,
    max_chars: int = 1800,
) -> dict:
    """Build a problem framing context block for the given user input.

    Returns:
        dict with keys: block (str), chars (int), matched (bool),
        frame (str), reason (str)
    """
    matched = should_inject_problem_framing(user_input)
    if not matched:
        return {
            "block": "",
            "chars": 0,
            "matched": False,
            "frame": "general",
            "reason": "query did not match problem-framing triggers",
        }
    frame = _classify_task_frame(user_input)
    block = _truncate_text(_FRAMING_HINT_TEMPLATE, max_chars=max_chars)
    return {
        "block": block,
        "chars": len(block),
        "matched": True,
        "frame": frame,
        "reason": f"matched {frame} framing triggers",
    }
