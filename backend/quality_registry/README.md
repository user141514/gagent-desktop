# Quality Registry

Owner layer: Layer 4 quality gates.

`gates.yml` records gate defaults, triggers, injected role, owner, enforcement level, source files, and downstream artifacts. Runtime modules own implementation; this registry owns cross-gate visibility and release validation.

Run:

```text
python backend/quality_registry/validate_quality_registry.py
```
