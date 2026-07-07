# Hotfix / Port-Back Ledger

This ledger records changes applied directly to the installed npm package. These changes are not complete until they are ported back to the source repository.

Runtime package path:

```text
C:\Users\Administrator\AppData\Roaming\npm\node_modules\gagent-desktop
```

## Active hotfixes to port back

### 1. Web search / browser tool convergence

Files changed:

```text
backend/core/ga.py
backend/core/runtime/web_tool_errors.py
backend/assets/tools_schema.json
backend/assets/tools_schema_cn.json
backend/memory/web_search_tool_sop.md
backend/tool_registry/tools/web_search.yml
backend/tool_registry/tools/web_scan.yml
backend/tool_registry/tools/web_execute_js.yml
backend/tool_registry/tools/browser_agent.yml
backend/tool_registry/policies/runtime_fallback.yml
backend/tool_registry/validate_tool_registry.py
backend/tool_registry/tests/smoke_web_tools.py
```

Reason:

```text
web_search, web_scan, web_execute_js, and browser_agent had blurred boundaries. Search failures could route into rendered browser tools, and browser state could pollute search results. The new contract separates HTTP source discovery from rendered page inspection.
```

Port-back target:

```text
Source repo packages/gagent-desktop and backend source snapshot that produces this npm package.
```

Verification:

```text
PYTHONUTF8=1 ./python-runtime/python.exe backend/tool_registry/validate_tool_registry.py
PYTHONUTF8=1 ./python-runtime/python.exe backend/tool_registry/tests/smoke_web_tools.py
```

Rollback:

```text
Revert the changed files listed above to the published package version, then restart gagent-desktop.
```

Status:

```text
runtime hotfix applied; source port-back required
```

---

### 2. Architecture convergence governance

Files changed:

```text
backend/memory/architecture_convergence_sop.md
backend/memory/development_workflow_sop.md
backend/memory/convergence_checklist.md
backend/quality_registry/gates.yml
backend/quality_registry/validate_quality_registry.py
backend/tool_registry/README.md
backend/quality_registry/README.md
```

Reason:

```text
The project needed an owner-layer model to prevent prompt/schema/SOP/runtime/tool implementation drift. Future changes must classify the owner layer before editing.
```

Port-back target:

```text
Source repo backend/memory, backend/tool_registry, backend/quality_registry.
```

Verification:

```text
PYTHONUTF8=1 ./python-runtime/python.exe backend/quality_registry/validate_quality_registry.py
PYTHONUTF8=1 ./python-runtime/python.exe backend/tool_registry/validate_tool_registry.py
```

Rollback:

```text
Remove the added governance files and restore prior quality defaults if needed.
```

Status:

```text
runtime governance files applied; source port-back required
```

---

### 3. Runtime ledger prototype

Files changed:

```text
backend/runtime_ledger/__init__.py
backend/runtime_ledger/ledger.py
backend/runtime_ledger/validate_runtime_ledger.py
backend/runtime_ledger/tests/smoke_runtime_ledger.py
backend/runtime_ledger/README.md
backend/memory/convergence_checklist.md
```

Reason:

```text
Mature Harness needs factual run trajectories before experience reuse, decision kernels, and capability acquisition can be reliable. Runtime Ledger records JSONL events for run_started, tool_call, tool_result, decision, smoke_test, and run_finished without relying on prompt obedience.
```

Port-back target:

```text
Source repo backend/runtime_ledger and backend/memory/convergence_checklist.md.
```

Verification:

```text
PYTHONUTF8=1 ./python-runtime/python.exe backend/runtime_ledger/validate_runtime_ledger.py
PYTHONUTF8=1 ./python-runtime/python.exe backend/runtime_ledger/tests/smoke_runtime_ledger.py
```

Rollback:

```text
Remove backend/runtime_ledger and revert backend/memory/convergence_checklist.md.
```

Status:

```text
runtime ledger prototype applied; not yet wired into ga.py/openai_agentmain.py; source port-back required
```

---

### Eval registry prototype

Files changed:

