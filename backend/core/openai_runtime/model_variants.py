import importlib.util
import json
import os
from typing import Any

from .backend_config import (
    _describe_variant_backend,
    _infer_backend_kind,
    _normalize_model_identity,
    _normalize_openai_base_url,
    _normalized_backend_base_url,
    _normalized_url_host,
    _strip_url,
)

# Replicated constants (originally from openai_agentmain.py)
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SCRIPT_DIR = PROJECT_ROOT
CLAUDE_SETTINGS_PATH = os.path.expanduser(os.path.join("~", ".claude", "settings.json"))

def _load_json_file(path: str) -> dict[str, Any]:
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    return data if isinstance(data, dict) else {}


def _load_mykeys() -> dict[str, Any]:
    py_path = os.path.join(SCRIPT_DIR, "mykey.py")
    if os.path.exists(py_path):
        spec = importlib.util.spec_from_file_location("ga_mykey", py_path)
        if spec is None or spec.loader is None:
            raise RuntimeError("Unable to load mykey.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return {k: v for k, v in vars(module).items() if not k.startswith("_")}

    json_path = os.path.join(SCRIPT_DIR, "mykey.json")
    if os.path.exists(json_path):
        return _load_json_file(json_path)

    # Fall back to environment variables (preferred new approach)
    api_key = os.environ.get("GA_API_KEY", "").strip()
    if api_key:
        return {
            "native_oai_config": {
                "name": os.environ.get("GA_BACKEND_NAME", "env-configured"),
                "apikey": api_key,
                "apibase": os.environ.get("GA_API_BASE_URL", "https://api.deepseek.com").rstrip("/"),
                "model": os.environ.get("GA_MODEL", "deepseek-v4-pro"),
                "stream": os.environ.get("GA_STREAM", "true").lower() != "false",
                "max_retries": int(os.environ.get("GA_MAX_RETRIES", "3")),
                "connect_timeout": int(os.environ.get("GA_CONNECT_TIMEOUT", "10")),
                "read_timeout": int(os.environ.get("GA_READ_TIMEOUT", "120")),
            }
        }
    return {}


def _load_claude_settings() -> dict[str, Any]:
    return _load_json_file(CLAUDE_SETTINGS_PATH)

def _candidate_priority(variant: dict[str, Any]) -> tuple[int, int, int, str]:
    label = str(variant.get("label", "")).lower()
    backend_kind = variant.get("backend_kind")
    source = variant.get("source")
    return (
        0 if backend_kind == "native_claude" else 1,
        0 if source == "mykey.py" else 1,
        0 if "native" in label else 1,
        label,
    )


def _make_variant(
    *,
    label: str,
    backend_kind: str,
    api_key: str,
    base_url: str | None,
    model: str | None,
    source: str,
    stream: bool | None = None,
    connect_timeout: int | None = None,
    read_timeout: int | None = None,
) -> dict[str, Any] | None:
    if not api_key or not base_url or not model:
        return None
    normalized_base_url = (
        _strip_url(base_url)
        if backend_kind == "native_claude"
        else _normalize_openai_base_url(base_url)
    )
    if not normalized_base_url:
        return None
    variant = {
        "label": label,
        "backend_kind": backend_kind,
        "api_key": api_key,
        "base_url": normalized_base_url,
        "model": model,
        "source": source,
    }
    if stream is not None:
        variant["stream"] = stream
    if connect_timeout is not None:
        variant["connect_timeout"] = connect_timeout
    if read_timeout is not None:
        variant["read_timeout"] = read_timeout
    return variant


def _resolve_model_variants() -> list[dict[str, Any]]:
    variants: list[dict[str, Any]] = []

    for name, cfg in _load_mykeys().items():
        if not isinstance(cfg, dict):
            continue
        api_key = str(cfg.get("apikey") or "").strip()
        base_url = str(cfg.get("apibase") or "").strip()
        model = str(cfg.get("model") or cfg.get("name") or "").strip()
        backend_kind = _infer_backend_kind(name, base_url, model)
        if not backend_kind:
            continue
        variant = _make_variant(
            label=name,
            backend_kind=backend_kind,
            api_key=api_key,
            base_url=base_url,
            model=model,
            source="mykey.py",
            stream=cfg.get("stream"),
            connect_timeout=cfg.get("connect_timeout"),
            read_timeout=cfg.get("read_timeout"),
        )
        if variant:
            variants.append(variant)

    settings_env = _load_claude_settings().get("env", {})
    if isinstance(settings_env, dict):
        anthropic_variant = _make_variant(
            label="claude-settings/anthropic",
            backend_kind="native_claude",
            api_key=str(settings_env.get("ANTHROPIC_AUTH_TOKEN") or "").strip(),
            base_url=str(settings_env.get("ANTHROPIC_BASE_URL") or "").strip(),
            model=str(settings_env.get("ANTHROPIC_MODEL") or "").strip(),
            source="~/.claude/settings.json",
        )
        if anthropic_variant:
            variants.append(anthropic_variant)

        openai_variant = _make_variant(
            label="claude-settings/openai",
            backend_kind="native_oai",
            api_key=str(settings_env.get("OPENAI_API_KEY") or "").strip(),
            base_url=str(settings_env.get("OPENAI_BASE_URL") or "").strip(),
            model=str(settings_env.get("OPENAI_MODEL") or "").strip(),
            source="~/.claude/settings.json",
        )
        if openai_variant:
            variants.append(openai_variant)

    env_anthropic_variant = _make_variant(
        label="env/anthropic",
        backend_kind="native_claude",
        api_key=str(os.environ.get("ANTHROPIC_AUTH_TOKEN") or "").strip(),
        base_url=str(os.environ.get("ANTHROPIC_BASE_URL") or "").strip(),
        model=str(os.environ.get("ANTHROPIC_MODEL") or "").strip(),
        source="env",
    )
    if env_anthropic_variant:
        variants.append(env_anthropic_variant)

    env_openai_variant = _make_variant(
        label="env/openai",
        backend_kind="native_oai",
        api_key=str(os.environ.get("OPENAI_API_KEY") or "").strip(),
        base_url=str(os.environ.get("OPENAI_BASE_URL") or "").strip(),
        model=str(os.environ.get("OPENAI_MODEL") or "").strip(),
        source="env",
    )
    if env_openai_variant:
        variants.append(env_openai_variant)

    deduped: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str, str]] = set()
    for variant in sorted(variants, key=_candidate_priority):
        key = (
            str(variant["backend_kind"]),
            str(variant["api_key"]),
            str(variant["base_url"]),
            str(variant["model"]),
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(variant)
    return deduped



def _describe_classic_backend(llmclient: Any, index: int) -> dict[str, Any]:
    backend = getattr(llmclient, "backend", None)
    class_name = type(backend).__name__ if backend is not None else ""
    base_url = getattr(backend, "api_base", None)
    model = getattr(backend, "model", None)
    backend_name = getattr(backend, "name", None)
    backend_kind = (
        _infer_backend_kind(class_name, base_url, model)
        or _infer_backend_kind(str(backend_name or ""), base_url, model)
        or ""
    )
    return {
        "index": index,
        "backend_kind": backend_kind,
        "base_url": _normalized_backend_base_url(backend_kind, base_url),
        "host": _normalized_url_host(base_url),
        "model": _normalize_model_identity(model),
        "api_key": str(getattr(backend, "api_key", "") or "").strip(),
        "label": str(backend_name or "").strip().lower(),
    }


def _score_variant_to_classic_backend(variant: dict[str, Any], classic_info: dict[str, Any]) -> tuple[int, int, int, int, int, int]:
    variant_info = _describe_variant_backend(variant)
    same_kind = bool(variant_info["backend_kind"] and variant_info["backend_kind"] == classic_info["backend_kind"])
    same_model = bool(variant_info["model"] and variant_info["model"] == classic_info["model"])
    same_base = bool(variant_info["base_url"] and variant_info["base_url"] == classic_info["base_url"])
    same_host = bool(variant_info["host"] and variant_info["host"] == classic_info["host"])
    same_key = bool(variant_info["api_key"] and variant_info["api_key"] == classic_info["api_key"])
    source_is_mykey = variant_info["source"] == "mykey.py"

    score = 0
    if same_kind and same_base and same_model:
        score += 100
    elif same_base and same_model:
        score += 90
    elif same_model and same_host:
        score += 75
    elif same_model:
        score += 60
    elif same_host and same_kind:
        score += 45
    elif same_host:
        score += 35
    elif same_kind:
        score += 20
    if same_key:
        score += 5

    return (
        score,
        1 if same_kind else 0,
        1 if same_model else 0,
        1 if same_base else 0,
        1 if source_is_mykey else 0,
        -int(classic_info.get("index", 0)),
    )


def _looks_like_backend_unavailable(output: str) -> bool:
    text = str(output or "").strip().lower()
    if not text:
        return False
    patterns = (
        "no available channel for model",
        '"code":"model_not_found"',
        "model_not_found",
        "503 server error",
        "http 503",
        "service unavailable",
        "sslerror",
        "max retries exceeded",
        "connectionerror",
        "connection aborted",
        "read timed out",
        "temporarily unavailable",
        "unexpected eof while reading",
    )
    return any(pattern in text for pattern in patterns)
