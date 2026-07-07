# Convergence Check Entry

Run these checks before claiming a non-trivial change is complete:

```text
PYTHONUTF8=1 ./python-runtime/python.exe backend/tool_registry/validate_tool_registry.py
PYTHONUTF8=1 ./python-runtime/python.exe backend/quality_registry/validate_quality_registry.py
PYTHONUTF8=1 ./python-runtime/python.exe backend/tool_registry/tests/smoke_web_tools.py
PYTHONUTF8=1 ./python-runtime/python.exe backend/eval_registry/validate_eval_registry.py
PYTHONUTF8=1 ./python-runtime/python.exe backend/eval_registry/tests/smoke_eval_registry.py
PYTHONUTF8=1 ./python-runtime/python.exe backend/eval_registry/score_functionality.py
PYTHONUTF8=1 ./python-runtime/python.exe backend/runtime_ledger/validate_runtime_ledger.py
PYTHONUTF8=1 ./python-runtime/python.exe backend/runtime_ledger/tests/smoke_runtime_ledger.py
```

Optional full-flow checks:

```text
PYTHONUTF8=1 ./python-runtime/python.exe backend/eval_registry/tests/smoke_openai_orchestrated_e2e.py
GAGENT_RUN_OPENAI_E2E=1 PYTHONUTF8=1 ./python-runtime/python.exe backend/eval_registry/tests/smoke_openai_orchestrated_e2e.py
PYTHONUTF8=1 ./python-runtime/python.exe backend/eval_registry/tests/smoke_browser_agent_e2e.py
GAGENT_RUN_BROWSER_AGENT_E2E=1 PYTHONUTF8=1 ./python-runtime/python.exe backend/eval_registry/tests/smoke_browser_agent_e2e.py
```

Pass criteria:

- tool registry validator exits 0;
- quality registry validator exits 0;
- web tool smoke exits 0;
- eval registry validator exits 0;
- eval registry smoke exits 0;
- functionality score exits 0 and reports optional e2e blockers instead of hiding them behind green internal evals;
- runtime ledger validator exits 0;
- runtime ledger smoke exits 0;
- smoke output may classify real network/search-backend failures as structured non-logic failures, but must not classify polluted results as success;
- no search-engine homepage may be returned as a successful web_search source;
- web_search failure must not recommend web_scan as ordinary fallback.
- OpenAI orchestrated e2e smoke may skip by default, but must fail when explicitly enabled and the real SDK/config/runtime path cannot complete.
- browser_agent e2e smoke may skip by default, but must fail when explicitly enabled and browser-use/Playwright/LLM runtime cannot complete.

This file is an operational checklist, not a source of truth. The source of truth remains:

- `backend/memory/architecture_convergence_sop.md`
- `backend/memory/development_workflow_sop.md`
- `backend/tool_registry/tools/*.yml`
- `backend/quality_registry/gates.yml`
- `backend/runtime_ledger/ledger.py`
- `backend/runtime_ledger/observability.py`
- `backend/eval_registry/cases/*.json`
- `backend/eval_registry/tests/smoke_openai_orchestrated_e2e.py`
- `backend/eval_registry/tests/smoke_browser_agent_e2e.py`
- `backend/eval_registry/score_functionality.py`
