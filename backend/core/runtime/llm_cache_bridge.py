"""Bridge: wire LLMCallCache into actual LLM call sites (P2-cache).

Adds semantic question canonicalization on top of exact prompt hash,
so "帮我写个快排" and "写一个快速排序" share the same cache entry.
"""

from __future__ import annotations

import hashlib
import os
import re
import time
from pathlib import Path
from typing import Any

CACHE_ENV_VAR = "GENERIC_AGENT_LLM_CACHE"


def llm_cache_enabled() -> bool:
    return os.environ.get(CACHE_ENV_VAR, "").strip() == "1"


# ── Semantic canonicalization ────────────────────────────────────


def _extract_user_question(messages: list[dict] | str) -> str:
    """Extract the latest user question from messages for semantic hashing."""
    if isinstance(messages, str):
        return messages.strip()
    text_parts = []
    for msg in reversed(messages):
        if isinstance(msg, dict) and msg.get("role") == "user":
            content = msg.get("content", "")
            if isinstance(content, str):
                text_parts.append(content)
            elif isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "text":
                        text_parts.append(block.get("text", ""))
            if text_parts:
                break
    return " ".join(text_parts).strip() if text_parts else ""


def _canonicalize(text: str) -> str:
    """Normalize a user question: lowercase, strip punctuation, collapse whitespace."""
    text = text.strip().lower()
    text = re.sub(r"[^\w\s]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def make_semantic_hash(messages: list[dict] | str) -> str:
    """Hash the canonicalized user question — survives minor rewording."""
    question = _extract_user_question(messages)
    canonical = _canonicalize(question)
    if not canonical:
        return ""
    return hashlib.sha256(f"semantic:{canonical}".encode("utf-8")).hexdigest()


# ── Cache read/write helpers ─────────────────────────────────────


def _get_cache():
    """Lazy-init the LLMCallCache singleton."""
    from .llm_cache import LLMCallCache

    if not hasattr(_get_cache, "_instance"):
        _get_cache._instance = LLMCallCache(Path("temp/llm_cache"))
    return _get_cache._instance


def try_get_cached(messages: list[dict] | str, model: str, tools: list[dict] | None = None) -> dict | None:
    """Check cache (exact hash first, then semantic). Returns cached value or None."""
    if not llm_cache_enabled():
        return None
    cache = _get_cache()
    exact_key = cache.make_key(model=model, messages=messages, tools=tools)
    result = cache.get(exact_key)
    if result is not None:
        return result
    semantic_key = make_semantic_hash(messages)
    if semantic_key:
        result = cache.get(semantic_key)
        if result is not None:
            return result
    return None


def store_cache(
    messages: list[dict] | str,
    model: str,
    response: str | dict,
    tools: list[dict] | None = None,
    metadata: dict | None = None,
) -> None:
    """Store LLM response in both exact and semantic cache slots."""
    if not llm_cache_enabled():
        return
    cache = _get_cache()
    value = {
        "response": response if isinstance(response, str) else str(response),
        "cached_at": time.time(),
        "model": model,
    }
    # Exact hash
    exact_key = cache.make_key(model=model, messages=messages, tools=tools)
    cache.set(exact_key, value)
    # Semantic hash
    semantic_key = make_semantic_hash(messages)
    if semantic_key:
        cache.set(semantic_key, value)


def get_cache_stats() -> dict:
    """Return cache hit/miss stats for profiler/audit."""
    if not hasattr(_get_cache, "_instance"):
        return {"enabled": False, "entries": 0}
    cache = _get_cache._instance
    try:
        entries = list(cache.entries_dir.glob("*.json"))
        return {
            "enabled": llm_cache_enabled(),
            "entries": len(entries),
            "dir": str(cache.cache_dir),
        }
    except Exception:
        return {"enabled": llm_cache_enabled(), "entries": -1}