```text
backend/eval_registry/__init__.py
backend/eval_registry/README.md
backend/eval_registry/cases/web_search_openai_docs.json
backend/eval_registry/cases/web_search_yobot_github_failure.json
backend/eval_registry/cases/web_search_tool_boundary.json
backend/eval_registry/registry.py
backend/eval_registry/validate_eval_registry.py
backend/eval_registry/score_eval_result.py
backend/eval_registry/run_eval_cases.py
backend/eval_registry/tests/smoke_eval_registry.py
backend/memory/convergence_checklist.md
package.json
scripts/prepublish-check.cjs
.gitignore
```

Reason:

```text
Create the first internal evaluation harness for web_search tool behavior and runtime_ledger trajectory scoring without external benchmark platforms, LLM judges, PyYAML, CTest, or frontend changes.
```

Port-back target:

```text
Source repo backend/eval_registry, backend/memory/convergence_checklist.md, backend/memory/hotfix_portback_ledger.md, package.json, scripts/prepublish-check.cjs, and .gitignore.
```

Verification:

```text
PYTHONUTF8=1 ./python-runtime/python.exe backend/eval_registry/validate_eval_registry.py
PYTHONUTF8=1 ./python-runtime/python.exe backend/eval_registry/tests/smoke_eval_registry.py
```

Rollback:

```text
Remove backend/eval_registry, remove backend/eval_registry/results from .gitignore, and remove eval_registry commands from backend/memory/convergence_checklist.md.
```

Status:

```text
runtime eval registry prototype applied; source port-back required
```

---

### Web search eval hardening

Files changed:

```text
backend/core/ga.py
backend/core/runtime/web_tool_errors.py
backend/tool_registry/tools/web_search.yml
backend/tool_registry/tests/smoke_web_tools.py
backend/eval_registry/score_eval_result.py
backend/eval_registry/tests/smoke_eval_registry.py
backend/memory/convergence_checklist.md
```

Reason:

```text
Direct web_search failures must carry structured error_category/recovery fields, and eval scoring must reject polluted success URLs even when they are nested in tool result payloads.
```

Verification:

```text
PYTHONUTF8=1 ./python-runtime/python.exe backend/tool_registry/tests/smoke_web_tools.py
PYTHONUTF8=1 ./python-runtime/python.exe backend/eval_registry/tests/smoke_eval_registry.py
```

Rollback:

```text
Revert the listed files to the previous eval_registry/runtime_ledger commit.
```

Status:

```text
web_search failure classification and eval scorer hardening applied; source port-back required
```

---

### Web search auto GitHub routing

Files changed:

```text
backend/core/ga.py
backend/tool_registry/tools/web_search.yml
backend/tool_registry/tests/smoke_web_tools.py
backend/eval_registry/run_eval_cases.py
backend/eval_registry/tests/smoke_eval_registry.py
backend/memory/web_search_tool_sop.md
```

Reason:

```text
engine=auto GitHub queries should attempt GitHub API before generic HTTP search engines, and eval reports should expose attempt_engines so the failure chain is auditable.
```

Verification:

```text
PYTHONUTF8=1 ./python-runtime/python.exe backend/tool_registry/tests/smoke_web_tools.py
PYTHONUTF8=1 ./python-runtime/python.exe backend/eval_registry/tests/smoke_eval_registry.py
PYTHONUTF8=1 ./python-runtime/python.exe backend/eval_registry/run_eval_cases.py
```

Rollback:

```text
Revert the listed files to the previous web_search eval hardening commit.
```

Status:

```text
auto GitHub routing and eval attempt visibility applied; source port-back required
```

---

### Eval registry web boundary expansion

Files changed:

```text
backend/eval_registry/README.md
backend/eval_registry/cases/web_scan_current_tab_boundary.json
backend/eval_registry/cases/web_execute_js_navigation_boundary.json
backend/eval_registry/run_eval_cases.py
backend/eval_registry/score_eval_result.py
backend/eval_registry/tests/smoke_eval_registry.py
```

Reason:

```text
eval_registry should no longer score only web_search. It now executes deterministic offline boundary evals for web_scan and web_execute_js with runtime_ledger events and result-shape scoring.
```

Verification:

```text
PYTHONUTF8=1 ./python-runtime/python.exe backend/eval_registry/validate_eval_registry.py
PYTHONUTF8=1 ./python-runtime/python.exe backend/eval_registry/tests/smoke_eval_registry.py
PYTHONUTF8=1 ./python-runtime/python.exe backend/eval_registry/run_eval_cases.py
```

