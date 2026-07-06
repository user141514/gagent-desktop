"""
Model capability database — auto-detection of protocol, features, and limits.

Used by the session layer to adapt behavior based on the actual model in use.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# ── Known model profiles ───────────────────────────────────────────

@dataclass
class ModelProfile:
    model_family: str       # e.g. "claude-4", "deepseek-v4", "gpt-4"
    protocol: str           # "claude" or "openai"
    max_tokens: int         # output token limit
    context_window: int     # context window size
    supports_vision: bool = False
    supports_thinking: bool = False
    supports_extended_thinking: bool = False  # budget >= 32K tokens
    supports_prompt_caching: bool = False
    supports_tools: bool = True
    extra_headers: dict[str, str] = field(default_factory=dict)
    beta_features: list[str] = field(default_factory=list)
    notes: str = ""


# ── Known models ───────────────────────────────────────────────────

_MODEL_PROFILES: dict[str, ModelProfile] = {}

def _register(patterns: list[str], profile: ModelProfile) -> None:
    for p in patterns:
        _MODEL_PROFILES[p.lower()] = profile


# Claude family
_register(
    ["claude-4", "claude-4-5", "claude-opus-4", "claude-sonnet-4", "claude-haiku-4",
     "claude-4.5", "claude-opus-4-5", "claude-sonnet-4-5", "claude-haiku-4-5",
     "claude-3.5", "claude-3-5", "claude-3-opus", "claude-3-sonnet", "claude-3-haiku"],
    ModelProfile(
        model_family="claude",
        protocol="claude",
        max_tokens=8192,
        context_window=200000,
        supports_vision=True,
        supports_thinking=True,
        supports_extended_thinking=True,
        supports_prompt_caching=True,
        supports_tools=True,
        beta_features=["claude-code-20250219", "prompt-caching-scope-2026-01-05"],
        notes="Full Claude Messages API support",
    ),
)

# DeepSeek family (OpenAI-compatible Chat Completions endpoint)
_register(
    ["deepseek-v4", "deepseek-v4-pro", "deepseek-chat", "deepseek-reasoner",
     "deepseek-v3", "deepseek-r1"],
    ModelProfile(
        model_family="deepseek",
        protocol="openai",
        max_tokens=8192,
        context_window=128000,
        supports_thinking=True,
        supports_extended_thinking=False,
        supports_prompt_caching=False,
        supports_tools=True,
        notes="DeepSeek uses OpenAI-compatible /v1/chat/completions endpoints",
    ),
)

# GPT family
_register(
    ["gpt-4", "gpt-4o", "gpt-4-turbo", "gpt-4.1", "gpt-4o-mini",
     "gpt-3.5", "o1", "o3", "o4-mini", "o4"],
    ModelProfile(
        model_family="gpt",
        protocol="openai",
        max_tokens=16384,
        context_window=128000,
        supports_vision=True,
        supports_thinking=True,
        supports_extended_thinking=False,
        supports_prompt_caching=False,
        supports_tools=True,
        notes="OpenAI Chat Completions / Responses API",
    ),
)

# Generic fallbacks
_register(
    ["*"],
    ModelProfile(
        model_family="unknown",
        protocol="openai",
        max_tokens=4096,
        context_window=32000,
        supports_tools=True,
        notes="Unknown model — using OpenAI-compatible defaults",
    ),
)


# ── Model detection ────────────────────────────────────────────────

def detect_model_profile(model: str, base_url: str | None = None) -> ModelProfile:
    """Match a model name to a known profile, with fallback detection."""
    lmodel = (model or "").lower().strip()
    lbase = (base_url or "").lower().strip()

    # Exact/fuzzy match against known patterns
    for pattern, profile in _MODEL_PROFILES.items():
        if pattern == "*":
            continue
        pattern_lower = pattern.lower()
        # Fuzzy match: model name contains the pattern
        if pattern_lower in lmodel:
            return profile
        # Also check base_url for clues
        if lbase and pattern_lower in lbase:
            return profile

    # Heuristic detection from model name
    if any(t in lmodel for t in ("claude", "anthropic")):
        return ModelProfile(
            model_family="claude", protocol="claude",
            max_tokens=8192, context_window=200000,
            supports_thinking=True, supports_tools=True,
            notes="Heuristic: Claude-like model",
        )

    if "deepseek" in lmodel:
        return _MODEL_PROFILES.get(
            "deepseek-v4-pro",
            ModelProfile(
                model_family="deepseek", protocol="openai",
                max_tokens=8192, context_window=128000,
                supports_thinking=True, supports_tools=True,
                notes="Heuristic: DeepSeek model",
            ),
        )

    if any(t in lmodel for t in ("gpt", "openai", "o1", "o3", "o4")):
        return ModelProfile(
            model_family="gpt", protocol="openai",
            max_tokens=16384, context_window=128000,
            supports_tools=True,
            notes="Heuristic: GPT-like model",
        )

    # Check base_url for Claude indicators
    if lbase and any(t in lbase for t in ("anthropic", "/messages")):
        return ModelProfile(
            model_family="claude", protocol="claude",
            max_tokens=8192, context_window=200000,
            supports_tools=True, notes="Heuristic: Claude-like endpoint",
        )

    # Default fallback
    return _MODEL_PROFILES["*"]


def get_model_capabilities(model: str, base_url: str | None = None) -> dict[str, Any]:
    """Return a capability dict for the given model (convenience function)."""
    profile = detect_model_profile(model, base_url)
    return {
        "model_family": profile.model_family,
        "protocol": profile.protocol,
        "max_tokens": profile.max_tokens,
        "context_window": profile.context_window,
        "supports_vision": profile.supports_vision,
        "supports_thinking": profile.supports_thinking,
        "supports_extended_thinking": profile.supports_extended_thinking,
        "supports_prompt_caching": profile.supports_prompt_caching,
        "supports_tools": profile.supports_tools,
    }
