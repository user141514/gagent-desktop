"""Robust loader and alignment helpers for localized tool schemas."""

from __future__ import annotations

import copy
import json
import os
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[2]
ASSETS_DIR = PROJECT_ROOT / "assets"
EN_SCHEMA_PATH = ASSETS_DIR / "tools_schema.json"
ZH_SCHEMA_PATH = ASSETS_DIR / "tools_schema_cn.json"

_LANG_ALIASES = {
    "en": "en",
    "en-us": "en",
    "en_us": "en",
    "english": "en",
    "zh": "zh",
    "zh-cn": "zh",
    "zh_cn": "zh",
    "zh-hans": "zh",
    "zh_hans": "zh",
    "chinese": "zh",
}
_LEGACY_ZH_MODEL_HINTS = ("glm", "minimax", "kimi")


def _normalize_lang(lang: str | None) -> str:
    key = str(lang or "").strip().lower()
    return _LANG_ALIASES.get(key, "")


def _tool_name(tool: dict[str, Any]) -> str:
    fn = tool.get("function") or {}
    return str(fn.get("name") or tool.get("name") or "").strip()


def _param_props(tool: dict[str, Any]) -> dict[str, Any]:
    fn = tool.get("function") or {}
    params = fn.get("parameters") or {}
    props = params.get("properties") or {}
    return props if isinstance(props, dict) else {}


def _read_schema_json(path: Path, *, adapt_runtime_shell: bool) -> list[dict[str, Any]]:
    text = path.read_text(encoding="utf-8")
    if adapt_runtime_shell and os.name != "nt":
        text = text.replace("powershell", "bash")
    obj = json.loads(text)
    if not isinstance(obj, list):
        raise ValueError(f"tool schema must be a list: {path}")
    return obj


def resolve_tool_schema_lang(
    preferred_lang: str | None = None,
    llm_name: str | None = None,
) -> str:
    """Resolve runtime schema language with env override and legacy fallback."""

    for candidate in (
        os.environ.get("GA_TOOL_SCHEMA_LANG"),
        preferred_lang,
        os.environ.get("GA_LANG"),
    ):
        normalized = _normalize_lang(candidate)
        if normalized:
            return normalized

    model_name = str(llm_name or "").lower()
    if any(hint in model_name for hint in _LEGACY_ZH_MODEL_HINTS):
        return "zh"
    return "en"


def align_localized_schema(
    base_schema: list[dict[str, Any]],
    localized_schema: list[dict[str, Any]] | None,
    *,
    locale: str = "zh",
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Align a localized schema to the canonical English structure.

    English remains the source of truth for tool ordering, parameter sets,
    enums/defaults, and required fields. Localized descriptions override
    English only when present and non-empty.
    """

    localized_schema = localized_schema or []
    localized_by_name = {
        _tool_name(tool): tool
        for tool in localized_schema
        if isinstance(tool, dict) and _tool_name(tool)
    }
    base_names = [_tool_name(tool) for tool in base_schema if isinstance(tool, dict)]

    report: dict[str, Any] = {
        "locale": locale,
        "missing_tools": [],
        "extra_localized_tools": sorted(
            name for name in localized_by_name.keys() if name not in base_names
        ),
        "missing_tool_descriptions": [],
        "missing_param_descriptions": [],
        "used_localized_descriptions": [],
    }

    aligned: list[dict[str, Any]] = []
    for base_tool in base_schema:
        merged = copy.deepcopy(base_tool)
        name = _tool_name(merged)
        localized_tool = localized_by_name.get(name)
        localized_fn = (localized_tool or {}).get("function") or {}
        merged_fn = merged.get("function") or {}

        localized_desc = str(localized_fn.get("description") or "").strip()
        if localized_desc:
            merged_fn["description"] = localized_desc
            report["used_localized_descriptions"].append(name)
        else:
            report["missing_tool_descriptions"].append(name)
            if localized_tool is None:
                report["missing_tools"].append(name)

        localized_props = _param_props(localized_tool or {})
        merged_props = _param_props(merged)
        for prop_name, prop_schema in merged_props.items():
            localized_prop = localized_props.get(prop_name) or {}
            localized_prop_desc = str(localized_prop.get("description") or "").strip()
            if localized_prop_desc:
                prop_schema["description"] = localized_prop_desc
            else:
                report["missing_param_descriptions"].append(f"{name}.{prop_name}")

        aligned.append(merged)

    report["tool_count"] = len(aligned)
    return aligned, report


def load_runtime_tool_schema(
    preferred_lang: str | None = None,
    llm_name: str | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Load the runtime schema for the current language/model context."""

    lang = resolve_tool_schema_lang(preferred_lang=preferred_lang, llm_name=llm_name)
    base_schema = _read_schema_json(EN_SCHEMA_PATH, adapt_runtime_shell=True)
    if lang == "en":
        return base_schema, {
            "locale": "en",
            "source": str(EN_SCHEMA_PATH),
            "fallback_to_english": False,
            "missing_tools": [],
            "missing_tool_descriptions": [],
            "missing_param_descriptions": [],
            "extra_localized_tools": [],
            "tool_count": len(base_schema),
        }

    localized_path = ZH_SCHEMA_PATH
    if not localized_path.is_file():
        return base_schema, {
            "locale": lang,
            "source": str(EN_SCHEMA_PATH),
            "fallback_to_english": True,
            "missing_tools": [_tool_name(tool) for tool in base_schema],
            "missing_tool_descriptions": [_tool_name(tool) for tool in base_schema],
            "missing_param_descriptions": [],
            "extra_localized_tools": [],
            "tool_count": len(base_schema),
        }

    localized_schema = _read_schema_json(localized_path, adapt_runtime_shell=True)
    aligned, report = align_localized_schema(base_schema, localized_schema, locale=lang)
    report["source"] = str(localized_path)
    report["fallback_to_english"] = bool(
        report["missing_tools"]
        or report["missing_tool_descriptions"]
        or report["missing_param_descriptions"]
    )
    return aligned, report


def write_aligned_localized_schema(lang: str = "zh") -> dict[str, Any]:
    """Persist a structurally aligned localized schema back to disk."""

    normalized = _normalize_lang(lang)
    if normalized != "zh":
        raise ValueError(f"write_aligned_localized_schema only supports zh, got: {lang}")

    base_schema = _read_schema_json(EN_SCHEMA_PATH, adapt_runtime_shell=False)
    localized_schema = (
        _read_schema_json(ZH_SCHEMA_PATH, adapt_runtime_shell=False)
        if ZH_SCHEMA_PATH.is_file()
        else []
    )
    aligned, report = align_localized_schema(base_schema, localized_schema, locale="zh")
    ZH_SCHEMA_PATH.write_text(
        json.dumps(aligned, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    report["source"] = str(ZH_SCHEMA_PATH)
    report["persisted"] = True
    return report
