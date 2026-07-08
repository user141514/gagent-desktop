# Convergence Check Entry

Run this baseline gate before claiming a non-trivial change is complete:

```text
PYTHONUTF8=1 ./python-runtime/python.exe backend/eval_registry/run_convergence_checks.py
npm.cmd run test:convergence
```

It executes:

```text
PYTHONUTF8=1 ./python-runtime/python.exe backend/tool_registry/validate_tool_registry.py
PYTHONUTF8=1 ./python-runtime/python.exe backend/quality_registry/validate_quality_registry.py
PYTHONUTF8=1 ./python-runtime/python.exe backend/tool_registry/tests/smoke_web_tools.py
PYTHONUTF8=1 ./python-runtime/python.exe backend/eval_registry/validate_eval_registry.py
PYTHONUTF8=1 ./python-runtime/python.exe backend/eval_registry/tests/smoke_eval_registry.py
PYTHONUTF8=1 ./python-runtime/python.exe backend/eval_registry/score_functionality.py --refresh
PYTHONUTF8=1 ./python-runtime/python.exe backend/runtime_ledger/validate_runtime_ledger.py
PYTHONUTF8=1 ./python-runtime/python.exe backend/runtime_ledger/tests/smoke_runtime_ledger.py
```

Full-flow completion gate:

```text
PYTHONUTF8=1 ./python-runtime/python.exe -m pip install --target backend/temp/e2e_deps -r backend/requirements-e2e.txt
PYTHONUTF8=1 ./python-runtime/python.exe backend/eval_registry/tests/smoke_openai_orchestrated_e2e.py
GAGENT_E2E_DEPS=backend/temp/e2e_deps GAGENT_RUN_OPENAI_E2E=1 PYTHONUTF8=1 ./python-runtime/python.exe backend/eval_registry/tests/smoke_openai_orchestrated_e2e.py
PYTHONUTF8=1 ./python-runtime/python.exe backend/eval_registry/tests/smoke_browser_agent_e2e.py
GAGENT_E2E_DEPS=backend/temp/e2e_deps GAGENT_RUN_BROWSER_AGENT_E2E=1 PYTHONUTF8=1 ./python-runtime/python.exe backend/eval_registry/tests/smoke_browser_agent_e2e.py
GAGENT_E2E_DEPS=backend/temp/e2e_deps GAGENT_RUN_OPENAI_E2E=1 GAGENT_RUN_BROWSER_AGENT_E2E=1 PYTHONUTF8=1 ./python-runtime/python.exe backend/eval_registry/run_convergence_checks.py --full
GAGENT_E2E_DEPS=backend/temp/e2e_deps GAGENT_RUN_OPENAI_E2E=1 GAGENT_RUN_BROWSER_AGENT_E2E=1 npm.cmd run test:convergence:full
```

Pass criteria:

- tool registry validator exits 0;
- quality registry validator exits 0;
- web tool smoke exits 0;
- eval registry validator exits 0;
- eval registry smoke exits 0;
- advisory functionality score reports optional e2e blockers instead of hiding them behind green internal evals;
- baseline convergence runner validates and prints the advisory functionality score JSON, including expected component names/weights, total/max_total/status/blockers consistency, and required evidence fields, on success;
- functionality score component weights are defined in `score_functionality.py`; score max_total/status and the convergence runner use that same source;
- full convergence runner includes baseline validators before strict functionality scoring;
- strict functionality score exits 0 only when optional real OpenAI/browser_agent e2e paths are explicitly enabled and pass;
- refreshed functionality score success output stays machine-readable as one JSON report; child stdout/stderr appears only on refresh failure;
- functionality score self-test verifies refresh child failure captures stdout/stderr locally;
- functionality score self-test verifies strict/non-strict CLI exit behavior with isolated `--results-dir` fixtures;
- functionality score self-test verifies skipped optional e2e paths cannot pass strict completion;
- functionality score self-test rejects the ambiguous `--refresh --results-dir` combination;
- functionality score self-test rejects isolated `--results-dir` scoring unless `--no-write` is set;
- functionality score output includes non-secret evidence for input report files, Git HEAD/dirty state, Python executable, results directory, and E2E switches;
- runtime ledger validator exits 0;
- runtime ledger smoke exits 0;
- smoke output may classify real network/search-backend failures as structured non-logic failures, but must not classify polluted results as success;
- no search-engine homepage may be returned as a successful web_search source;
- web_search failure must not recommend web_scan as ordinary fallback.
- OpenAI orchestrated e2e smoke may skip by default, but must fail when explicitly enabled and the real SDK/config/runtime path cannot complete.
- browser_agent e2e smoke may skip by default, but must fail when explicitly enabled and browser-use/Playwright/LLM runtime cannot complete.
- optional real e2e dependencies live in `backend/requirements-e2e.txt`; `GAGENT_E2E_DEPS` must point at the installed target because packaged Python ignores `PYTHONPATH`.
- browser_agent must not report success when the underlying browser-use run has no final result.
- DeepSeek thinking variants must use a browser-use-compatible chat model for browser_agent structured tool calls.
- OpenAI E2E success/skip output must not be polluted by Classic GenericAgent init tracebacks.

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
- `backend/eval_registry/run_convergence_checks.py`
- `backend/requirements-e2e.txt`
