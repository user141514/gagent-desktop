from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Any

import requests


DEFAULT_PROVIDER = "deepseek"
DEFAULT_BASE_URL = "https://api.deepseek.com"
DEFAULT_MODEL = "deepseek-v4-pro"
KNOWN_DEEPSEEK_MODELS = [
    "deepseek-v4-pro",
    "deepseek-v4-flash",
]
CONFIG_FILENAME = "llm_config.json"
APP_CONFIG_DIR = "gagent-desktop"
LEGACY_WINDOWS_CONFIG_DIR = "GenericAgent"


def get_config_path() -> Path:
    override = os.getenv("GAGENT_DESKTOP_STATE_DIR") or os.getenv("GAGENT_CONFIG_DIR")
    if override:
        return Path(override).expanduser().resolve() / CONFIG_FILENAME
    if os.name == "nt":
        root = os.getenv("APPDATA") or str(Path.home() / "AppData" / "Roaming")
        return Path(root) / APP_CONFIG_DIR / CONFIG_FILENAME
    return Path.home() / ".config" / APP_CONFIG_DIR / CONFIG_FILENAME


def get_legacy_config_paths() -> list[Path]:
    if os.getenv("GAGENT_DESKTOP_STATE_DIR") or os.getenv("GAGENT_CONFIG_DIR"):
        return []
    if os.name == "nt":
        root = os.getenv("APPDATA") or str(Path.home() / "AppData" / "Roaming")
        return [Path(root) / LEGACY_WINDOWS_CONFIG_DIR / CONFIG_FILENAME]
    return [Path.home() / ".config" / "genericagent" / CONFIG_FILENAME]


def default_llm_config() -> dict[str, Any]:
    return {
        "provider": DEFAULT_PROVIDER,
        "api_key": "",
        "base_url": DEFAULT_BASE_URL,
        "model": DEFAULT_MODEL,
    }


def load_saved_llm_config() -> dict[str, Any]:
    config = default_llm_config()
    path = get_config_path()
    if not path.exists():
        _migrate_legacy_config(path)
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            data = {}
        if isinstance(data, dict):
            for key in ("provider", "api_key", "base_url", "model"):
                value = data.get(key)
                if isinstance(value, str):
                    config[key] = value.strip()
    return _normalize_config(config)


def _migrate_legacy_config(path: Path) -> None:
    for legacy_path in get_legacy_config_paths():
        if legacy_path == path or not legacy_path.exists():
            continue
        try:
            data = legacy_path.read_text(encoding="utf-8")
            json.loads(data)
        except (OSError, json.JSONDecodeError):
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(data, encoding="utf-8")
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
        return


def load_effective_llm_config() -> dict[str, Any]:
    config = load_saved_llm_config()
    if not config["api_key"]:
        env_key = os.getenv("GA_API_KEY", "").strip()
        if env_key:
            config["api_key"] = env_key
            config["source"] = "environment"
    if os.getenv("GA_API_BASE_URL"):
        config["base_url"] = os.getenv("GA_API_BASE_URL", "").strip().rstrip("/") or DEFAULT_BASE_URL
    if os.getenv("GA_MODEL"):
        config["model"] = os.getenv("GA_MODEL", "").strip() or DEFAULT_MODEL
    return _normalize_config(config)


def save_llm_config(patch: dict[str, Any]) -> dict[str, Any]:
    config = load_saved_llm_config()
    for key in ("provider", "base_url", "model"):
        if key in patch and isinstance(patch[key], str):
            config[key] = patch[key].strip()
    if "api_key" in patch and isinstance(patch["api_key"], str):
        next_key = patch["api_key"].strip()
        if next_key:
            config["api_key"] = next_key
    config = _normalize_config(config)

    path = get_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return config


def build_candidate_llm_config(patch: dict[str, Any] | None = None) -> dict[str, Any]:
    config = load_effective_llm_config()
    patch = patch or {}
    for key in ("provider", "base_url", "model"):
        if key in patch and isinstance(patch[key], str):
            config[key] = patch[key].strip()
    if "api_key" in patch and isinstance(patch["api_key"], str):
        next_key = patch["api_key"].strip()
        if next_key:
            config["api_key"] = next_key
    return _normalize_config(config)


