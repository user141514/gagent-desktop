"""Shadow validation for dynamic ``do_<tool_name>`` handlers."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import asdict, dataclass
from typing import Any

DEFAULT_INTERNAL_TOOLS = frozenset({"no_tool"})


@dataclass(frozen=True)
class ToolRegistryShadowReport:
    schema_tools: tuple[str, ...]
    handler_tools: tuple[str, ...]
    schema_without_handler: tuple[str, ...]
    handler_without_schema: tuple[str, ...]
    internal_handlers: tuple[str, ...]
    invalid_schema_entries: tuple[int, ...]

    @property
    def ok(self) -> bool:
        return not self.schema_without_handler and not self.invalid_schema_entries

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["ok"] = self.ok
        data["schema_tool_count"] = len(self.schema_tools)
        data["handler_tool_count"] = len(self.handler_tools)
        return data


def _tool_name(tool: Any) -> str:
    if not isinstance(tool, dict):
        return ""
    fn = tool.get("function") or {}
    if isinstance(fn, dict):
        name = fn.get("name")
        if name is not None:
            return str(name).strip()
    return str(tool.get("name") or "").strip()


def _sorted_unique(names: Iterable[str]) -> tuple[str, ...]:
    return tuple(sorted({str(name).strip() for name in names if str(name).strip()}))


def extract_schema_tool_names(tools_schema: Iterable[Any] | None) -> tuple[str, ...]:
    return _sorted_unique(_tool_name(tool) for tool in tools_schema or [])


def _invalid_schema_entries(tools_schema: Iterable[Any] | None) -> tuple[int, ...]:
    return tuple(
        index
        for index, tool in enumerate(tools_schema or [])
        if not _tool_name(tool)
    )


def discover_handler_tool_names(handler: Any) -> tuple[str, ...]:
    return _sorted_unique(
        attr[3:]
        for attr in dir(handler)
        if attr.startswith("do_") and callable(getattr(handler, attr, None))
    )


def validate_tool_registry_shadow(
    handler: Any,
    tools_schema: Iterable[Any] | None,
    *,
    internal_tools: Iterable[str] = DEFAULT_INTERNAL_TOOLS,
) -> ToolRegistryShadowReport:
    schema_tools = extract_schema_tool_names(tools_schema)
    handler_tools = discover_handler_tool_names(handler)
    internal_tool_set = set(internal_tools)
    internal = _sorted_unique(name for name in handler_tools if name in internal_tool_set)
    public_handlers = tuple(name for name in handler_tools if name not in internal_tool_set)
    schema_set = set(schema_tools)
    public_handler_set = set(public_handlers)

    return ToolRegistryShadowReport(
        schema_tools=schema_tools,
        handler_tools=handler_tools,
        schema_without_handler=tuple(name for name in schema_tools if name not in public_handler_set),
        handler_without_schema=tuple(name for name in public_handlers if name not in schema_set),
        internal_handlers=internal,
        invalid_schema_entries=_invalid_schema_entries(tools_schema),
    )


__all__ = [
    "DEFAULT_INTERNAL_TOOLS",
    "ToolRegistryShadowReport",
    "discover_handler_tool_names",
    "extract_schema_tool_names",
    "validate_tool_registry_shadow",
]
