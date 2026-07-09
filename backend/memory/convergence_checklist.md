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
- eval registry validator rejects unsupported eval case `type` and `version`;
- eval registry loader rejects invalid top-level scalar types before coercion;
- eval registry loader rejects unknown top-level eval case fields;
- eval registry validator rejects unknown `input` fields for each `(type, target_tool)` contract;
- eval registry validator rejects missing required `input` fields for each `(type, target_tool)` contract;
- eval registry validator rejects invalid `input` field value types;
- eval registry loader rejects non-integer `score` values before coercion;
- eval registry validator rejects score weights that differ from the current 60/40 harness contract;
- eval registry validator rejects cases whose `expected_tools.allowed` does not include `target_tool`;
- eval registry validator rejects overlap between `expected_tools.allowed` and `expected_tools.forbidden`;
- eval registry validator rejects duplicate items in `expected_tools.allowed` and `expected_tools.forbidden`;
- eval registry validator rejects non-string items in `expected_tools.allowed` and `expected_tools.forbidden`;
- eval registry validator rejects `expected_tools.allowed` or `expected_tools.forbidden` entries missing from `backend/tool_registry/tools/*.yml`;
- eval registry validator rejects `expected_result` cases that allow neither success nor structured failure;
- eval registry validator rejects duplicate items in `expected_result.require_runtime_events` and `expected_result.require_contract_terms`;
- eval registry validator rejects non-list `expected_result.require_runtime_events` and `expected_result.require_contract_terms`;
- eval registry validator rejects non-string items in `expected_result.require_runtime_events` and `expected_result.require_contract_terms`;
- eval registry validator rejects non-boolean `expected_result` boolean switches;
- eval registry validator rejects tool-specific `expected_result` fields on mismatched target tools or case types;
- eval registry scoring rejects ledger `final_status` values that do not match `expected_result.require_final_status`;
- eval registry validator rejects unsupported RuntimeHost event names in `expected_result.require_runtime_events`;
- eval registry validator rejects `expected_result.require_balanced_turn_events` unless `require_runtime_events` includes both LLM turn events;
- eval registry validator rejects unsupported `expected_ledger.required_events` and `expected_ledger.required_on_failure` event names;
- eval registry validator rejects non-list `expected_ledger.required_on_failure` and `expected_ledger.required_decision_forbidden_actions`;
- eval registry validator rejects duplicate items in `expected_ledger.required_events`, `expected_ledger.required_on_failure`, and `expected_ledger.required_decision_forbidden_actions`;
- eval registry validator rejects non-string items in `expected_ledger.required_events`, `expected_ledger.required_on_failure`, and `expected_ledger.required_decision_forbidden_actions`;
- eval registry validator rejects `expected_ledger.required_decision_forbidden_actions` entries outside `expected_tools.forbidden`;
- eval registry validator rejects unknown `expected_tools`, `expected_ledger`, and `score` fields;
- eval registry validator rejects unknown `expected_result` fields;
- eval registry smoke exits 0;
- advisory functionality score reports optional e2e blockers instead of hiding them behind green internal evals;
- functionality score requires internal eval reports to cover every registry case id exactly once;
- functionality score rejects internal eval reports whose `results` field is not a list of objects;
- functionality score rejects internal eval result totals outside 0..100 and verdicts outside pass/fail/skip;
- functionality score rejects internal eval summary counts/status that do not match result verdicts;
- functionality score reports partial internal eval blockers when all cases pass but average score is below 100;
- baseline convergence runner validates and prints the advisory functionality score JSON, including refreshed/strict mode flags, expected component names/weights/status fields, total/max_total/status/blockers consistency, and required evidence fields, on success;
- baseline convergence runner rejects unknown fields in functionality score component objects;
- baseline convergence runner rejects unknown fields in functionality score evidence, e2e_env, source_git, input_reports, and input report objects;
- full convergence runner rejects strict functionality scores from dirty Git worktrees;
- functionality score component weights are defined in `score_functionality.py`; score max_total/status and the convergence runner use that same source;
- functionality score output schema field sets are defined in `score_functionality.py`; evidence generation and convergence validation reuse those constants;
- convergence runner score fixtures are generated from the shared component weights;
- full convergence runner includes baseline validators before strict functionality scoring;
- strict functionality score exits 0 only when optional real OpenAI/browser_agent e2e paths are explicitly enabled and pass;
- passed optional E2E score reports include run id, successful runtime_ledger evidence, and target-specific success evidence; OpenAI reports also include RuntimeHost observability alignment, and browser_agent reports include non-empty output plus positive step count;
- passed optional E2E score reports reject unknown top-level fields;
- passed optional E2E score reports reject unknown `ledger_summary` fields using `runtime_ledger.RUNTIME_LEDGER_SUMMARY_FIELDS` as the source of truth;
- skipped/failed optional E2E score reports reject unknown top-level fields;
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
- eval registry scoring rejects successful web_search results that lack a valid non-search-engine source URL;
- web_search failure must not recommend web_scan as ordinary fallback.
- final-answer scoring rejects forbidden fallback recommendations from eval case `expected_tools.forbidden`.
- agent-loop eval success scores the actual loop final answer and actual last tool result, not only synthesized harness wrappers.
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
- `backend/eval_registry/validate_eval_registry.py`
- `backend/eval_registry/score_final_answer.py`
- `backend/eval_registry/score_functionality.py`
- `backend/eval_registry/run_convergence_checks.py`
- `backend/requirements-e2e.txt`