def check_llm_config(patch: dict[str, Any] | None = None, *, probe_chat: bool = True) -> dict[str, Any]:
    config = build_candidate_llm_config(patch)
    api_key = str(config.get("api_key") or "").strip()
    model = str(config.get("model") or DEFAULT_MODEL).strip() or DEFAULT_MODEL
    base_url = normalize_openai_base_url(str(config.get("base_url") or DEFAULT_BASE_URL))
    started = time.perf_counter()
    result: dict[str, Any] = {
        "ok": False,
        "provider": config.get("provider") or DEFAULT_PROVIDER,
        "base_url_normalized": base_url,
        "models": [],
        "fallback_models": KNOWN_DEEPSEEK_MODELS,
        "selected_model": model,
        "selected_model_valid": False,
        "latency_ms": 0,
        "chat_probe_ok": False,
        "stage": "input",
        "message": "",
    }
    if not api_key:
        result["message"] = "API key is required before testing the connection."
        return _finish_check_result(result, started)

    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    try:
        models_response = requests.get(f"{base_url}/models", headers=headers, timeout=10)
    except requests.RequestException as exc:
        result["stage"] = "network"
        result["message"] = f"Network connection failed while requesting /models: {exc}"
        return _finish_check_result(result, started)

    if models_response.status_code in (401, 403):
        result["stage"] = "auth"
        result["status_code"] = models_response.status_code
        result["message"] = "API key was rejected by the provider."
        return _finish_check_result(result, started)

    models_supported = 200 <= models_response.status_code < 300
    if models_supported:
        models = _extract_model_ids(_safe_json(models_response))
        result["models"] = models
        result["selected_model_valid"] = model in models if models else False
    else:
        result["models"] = []
        result["selected_model_valid"] = model in KNOWN_DEEPSEEK_MODELS
        result["models_status_code"] = models_response.status_code

    if not probe_chat:
        result["ok"] = models_supported
        result["stage"] = "models"
        result["message"] = "Model list retrieved." if models_supported else "/models is not available."
        return _finish_check_result(result, started)

    try:
        chat_response = requests.post(
            f"{base_url}/chat/completions",
            headers=headers,
            json={
                "model": model,
                "messages": [{"role": "user", "content": "ping"}],
                "max_tokens": 1,
                "temperature": 0,
                "stream": False,
            },
            timeout=15,
        )
    except requests.RequestException as exc:
        result["stage"] = "network"
        result["message"] = f"Network connection failed while probing chat: {exc}"
        return _finish_check_result(result, started)

    result["chat_status_code"] = chat_response.status_code
    if 200 <= chat_response.status_code < 300:
        if not result["models"]:
            result["models"] = KNOWN_DEEPSEEK_MODELS
        result["ok"] = True
        result["chat_probe_ok"] = True
        result["selected_model_valid"] = True
        result["stage"] = "chat"
        result["message"] = "Connection verified."
        return _finish_check_result(result, started)

    if chat_response.status_code in (401, 403):
        result["stage"] = "auth"
        result["message"] = "API key was rejected by the provider."
    elif chat_response.status_code == 404:
        result["stage"] = "model"
        result["message"] = f"Model or chat endpoint was not found: {model}"
    else:
        result["stage"] = "chat"
        result["message"] = _provider_error_message(chat_response) or "Chat probe failed."
    return _finish_check_result(result, started)


def apply_llm_config_to_env(config: dict[str, Any] | None = None) -> dict[str, Any]:
    effective = _normalize_config(config or load_effective_llm_config())
    api_key = str(effective.get("api_key") or "").strip()
    if api_key:
        os.environ["GA_API_KEY"] = api_key
        os.environ["GA_KEY1_API_KEY"] = api_key
    os.environ["GA_BACKEND_NAME"] = str(effective.get("provider") or DEFAULT_PROVIDER)
    os.environ["GA_API_BASE_URL"] = str(effective.get("base_url") or DEFAULT_BASE_URL).rstrip("/")
    os.environ["GA_KEY1_API_BASE"] = os.environ["GA_API_BASE_URL"]
    os.environ["GA_MODEL"] = str(effective.get("model") or DEFAULT_MODEL)
    os.environ["GA_KEY1_MODEL"] = os.environ["GA_MODEL"]
    _clear_llmcore_config_cache()
    return effective


def normalize_openai_base_url(base_url: str) -> str:
    base = (base_url or DEFAULT_BASE_URL).strip().rstrip("/") or DEFAULT_BASE_URL
    if base.endswith("$"):
        base = base[:-1].rstrip("/")
    if "/v1" in base:
        return base
    return f"{base}/v1"


def public_llm_config(config: dict[str, Any] | None = None) -> dict[str, Any]:
    effective = load_effective_llm_config() if config is None else _normalize_config(config)
    api_key = str(effective.get("api_key") or "")
    return {
        "provider": effective.get("provider") or DEFAULT_PROVIDER,
        "base_url": effective.get("base_url") or DEFAULT_BASE_URL,
        "model": effective.get("model") or DEFAULT_MODEL,
        "api_key_masked": mask_api_key(api_key),
        "configured": bool(api_key),
        "source": effective.get("source") or ("local" if api_key else "unset"),
        "config_path": str(get_config_path()),
    }


def mask_api_key(api_key: str) -> str:
    value = (api_key or "").strip()
    if not value:
        return ""
    if len(value) <= 8:
        return "*" * len(value)
    return f"{value[:4]}...{value[-4:]}"


def _safe_json(response: requests.Response) -> dict[str, Any]:
    try:
        data = response.json()
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def _extract_model_ids(data: dict[str, Any]) -> list[str]:
    raw_models = data.get("data")
    if not isinstance(raw_models, list):
        return []
    model_ids = []
    for item in raw_models:
        if isinstance(item, dict) and isinstance(item.get("id"), str):
            model_ids.append(item["id"])
    return sorted(set(model_ids))


def _provider_error_message(response: requests.Response) -> str:
    data = _safe_json(response)
    error = data.get("error")
    if isinstance(error, dict):
        message = error.get("message")
        if isinstance(message, str):
            return message
    if isinstance(error, str):
        return error
    return ""


def _finish_check_result(result: dict[str, Any], started: float) -> dict[str, Any]:
    result["latency_ms"] = int((time.perf_counter() - started) * 1000)
    return result


def _normalize_config(config: dict[str, Any]) -> dict[str, Any]:
    normalized = default_llm_config()
    normalized.update({key: value for key, value in config.items() if isinstance(value, str)})
    normalized["provider"] = normalized["provider"].strip() or DEFAULT_PROVIDER
    normalized["api_key"] = normalized["api_key"].strip()
    normalized["base_url"] = (normalized["base_url"].strip() or DEFAULT_BASE_URL).rstrip("/")
    normalized["model"] = normalized["model"].strip() or DEFAULT_MODEL
    if "source" in config and isinstance(config["source"], str):
        normalized["source"] = config["source"]
    return normalized


def _clear_llmcore_config_cache() -> None:
    for module_name in ("core.llmcore", "llmcore"):
        module = sys.modules.get(module_name)
        if module is None:
            continue
        for attr in ("mykeys", "proxies"):
            if attr in getattr(module, "__dict__", {}):
                try:
                    delattr(module, attr)
                except AttributeError:
                    pass