Rollback:

```text
Remove the two added eval cases and revert eval_registry runner/scorer/smoke changes.
```

Status:

```text
web_scan and web_execute_js boundary eval coverage applied; source port-back required
```

---

### Browser bridge handler ledger integration

Files changed:

```text
backend/core/ga.py
backend/eval_registry/README.md
backend/eval_registry/run_eval_cases.py
backend/eval_registry/tests/smoke_eval_registry.py
backend/runtime_ledger/README.md
```

Reason:

```text
web_scan and web_execute_js evals should exercise the real GenericAgentHandler methods and verify handler-level runtime_ledger events, instead of relying on eval harness event wrapping.
```

Verification:

```text
PYTHONUTF8=1 ./python-runtime/python.exe backend/eval_registry/tests/smoke_eval_registry.py
PYTHONUTF8=1 ./python-runtime/python.exe backend/eval_registry/run_eval_cases.py
```

Rollback:

```text
Revert handler ledger helpers and restore eval runner browser bridge event wrapping.
```

Status:

```text
web_scan and web_execute_js handler ledger integration applied; source port-back required
```

---

### Browser agent contract eval coverage

Files changed:

```text
backend/eval_registry/README.md
backend/eval_registry/cases/browser_agent_contract_boundary.json
backend/eval_registry/run_eval_cases.py
backend/eval_registry/score_eval_result.py
backend/eval_registry/tests/smoke_eval_registry.py
```

Reason:

```text
browser_agent should be represented in eval_registry without launching the expensive browser/LLM workflow. The contract eval verifies registry ownership and forbidden fallback language.
```

Verification:

```text
PYTHONUTF8=1 ./python-runtime/python.exe backend/eval_registry/validate_eval_registry.py
PYTHONUTF8=1 ./python-runtime/python.exe backend/eval_registry/tests/smoke_eval_registry.py
PYTHONUTF8=1 ./python-runtime/python.exe backend/eval_registry/run_eval_cases.py
```

Rollback:

```text
Remove backend/eval_registry/cases/browser_agent_contract_boundary.json and revert contract-runner/scorer changes.
```

Status:

```text
browser_agent contract eval coverage applied; executable browser-agent eval still intentionally not enabled
```

---

### Browser agent handler-stub eval coverage

Files changed:

```text
backend/core/ga.py
backend/eval_registry/README.md
backend/eval_registry/cases/browser_agent_handler_stub_boundary.json
backend/eval_registry/run_eval_cases.py
backend/eval_registry/score_eval_result.py
backend/eval_registry/tests/smoke_eval_registry.py
backend/runtime_ledger/README.md
```

Reason:

```text
browser_agent should have a handler-level eval path and runtime_ledger events without launching the real browser/LLM workflow. The harness stubs run_browser_agent and calls GenericAgentHandler.do_browser_agent.
```

Verification:

```text
PYTHONUTF8=1 ./python-runtime/python.exe backend/eval_registry/tests/smoke_eval_registry.py
PYTHONUTF8=1 ./python-runtime/python.exe backend/eval_registry/run_eval_cases.py
```

Rollback:

```text
Remove backend/eval_registry/cases/browser_agent_handler_stub_boundary.json and revert browser_agent handler ledger/scoring changes.
```

Status:

```text
browser_agent handler-stub eval and runtime_ledger coverage applied; real browser-agent workflow eval remains intentionally disabled
```

---

### Final answer scoring prototype

Files changed:

```text
backend/eval_registry/README.md
backend/eval_registry/score_final_answer.py
backend/eval_registry/run_eval_cases.py
backend/eval_registry/tests/smoke_eval_registry.py
```

Reason:

```text
The eval harness should not score only tool JSON and ledger events. It must also reject final-answer hallucinations such as reporting a successful finding when the tool result is a structured failure.
```

Verification:

```text
PYTHONUTF8=1 ./python-runtime/python.exe backend/eval_registry/tests/smoke_eval_registry.py
PYTHONUTF8=1 ./python-runtime/python.exe backend/eval_registry/run_eval_cases.py
```

Rollback:

```text
Remove backend/eval_registry/score_final_answer.py and revert the eval runner/smoke/README changes.
```

Status:

```text
rule-based final-answer scoring applied; source port-back required
```
