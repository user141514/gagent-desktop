from __future__ import annotations

import os
from typing import Any
from urllib.parse import urlparse


def _strip_url(url: str | None) -> str | None:
    if not url:
        return None
    return str(url).rstrip("/")


def _normalize_openai_base_url(base_url: str | None) -> str | None:
    stripped = _strip_url(base_url)
    if not stripped:
        return None
    if "/v1" not in stripped:
        return f"{stripped}/v1"
    return stripped


def _infer_backend_kind(name: str, base_url: str | None, model: str | None) -> str | None:
    """Infer the backend protocol from configuration metadata.

    Priority (highest to lowest):
      1. Explicit `native_oai` / `native_claude` in the config key name
      2. Base URL structure (anthropic endpoint vs openai endpoint)
      3. Model name keywords with base URL context
      4. Protocol override via GA_PROTOCOL env var
    """
    lname = name.lower()
    lbase = (base_url or "").lower()
    lmodel = (model or "").lower()

    # -- Explicit backend type in config key name (highest priority) --
    if "native_claude" in lname:
        return "native_claude"
    if "native_oai" in lname:
        return "native_oai"

    # -- Backward-compatible name heuristics --
    # "native" + "claude" anywhere -> native_claude
    if "native" in lname and "claude" in lname:
        return "native_claude"
    if "native" in lname and ("oai" in lname or "openai" in lname or "gpt" in lname):
        return "native_oai"
    # Legacy: just "claude" in name -> native_claude
    if any(token in lname for token in ("claude", "anthropic")):
        return "native_claude"
    # Legacy: just "openai" / "oai" / "gpt" in name -> native_oai
    if any(token in lname for token in ("oai", "openai", "gpt")):
        return "native_oai"

    # -- Base URL indicates protocol --
    if any(token in lbase for token in ("anthropic", "/messages")):
        return "native_claude"
    if any(token in lbase for token in ("/v1", "chat/completions", "responses", "openai")):
        # OpenAI-compatible endpoint -> check model to decide
        if any(token in lmodel for token in ("claude-", "claude3", "claude4", "anthropic")):
            # Claude model on OpenAI-compatible proxy -> native_oai (uses OAI protocol)
            return "native_oai"
        return "native_oai"

    # -- Model name with no base URL context --
    if any(token in lmodel for token in ("claude-", "claude3", "claude4", "anthropic")):
        # Unknown base URL but Claude model -- could be either protocol
        # Default to native_oai (more widely supported by proxies)
        if lbase and not any(t in lbase for t in ("anthropic", "messages", "openai", "v1")):
            return "native_oai"
        return "native_claude"

    if any(token in lmodel for token in ("deepseek",)):
        return "native_oai"
    if any(token in lmodel for token in ("gpt-", "o1", "o3", "o4")):
        return "native_oai"

    # -- Protocol override via environment --
    protocol_override = os.environ.get("GA_PROTOCOL", "").strip().lower()
    if protocol_override == "claude":
        return "native_claude"
    if protocol_override == "openai":
        return "native_oai"

    # -- Fallback --
    if lbase and any(t in lbase for t in ("claude", "api.anthropic")):
        return "native_claude"

    return None


def _normalize_model_identity(model: str | None) -> str:
    text = str(model or "").strip().lower()
    if not text:
        return ""
    return text.replace("[1m]", "").strip()


def _normalized_backend_base_url(backend_kind: str | None, base_url: str | None) -> str:
    kind = str(backend_kind or "").strip().lower()
    if kind == "native_oai":
        return str(_normalize_openai_base_url(base_url) or "").strip().lower()
    return str(_strip_url(base_url) or "").strip().lower()


def _normalized_url_host(base_url: str | None) -> str:
    normalized = str(_strip_url(base_url) or "").strip()
    if not normalized:
        return ""
    parsed = urlparse(normalized)
    if parsed.netloc:
        return parsed.netloc.lower()
    if "://" in normalized:
        normalized = normalized.split("://", 1)[1]
    return normalized.split("/", 1)[0].lower()


def _describe_variant_backend(variant: dict[str, Any]) -> dict[str, Any]:
    backend_kind = str(variant.get("backend_kind") or "").strip().lower()
    base_url = variant.get("base_url")
    return {
        "backend_kind": backend_kind,
        "base_url": _normalized_backend_base_url(backend_kind, base_url),
        "host": _normalized_url_host(base_url),
        "model": _normalize_model_identity(variant.get("model")),
        "api_key": str(variant.get("api_key") or "").strip(),
        "source": str(variant.get("source") or "").strip().lower(),
        "label": str(variant.get("label") or "").strip().lower(),
    }