# Tool Registry

Owner layer: Layer 1 capability contract.

`tools/*.yml` is the source of truth for public tool capability boundaries:

- purpose and explicit non-purpose;
- inputs and outputs;
- success and failure contracts;
- fallback policy;
- forbidden behaviors;
- smoke tests;
- source files and generated artifacts.

Downstream schema, SOP, and prompt text may summarize these contracts, but must not invent separate tool behavior.

Run:

```text
python backend/tool_registry/validate_tool_registry.py
python backend/tool_registry/tests/smoke_web_tools.py
```
