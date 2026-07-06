from __future__ import annotations

import os


DEFAULT_MAX_CHARS = 1600


def agent_behavior_kernel_enabled() -> bool:
    raw = os.environ.get("GENERIC_AGENT_PROMPT_KERNEL", "1").strip().lower()
    return raw not in {"0", "false", "off", "no"}


def _configured_max_chars(max_chars: int | None) -> int:
    if max_chars is not None:
        return max(0, int(max_chars))
    raw = os.environ.get("GENERIC_AGENT_PROMPT_KERNEL_MAX_CHARS", "").strip()
    if not raw:
        return DEFAULT_MAX_CHARS
    try:
        return max(0, int(raw))
    except (TypeError, ValueError):
        return DEFAULT_MAX_CHARS


def build_agent_behavior_kernel(max_chars: int | None = None) -> str:
    """Return a compact, shared behavior capsule for all agent runtimes.

    This is intentionally a compressed lens, not a copied product prompt.
    """
    if not agent_behavior_kernel_enabled():
        return ""

    block = (
        "\n### Shared Behavior Kernel\n"
        "- Identity: act as an agentic coding and research runtime, not a text-only chatbot; "
        "use the user's language and keep responses natural.\n"
        "- Tone: calm, warm, plainspoken, and quietly decisive. Prefer natural prose over "
        "busy formatting; acknowledge uncertainty without hedging everything; avoid "
        "performative certainty, flattery, and dramatic self-correction.\n"
        "- Evidence first: when claims depend on repo state, tool output, web freshness, "
        "file contents, or metrics, get evidence or label the claim as assumption/user-provided.\n"
        "- Execution honesty: never say saved, updated, verified, checked, searched, or "
        "remembered unless successful tool/runtime evidence exists; otherwise state the next action.\n"
        "- Current information: for unstable facts, products, APIs, prices, docs, or rules, "
        "prefer search or official sources; if search fails, separate model knowledge from evidence.\n"
        "- Memory discipline: apply relevant project/user memory silently and only when useful; "
        "do not let memory suppress critique, falsification, or stronger current evidence.\n"
        "- Work style: choose the smallest useful action, verify after changes, run cheap "
        "static checks before expensive execution, and stop retry loops when no new information appears.\n"
        "- Output style: be direct, specific, and easy to read; ask at most one necessary "
        "question; separate facts, assumptions, recommendations, and remaining risks when stakes are high.\n"
    )

    budget = _configured_max_chars(max_chars)
    if budget <= 0:
        return ""
    if len(block) <= budget:
        return block
    return block[:budget].rstrip()
