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

---

### Agent-loop runtime mapper eval

Files changed:

```text
backend/core/agent_loop.py
backend/eval_registry/README.md
backend/eval_registry/cases/agent_loop_runtime_mapper_web_search.json
backend/eval_registry/run_eval_cases.py
backend/eval_registry/score_eval_result.py
backend/eval_registry/tests/smoke_eval_registry.py
```

Reason:

```text
eval_registry needed at least one deterministic agent-loop-level check, not only direct tool handler checks. The new case exercises agent_runner_loop with a fake LLM and fake web_search handler, verifies RuntimeEventMapper turn/tool events, and catches unbalanced final-turn llm_call_started/llm_call_completed events.
```

Verification:

```text
PYTHONUTF8=1 ./python-runtime/python.exe backend/eval_registry/tests/smoke_eval_registry.py
PYTHONUTF8=1 ./python-runtime/python.exe backend/eval_registry/run_eval_cases.py
```

Rollback:

```text
Remove backend/eval_registry/cases/agent_loop_runtime_mapper_web_search.json, revert the eval runner/scorer/smoke/README changes, and revert the agent_loop.py turn_end emission fix.
```

Status:

```text
agent-loop runtime mapper eval applied; source port-back required
```

---

### Agent-loop runtime ledger opt-in

Files changed:

```text
backend/core/agent_loop.py
backend/eval_registry/README.md
backend/eval_registry/run_eval_cases.py
backend/eval_registry/tests/smoke_eval_registry.py
backend/runtime_ledger/README.md
```

Reason:

```text
The agent-loop eval previously relied on eval-runner wrapper events for runtime_ledger scoring. agent_runner_loop now has an opt-in runtime_ledger_run_id path that emits run_started, turn-tagged tool_call/tool_result, and run_finished directly from the loop.
```

Verification:

```text
PYTHONUTF8=1 ./python-runtime/python.exe backend/eval_registry/tests/smoke_eval_registry.py
PYTHONUTF8=1 ./python-runtime/python.exe backend/eval_registry/run_eval_cases.py
PYTHONUTF8=1 ./python-runtime/python.exe backend/runtime_ledger/tests/smoke_runtime_ledger.py
```

Rollback:

```text
Remove the runtime_ledger_run_id parameter and nested writer from backend/core/agent_loop.py, then restore eval runner wrapper ledger events for agent_loop_runtime_mapper_web_search.
```

Status:

```text
agent-loop runtime_ledger opt-in applied; source port-back required
```

---

### Classic agentmain runtime ledger wiring

Files changed:

```text
backend/core/agentmain.py
backend/runtime_ledger/README.md
backend/runtime_ledger/tests/smoke_runtime_ledger.py
```

Reason:

```text
agent_runner_loop supported runtime_ledger_run_id, but the classic agentmain entrypoint did not pass its task run_id. Normal classic-agent runs now write runtime_ledger events without relying on eval-only wiring.
```

Verification:

```text
PYTHONUTF8=1 ./python-runtime/python.exe backend/runtime_ledger/tests/smoke_runtime_ledger.py
PYTHONUTF8=1 ./python-runtime/python.exe backend/eval_registry/tests/smoke_eval_registry.py
```

Rollback:

```text
Remove runtime_ledger_run_id=run_id from backend/core/agentmain.py and remove the smoke assertion.
```

Status:

```text
classic agentmain runtime_ledger wiring applied; source port-back required
```

---

### OpenAI orchestrated runtime ledger wiring

Files changed:

```text
backend/core/openai_agentmain.py
backend/runtime_ledger/README.md
backend/runtime_ledger/tests/smoke_runtime_ledger.py
```

Reason:

```text
The OpenAI orchestrated agent had RuntimeHost/profiler tracking but did not emit runtime_ledger JSONL events. It now writes run_started, streamed tool_call/tool_result, and run_finished under the existing profile run_id.
```

Verification:

```text
PYTHONUTF8=1 ./python-runtime/python.exe backend/runtime_ledger/tests/smoke_runtime_ledger.py
PYTHONUTF8=1 ./python-runtime/python.exe -m py_compile backend/core/openai_agentmain.py
```

Rollback:

```text
Remove OpenAIOrchestratedAgent._write_runtime_ledger_event and the run/tool/final calls in backend/core/openai_agentmain.py, then remove the smoke markers.
```

Status:

```text
OpenAI orchestrated runtime_ledger wiring applied; source port-back required
```

---

### OpenAI runtime ledger helper smoke

Files changed:

```text
backend/runtime_ledger/README.md
backend/runtime_ledger/tests/smoke_runtime_ledger.py
```

Reason:

```text
The OpenAI orchestrated runtime_ledger smoke previously checked source markers only. It now instantiates OpenAIOrchestratedAgent without running the SDK loop, calls the runtime_ledger helper, and verifies the JSONL events can be read and summarized.
```

Verification:

```text
PYTHONUTF8=1 ./python-runtime/python.exe backend/runtime_ledger/tests/smoke_runtime_ledger.py
```

Rollback:

```text
Remove _assert_openai_helper_writes_runtime_ledger from backend/runtime_ledger/tests/smoke_runtime_ledger.py and remove the README note.
```

Status:

```text
OpenAI runtime_ledger helper smoke applied; source port-back required
```

---

### Runtime observability join

Files changed:

```text
backend/runtime_ledger/observability.py
backend/runtime_ledger/__init__.py
backend/runtime_ledger/README.md
backend/runtime_ledger/tests/smoke_runtime_ledger.py
backend/eval_registry/run_eval_cases.py
backend/eval_registry/tests/smoke_eval_registry.py
backend/eval_registry/README.md
```

Reason:

```text
RuntimeHost events and runtime_ledger events were recorded in parallel but had no shared read view. runtime_ledger now exposes a read-only summarize_observability() helper that joins both trajectories for one run id, and eval reports include it for the agent-loop runtime mapper case.
```

Verification:

```text
PYTHONUTF8=1 ./python-runtime/python.exe backend/runtime_ledger/tests/smoke_runtime_ledger.py
PYTHONUTF8=1 ./python-runtime/python.exe backend/eval_registry/tests/smoke_eval_registry.py
PYTHONUTF8=1 ./python-runtime/python.exe backend/eval_registry/run_eval_cases.py
```

Rollback:

```text
Remove backend/runtime_ledger/observability.py, its __init__.py exports, the smoke assertions, and the eval report observability field.
```

Status:

```text
runtime observability join applied; source port-back required
```

---

### Agent-loop structured failure eval

Files changed:

```text
backend/core/agent_loop.py
backend/eval_registry/cases/agent_loop_runtime_mapper_web_search_failure.json
backend/eval_registry/run_eval_cases.py
backend/eval_registry/tests/smoke_eval_registry.py
backend/eval_registry/README.md
backend/runtime_ledger/README.md
```

Reason:

```text
agent_loop runtime mapper eval covered only the success path. The eval registry now runs a deterministic structured web_search failure through the real agent_runner_loop, verifies a runtime_ledger decision, and requires run_finished.final_status=structured_failure.
```

Verification:

```text
PYTHONUTF8=1 ./python-runtime/python.exe backend/eval_registry/tests/smoke_eval_registry.py
PYTHONUTF8=1 ./python-runtime/python.exe backend/eval_registry/run_eval_cases.py
```

Rollback:

```text
Remove the new eval case, remove force_error handling from the fake eval handler, restore agent_loop final_status to success/max_turns only, and remove the smoke assertions.
```

Status:

```text
agent-loop structured failure eval applied; source port-back required
```

---

### OpenAI orchestrated optional e2e smoke

Files changed:

```text
backend/eval_registry/tests/smoke_openai_orchestrated_e2e.py
backend/eval_registry/README.md
backend/memory/convergence_checklist.md
```

Reason:

```text
OpenAI orchestrated runtime_ledger coverage had helper-level smoke but no runnable full SDK path. The eval registry now has an opt-in e2e smoke that structured-skips by default and, when GAGENT_RUN_OPENAI_E2E=1 is set, starts OpenAIOrchestratedAgent, submits a run_id-tagged task, and verifies runtime_ledger run_started/run_finished.
The smoke writes latest_openai_e2e_report.json as an ignored runtime artifact so readiness/runtime failures are preserved as machine-readable evidence.
```

Verification:

```text
PYTHONUTF8=1 ./python-runtime/python.exe backend/eval_registry/tests/smoke_openai_orchestrated_e2e.py
```

Rollback:

```text
Remove backend/eval_registry/tests/smoke_openai_orchestrated_e2e.py and remove the optional check references from README and convergence_checklist.md.
```

Status:

```text
OpenAI orchestrated optional e2e smoke applied; source port-back required
```

---

### Browser agent optional e2e smoke

Files changed:

```text
backend/eval_registry/tests/smoke_browser_agent_e2e.py
backend/eval_registry/README.md
backend/memory/convergence_checklist.md
```

Reason:

```text
browser_agent coverage had registry contract and stubbed handler evals but no runnable full browser/LLM path. The eval registry now has an opt-in e2e smoke that structured-skips by default and, when GAGENT_RUN_BROWSER_AGENT_E2E=1 is set, calls GenericAgentHandler.do_browser_agent with a run_id and writes latest_browser_agent_e2e_report.json.
```

Verification:

```text
PYTHONUTF8=1 ./python-runtime/python.exe backend/eval_registry/tests/smoke_browser_agent_e2e.py
```

Rollback:

```text
Remove backend/eval_registry/tests/smoke_browser_agent_e2e.py and remove the optional check references from README and convergence_checklist.md.
```

Status:

```text
browser_agent optional e2e smoke applied; source port-back required
```

---

### Functionality score report

Files changed:

```text
backend/eval_registry/score_functionality.py
backend/eval_registry/README.md
backend/memory/convergence_checklist.md
backend/memory/hotfix_portback_ledger.md
```

Reason:

```text
Internal eval reports can pass while optional real OpenAI/browser_agent e2e paths are still readiness failures. The eval registry now has a small stdlib-only score_functionality.py entrypoint that combines latest_eval_report.json, latest_openai_e2e_report.json, and latest_browser_agent_e2e_report.json into latest_functionality_score.json.
```

Verification:

```text
PYTHONUTF8=1 ./python-runtime/python.exe backend/eval_registry/score_functionality.py --self-test
PYTHONUTF8=1 ./python-runtime/python.exe backend/eval_registry/score_functionality.py
```

Rollback:

```text
Remove backend/eval_registry/score_functionality.py and remove score_functionality.py references from README and convergence_checklist.md.
```

Status:

```text
functionality score report applied; source port-back required
```

---

### Optional E2E dependency manifest

Files changed:

```text
backend/requirements-e2e.txt
backend/eval_registry/tests/smoke_openai_orchestrated_e2e.py
backend/eval_registry/tests/smoke_browser_agent_e2e.py
backend/eval_registry/score_functionality.py
backend/eval_registry/README.md
backend/memory/convergence_checklist.md
backend/memory/hotfix_portback_ledger.md
```

Reason:

```text
The strict functionality score is blocked by missing openai-agents/browser-use/Playwright dependencies. Packaged Windows Python uses python313._pth and ignores PYTHONPATH, so opt-in e2e smoke tests now support an explicit GAGENT_E2E_DEPS target directory and the optional dependency list lives in backend/requirements-e2e.txt.
```

Verification:

```text
PYTHONUTF8=1 ./python-runtime/python.exe backend/eval_registry/score_functionality.py --self-test
PYTHONUTF8=1 ./python-runtime/python.exe backend/eval_registry/tests/smoke_openai_orchestrated_e2e.py
PYTHONUTF8=1 ./python-runtime/python.exe backend/eval_registry/tests/smoke_browser_agent_e2e.py
```

Rollback:

```text
Remove backend/requirements-e2e.txt and remove GAGENT_E2E_DEPS path injection from the two optional e2e smoke scripts.
```

Status:

```text
optional e2e dependency manifest applied; source port-back required
```

---

### Optional E2E readiness advancement

Files changed:

```text
backend/core/browser_agent.py
backend/eval_registry/tests/smoke_openai_orchestrated_e2e.py
backend/eval_registry/tests/smoke_browser_agent_e2e.py
backend/eval_registry/README.md
backend/memory/convergence_checklist.md
backend/memory/hotfix_portback_ledger.md
```

Reason:

```text
OpenAI opt-in e2e could be misclassified because runtime_ledger run_finished may be written just after the smoke first reads events. browser_agent could also return success=true when browser-use stopped without a final result. The OpenAI smoke now waits briefly for required ledger events, and browser_agent now fails fast on missing browser LLM credentials and treats missing final result as failure.
DeepSeek thinking variants are not compatible with browser-use structured tool_choice, so browser_agent maps DeepSeek browser runs to a compatible DeepSeek chat model and rewrites /anthropic base_url to /v1 for the browser-use DeepSeek adapter.
```

Verification:

```text
GAGENT_E2E_DEPS=backend/temp/e2e_deps GAGENT_RUN_OPENAI_E2E=1 PYTHONUTF8=1 ./python-runtime/python.exe backend/eval_registry/tests/smoke_openai_orchestrated_e2e.py
GAGENT_E2E_DEPS=backend/temp/e2e_deps GAGENT_RUN_BROWSER_AGENT_E2E=1 PYTHONUTF8=1 ./python-runtime/python.exe backend/eval_registry/tests/smoke_browser_agent_e2e.py
PYTHONUTF8=1 ./python-runtime/python.exe backend/eval_registry/score_functionality.py
```

Rollback:

```text
Remove the OpenAI smoke event wait helper and browser_agent credential/final-result guards.
```

Status:

```text
OpenAI opt-in e2e passed; browser_agent opt-in e2e passed with DeepSeek browser model fallback; source port-back required
```

---

### Functionality score refresh

Files changed:

```text
backend/eval_registry/score_functionality.py
backend/eval_registry/README.md
backend/memory/convergence_checklist.md
backend/memory/hotfix_portback_ledger.md
```

Reason:

```text
latest_functionality_score.json could be computed from stale latest_* reports. score_functionality.py now supports --refresh, which runs the eval report generators before scoring so the score can be tied to the current source state.
```

Verification:

```text
PYTHONUTF8=1 ./python-runtime/python.exe backend/eval_registry/score_functionality.py --self-test
PYTHONUTF8=1 ./python-runtime/python.exe backend/eval_registry/score_functionality.py --refresh
```

Rollback:

```text
Remove the --refresh argument and _refresh_reports/_refresh_commands helpers from score_functionality.py, then restore the old checklist command.
```

Status:

```text
functionality score refresh applied; source port-back required
```

---

### OpenAI E2E classic init noise

Files changed:

```text
backend/core/openai_agentmain.py
backend/eval_registry/tests/smoke_openai_orchestrated_e2e.py
backend/memory/convergence_checklist.md
backend/memory/hotfix_portback_ledger.md
```

Reason:

```text
OpenAI orchestrated E2E could pass while Classic GenericAgent optional initialization printed a GA_API_KEY traceback. Classic executor init failure is now stored on the agent and only returned if the classic executor path is actually used. The OpenAI smoke has an offline regression check for quiet classic init failure.
```

Verification:

```text
PYTHONUTF8=1 ./python-runtime/python.exe -m py_compile backend/core/openai_agentmain.py backend/eval_registry/tests/smoke_openai_orchestrated_e2e.py
PYTHONUTF8=1 ./python-runtime/python.exe backend/eval_registry/tests/smoke_openai_orchestrated_e2e.py
GAGENT_E2E_DEPS=backend/temp/e2e_deps GAGENT_RUN_OPENAI_E2E=1 PYTHONUTF8=1 ./python-runtime/python.exe backend/eval_registry/tests/smoke_openai_orchestrated_e2e.py
```

Rollback:

```text
Restore direct traceback printing in _init_classic_executor and remove _self_test_classic_executor_init_quiet from the OpenAI smoke.
```

Status:

```text
OpenAI E2E classic init traceback suppression applied; source port-back required
```

---

### Functionality score quiet refresh output

Files changed:

```text
backend/eval_registry/score_functionality.py
backend/eval_registry/README.md
backend/memory/convergence_checklist.md
backend/memory/hotfix_portback_ledger.md
```

Reason:

```text
score_functionality.py --refresh previously streamed child command logs before the final score JSON, which made the score hard to parse automatically. Successful refresh now captures child stdout/stderr and prints only the final JSON report; failed refresh still prints captured child stdout/stderr to stderr.
```

Verification:

```text
PYTHONUTF8=1 ./python-runtime/python.exe backend/eval_registry/score_functionality.py --self-test
GAGENT_E2E_DEPS=backend/temp/e2e_deps GAGENT_RUN_OPENAI_E2E=1 GAGENT_RUN_BROWSER_AGENT_E2E=1 PYTHONUTF8=1 ./python-runtime/python.exe backend/eval_registry/score_functionality.py --refresh
```

Rollback:

```text
Replace _run_refresh_command with direct subprocess.run(command, cwd=ROOT, check=True) and remove captured-output helpers.
```

Status:

```text
functionality score quiet refresh output applied; source port-back required
```

---

### Functionality score refresh failure self-test

Files changed:

```text
backend/eval_registry/score_functionality.py
backend/eval_registry/README.md
backend/memory/convergence_checklist.md
backend/memory/hotfix_portback_ledger.md
```

Reason:

```text
The quiet refresh path was verified for successful JSON output, but refresh child-command failure output was only covered by formatting helpers. The self-test now runs a local failing Python child process and asserts returncode/stdout/stderr are preserved.
```

Verification:

```text
PYTHONUTF8=1 ./python-runtime/python.exe backend/eval_registry/score_functionality.py --self-test
```

Rollback:

```text
Remove the failing_command block from _self_test and restore the previous README/checklist text.
```

Status:

```text
functionality score refresh failure self-test applied; source port-back required
```

---

### Functionality score strict gate

Files changed:

```text
backend/eval_registry/score_functionality.py
backend/eval_registry/README.md
backend/memory/convergence_checklist.md
backend/memory/hotfix_portback_ledger.md
```

Reason:

```text
score_functionality.py could report needs_work while exiting 0, which is useful for advisory reports but too soft for completion gates. The command now supports --strict so needs_work exits non-zero while a complete 100/100 score exits 0.
```

Verification:

```text
PYTHONUTF8=1 ./python-runtime/python.exe backend/eval_registry/score_functionality.py --self-test
GAGENT_E2E_DEPS=backend/temp/e2e_deps GAGENT_RUN_OPENAI_E2E=1 GAGENT_RUN_BROWSER_AGENT_E2E=1 PYTHONUTF8=1 ./python-runtime/python.exe backend/eval_registry/score_functionality.py --refresh --strict
```

Rollback:

```text
Remove the --strict argument and _exit_code_for_report helper, then restore the checklist command to --refresh.
```

Status:

```text
functionality score strict gate applied; source port-back required
```

---

### Functionality score isolated CLI fixtures

Files changed:

```text
backend/eval_registry/score_functionality.py
backend/eval_registry/README.md
backend/memory/convergence_checklist.md
backend/memory/hotfix_portback_ledger.md
```

Reason:

```text
The strict gate self-test covered helper exit-code logic but not the real CLI argument path. score_functionality.py now accepts --results-dir, and the self-test uses temporary report fixtures plus --no-write to verify strict/non-strict CLI exit behavior without touching runtime artifacts.
```

Verification:

```text
PYTHONUTF8=1 ./python-runtime/python.exe backend/eval_registry/score_functionality.py --self-test
```

Rollback:

```text
Remove the --results-dir argument and temporary-directory CLI subprocess checks from _self_test.
```

Status:

```text
functionality score isolated CLI fixture checks applied; source port-back required
```

---

### Functionality score strict skip semantics

Files changed:

```text
backend/eval_registry/score_functionality.py
backend/eval_registry/README.md
backend/memory/convergence_checklist.md
backend/memory/hotfix_portback_ledger.md
```

Reason:

```text
The convergence checklist used the strict score command without stating that optional real E2E env vars must be enabled. The checklist now separates baseline advisory scoring from the full-flow completion gate, and the score self-test verifies skipped optional E2E reports stay needs_work and fail strict completion.
```

Verification:

```text
PYTHONUTF8=1 ./python-runtime/python.exe backend/eval_registry/score_functionality.py --self-test
GAGENT_E2E_DEPS=backend/temp/e2e_deps GAGENT_RUN_OPENAI_E2E=1 GAGENT_RUN_BROWSER_AGENT_E2E=1 PYTHONUTF8=1 ./python-runtime/python.exe backend/eval_registry/score_functionality.py --refresh --strict
```

Rollback:

```text
Remove the skipped_optional block from _self_test and restore convergence_checklist.md to the previous single strict command.
```

Status:

```text
functionality score strict skip semantics applied; source port-back required
```

---

### Functionality score refresh/results-dir conflict

Files changed:

```text
backend/eval_registry/score_functionality.py
backend/eval_registry/README.md
backend/memory/convergence_checklist.md
backend/memory/hotfix_portback_ledger.md
```

Reason:

```text
--results-dir is for isolated fixture reports, while --refresh regenerates the default latest reports. Allowing both together could refresh one directory and score another. The CLI now rejects this ambiguous combination, and self-test covers the real argparse path.
```

Verification:

```text
PYTHONUTF8=1 ./python-runtime/python.exe backend/eval_registry/score_functionality.py --self-test
```

Rollback:

```text
Remove the parser.error guard and invalid_combo self-test block.
```

Status:

```text
functionality score refresh/results-dir conflict guard applied; source port-back required
```

---

### Baseline convergence runner

Files changed:

```text
backend/eval_registry/run_convergence_checks.py
backend/eval_registry/README.md
backend/memory/convergence_checklist.md
backend/memory/hotfix_portback_ledger.md
package.json
```

Reason:

```text
The baseline convergence checklist was a manual list of commands, which made completion checks easy to run inconsistently. A small stdlib runner now executes the baseline gates in order with PYTHONUTF8=1 and reports the first failing command with captured output.
```

Verification:

```text
PYTHONUTF8=1 ./python-runtime/python.exe backend/eval_registry/run_convergence_checks.py
npm.cmd run test:convergence
```

Rollback:

```text
Remove backend/eval_registry/run_convergence_checks.py and the test:convergence/checklist/README references.
```

Status:

```text
baseline convergence runner applied; source port-back required
```

---

### Baseline convergence score visibility

Files changed:

```text
backend/eval_registry/run_convergence_checks.py
backend/eval_registry/README.md
backend/memory/convergence_checklist.md
backend/memory/hotfix_portback_ledger.md
```

Reason:

```text
The baseline convergence runner executed score_functionality.py --refresh but hid its successful JSON output, so advisory needs_work/blocker details were not visible. The runner now prints successful score output while keeping other successful child logs quiet.
```

Verification:

```text
PYTHONUTF8=1 ./python-runtime/python.exe backend/eval_registry/run_convergence_checks.py --self-test
PYTHONUTF8=1 ./python-runtime/python.exe backend/eval_registry/run_convergence_checks.py
```

Rollback:

```text
Remove _success_output_for/_is_score_command/_self_test and the success-output print from run_convergence_checks.py.
```

Status:

```text
baseline convergence score visibility applied; source port-back required
```

---

### Baseline convergence score JSON validation

Files changed:

```text
backend/eval_registry/run_convergence_checks.py
backend/eval_registry/README.md
backend/memory/convergence_checklist.md
backend/memory/hotfix_portback_ledger.md
```

Reason:

```text
The baseline convergence runner printed score_functionality.py output but did not validate that it was still pure JSON. It now parses the score output before printing it and fails if logs or other text pollute stdout.
```

Verification:

```text
PYTHONUTF8=1 ./python-runtime/python.exe backend/eval_registry/run_convergence_checks.py --self-test
PYTHONUTF8=1 ./python-runtime/python.exe backend/eval_registry/run_convergence_checks.py
```

Rollback:

```text
Remove the json.loads validation from _success_output_for and restore direct stdout.strip() forwarding.
```

Status:

```text
baseline convergence score JSON validation applied; source port-back required
```

---

### Full convergence package script

Files changed:

```text
package.json
backend/eval_registry/README.md
backend/memory/convergence_checklist.md
backend/memory/hotfix_portback_ledger.md
```

Reason:

```text
Baseline convergence had a package script, but the full strict completion gate still required manually spelling the scorer command. package.json now exposes test:convergence:full, which runs score_functionality.py --refresh --strict and relies on the caller to set the opt-in E2E env vars.
```

Verification:

```text
GAGENT_E2E_DEPS=backend/temp/e2e_deps GAGENT_RUN_OPENAI_E2E=1 GAGENT_RUN_BROWSER_AGENT_E2E=1 npm.cmd run test:convergence:full
```

Rollback:

```text
Remove test:convergence:full from package.json and restore the checklist/README references.
```

Status:

```text
full convergence package script applied; source port-back required
```

---

### Full convergence runner mode

Files changed:

```text
backend/eval_registry/run_convergence_checks.py
package.json
backend/eval_registry/README.md
backend/memory/convergence_checklist.md
backend/memory/hotfix_portback_ledger.md
```

Reason:

```text
test:convergence:full ran only score_functionality.py --refresh --strict, so it did not include the baseline tool/quality/runtime validators. run_convergence_checks.py now supports --full, which runs the same baseline validators and uses strict scoring for the functionality score step.
```

Verification:

```text
PYTHONUTF8=1 ./python-runtime/python.exe backend/eval_registry/run_convergence_checks.py --self-test
GAGENT_E2E_DEPS=backend/temp/e2e_deps GAGENT_RUN_OPENAI_E2E=1 GAGENT_RUN_BROWSER_AGENT_E2E=1 npm.cmd run test:convergence:full
```

Rollback:

```text
Remove --full support from run_convergence_checks.py and point test:convergence:full back at score_functionality.py --refresh --strict.
```

Status:

```text
full convergence runner mode applied; source port-back required
```

---

### Functionality score results-dir no-write guard

Files changed:

```text
backend/eval_registry/score_functionality.py
backend/eval_registry/README.md
backend/memory/convergence_checklist.md
backend/memory/hotfix_portback_ledger.md
```

Reason:

```text
--results-dir is for isolated fixture reports. Allowing it without --no-write could write fixture-derived scores into the default latest_functionality_score.json artifact. The CLI now rejects that combination, and self-test covers the real argparse path.
```

Verification:

```text
PYTHONUTF8=1 ./python-runtime/python.exe backend/eval_registry/score_functionality.py --self-test
GAGENT_E2E_DEPS=backend/temp/e2e_deps GAGENT_RUN_OPENAI_E2E=1 GAGENT_RUN_BROWSER_AGENT_E2E=1 npm.cmd run test:convergence:full
```

Rollback:

```text
Remove the --results-dir requires --no-write parser guard and missing_no_write self-test block, then restore the README/checklist text.
```

Status:

```text
functionality score results-dir no-write guard applied; source port-back required
```

---

### Functionality score evidence metadata

Files changed:

```text
backend/eval_registry/score_functionality.py
backend/eval_registry/README.md
backend/memory/convergence_checklist.md
backend/memory/hotfix_portback_ledger.md
```

Reason:

```text
A 100/100 functionality score was machine-readable, but did not say which report files, Python runtime, results directory, or non-secret E2E switches produced it. score_functionality.py now emits an evidence object so score reports are easier to audit without reading shell history.
```

Verification:

```text
PYTHONUTF8=1 ./python-runtime/python.exe backend/eval_registry/score_functionality.py --self-test
GAGENT_E2E_DEPS=backend/temp/e2e_deps GAGENT_RUN_OPENAI_E2E=1 GAGENT_RUN_BROWSER_AGENT_E2E=1 npm.cmd run test:convergence:full
```

Rollback:

```text
Remove _build_evidence/_input_report_evidence/_utc_* helpers, the report["evidence"] assignment, and the evidence assertions/docs.
```

Status:

```text
functionality score evidence metadata applied; source port-back required
```

---

### Convergence runner score evidence validation

Files changed:

```text
backend/eval_registry/run_convergence_checks.py
backend/eval_registry/README.md
backend/memory/convergence_checklist.md
backend/memory/hotfix_portback_ledger.md
```

Reason:

```text
score_functionality.py emitted evidence metadata, but run_convergence_checks.py only verified that stdout was a JSON object. The convergence runner now rejects score output without required evidence fields, input report entries, E2E switch entries, and UTC timestamps.
```

Verification:

```text
PYTHONUTF8=1 ./python-runtime/python.exe backend/eval_registry/run_convergence_checks.py --self-test
GAGENT_E2E_DEPS=backend/temp/e2e_deps GAGENT_RUN_OPENAI_E2E=1 GAGENT_RUN_BROWSER_AGENT_E2E=1 npm.cmd run test:convergence:full
```

Rollback:

```text
Remove SCORE_INPUT_REPORTS, SCORE_E2E_ENV_KEYS, _validate_score_evidence, _score_output_fixture, and restore _self_test to the old minimal JSON object check.
```

Status:

```text
convergence runner score evidence validation applied; source port-back required
```

---

### Functionality score Git source fingerprint

Files changed:

```text
backend/eval_registry/score_functionality.py
backend/eval_registry/run_convergence_checks.py
backend/eval_registry/README.md
backend/memory/convergence_checklist.md
backend/memory/hotfix_portback_ledger.md
```

Reason:

```text
Functionality score reports captured runtime evidence, but not the source version that produced the score. score_functionality.py now emits source_git.available/head/branch/dirty, and run_convergence_checks.py rejects score output that cannot bind to a Git source fingerprint.
```

Verification:

```text
PYTHONUTF8=1 ./python-runtime/python.exe backend/eval_registry/score_functionality.py --self-test
PYTHONUTF8=1 ./python-runtime/python.exe backend/eval_registry/run_convergence_checks.py --self-test
GAGENT_E2E_DEPS=backend/temp/e2e_deps GAGENT_RUN_OPENAI_E2E=1 GAGENT_RUN_BROWSER_AGENT_E2E=1 npm.cmd run test:convergence:full
```

Rollback:

```text
Remove _source_git_evidence/_git_text, the evidence.source_git assignment and assertions, and the source_git validation block in run_convergence_checks.py.
```

Status:

```text
functionality score Git source fingerprint applied; source port-back required
```

---

### Convergence runner score component validation

Files changed:

```text
backend/eval_registry/run_convergence_checks.py
backend/eval_registry/README.md
backend/memory/convergence_checklist.md
backend/memory/hotfix_portback_ledger.md
```

Reason:

```text
run_convergence_checks.py validated score JSON and evidence, but not the score component contract. A future weight/name change could still print a 100/100-looking score. The runner now rejects score output unless the three expected components and weights are exactly internal_eval=70, openai_orchestrated_e2e=15, browser_agent_e2e=15.
```

Verification:

```text
PYTHONUTF8=1 ./python-runtime/python.exe backend/eval_registry/run_convergence_checks.py --self-test
GAGENT_E2E_DEPS=backend/temp/e2e_deps GAGENT_RUN_OPENAI_E2E=1 GAGENT_RUN_BROWSER_AGENT_E2E=1 npm.cmd run test:convergence:full
```

Rollback:

```text
Remove SCORE_COMPONENT_WEIGHTS, _validate_score_components, the component fixture fields, and the component rejection self-tests.
```

Status:

```text
convergence runner score component validation applied; source port-back required
```

---

### Functionality score component weight source

Files changed:

```text
backend/eval_registry/score_functionality.py
backend/eval_registry/run_convergence_checks.py
backend/eval_registry/README.md
backend/memory/convergence_checklist.md
backend/memory/hotfix_portback_ledger.md
```

Reason:

```text
The convergence runner locked expected score component weights, but duplicated the same constants already owned by score_functionality.py. score_functionality.py now exports SCORE_COMPONENT_WEIGHTS, and run_convergence_checks.py imports that source of truth while still validating report output against it.
```

Verification:

```text
PYTHONUTF8=1 ./python-runtime/python.exe backend/eval_registry/run_convergence_checks.py --self-test
PYTHONUTF8=1 ./python-runtime/python.exe backend/eval_registry/score_functionality.py --self-test
GAGENT_E2E_DEPS=backend/temp/e2e_deps GAGENT_RUN_OPENAI_E2E=1 GAGENT_RUN_BROWSER_AGENT_E2E=1 npm.cmd run test:convergence:full
```

Rollback:

```text
Remove SCORE_COMPONENT_WEIGHTS from score_functionality.py, remove the run_convergence_checks.py import/path shim, and restore the local runner component weight dict.
```

Status:

```text
functionality score component weight source applied; source port-back required
```

---

### Convergence runner score total consistency

Files changed:

```text
backend/eval_registry/run_convergence_checks.py
backend/eval_registry/README.md
backend/memory/convergence_checklist.md
backend/memory/hotfix_portback_ledger.md
```

Reason:

```text
run_convergence_checks.py validated component names/weights and evidence, but not whether total, max_total, status, and component scores agreed with each other. The runner now rejects inconsistent totals, invalid component score ranges, wrong max_total, and status values that do not match the computed total.
```

Verification:

```text
PYTHONUTF8=1 ./python-runtime/python.exe backend/eval_registry/run_convergence_checks.py --self-test
GAGENT_E2E_DEPS=backend/temp/e2e_deps GAGENT_RUN_OPENAI_E2E=1 GAGENT_RUN_BROWSER_AGENT_E2E=1 npm.cmd run test:convergence:full
```

Rollback:

```text
Remove the total/max_total/status/component score validation block and the bad_total/bad_max_total/bad_status/bad_component_score self-test cases.
```

Status:

```text
convergence runner score total consistency applied; source port-back required
```

---

### Convergence runner blocker consistency

Files changed:

```text
backend/eval_registry/run_convergence_checks.py
backend/eval_registry/README.md
backend/memory/convergence_checklist.md
backend/memory/hotfix_portback_ledger.md
```

Reason:

```text
score_functionality.py computes top-level blockers from component blockers, but run_convergence_checks.py did not verify that relationship. The runner now rejects reports where component blockers are malformed or top-level blockers do not exactly match the flattened component blockers list.
```

Verification:

```text
PYTHONUTF8=1 ./python-runtime/python.exe backend/eval_registry/run_convergence_checks.py --self-test
GAGENT_E2E_DEPS=backend/temp/e2e_deps GAGENT_RUN_OPENAI_E2E=1 GAGENT_RUN_BROWSER_AGENT_E2E=1 npm.cmd run test:convergence:full
```

Rollback:

```text
Remove the component blockers validation, top-level blockers comparison, and bad_blockers self-test case.
```

Status:

```text
convergence runner blocker consistency applied; source port-back required
```

---

### Functionality score max-total source

Files changed:

```text
backend/eval_registry/score_functionality.py
backend/eval_registry/README.md
backend/memory/convergence_checklist.md
backend/memory/hotfix_portback_ledger.md
```

Reason:

```text
score_functionality.py exported SCORE_COMPONENT_WEIGHTS for the convergence runner, but score_reports still hard-coded max_total/status against 100. The score now computes component weights, max_total, and status from SCORE_COMPONENT_WEIGHTS, and self-test mutates the weight table to prove the relationship.
```

Verification:

```text
PYTHONUTF8=1 ./python-runtime/python.exe backend/eval_registry/score_functionality.py --self-test
PYTHONUTF8=1 ./python-runtime/python.exe backend/eval_registry/run_convergence_checks.py --self-test
GAGENT_E2E_DEPS=backend/temp/e2e_deps GAGENT_RUN_OPENAI_E2E=1 GAGENT_RUN_BROWSER_AGENT_E2E=1 npm.cmd run test:convergence:full
```

Rollback:

```text
Restore the old hard-coded weight constants, return status/max_total to the literal 100 behavior, and remove the shifted_weights self-test block.
```

Status:

```text
functionality score max-total source applied; source port-back required
```

---

### Convergence runner score fixture weight source

Files changed:

```text
backend/eval_registry/score_functionality.py
backend/eval_registry/run_convergence_checks.py
backend/eval_registry/README.md
backend/memory/convergence_checklist.md
backend/memory/hotfix_portback_ledger.md
```

Reason:

```text
The convergence runner imported SCORE_COMPONENT_WEIGHTS for validation, but its self-test fixture still hard-coded 70/15/15. The fixture now generates component weights, total, and max_total from SCORE_COMPONENT_WEIGHTS, and the unused legacy weight aliases in score_functionality.py were removed.
```

Verification:

```text
PYTHONUTF8=1 ./python-runtime/python.exe backend/eval_registry/run_convergence_checks.py --self-test
PYTHONUTF8=1 ./python-runtime/python.exe backend/eval_registry/score_functionality.py --self-test
GAGENT_E2E_DEPS=backend/temp/e2e_deps GAGENT_RUN_OPENAI_E2E=1 GAGENT_RUN_BROWSER_AGENT_E2E=1 npm.cmd run test:convergence:full
```

Rollback:

```text
Restore hard-coded component fixture values in _score_output_fixture and re-add the legacy INTERNAL_EVAL_WEIGHT/OPENAI_E2E_WEIGHT/BROWSER_AGENT_E2E_WEIGHT aliases.
```

Status:

```text
convergence runner score fixture weight source applied; source port-back required
```

---

### Convergence runner component status validation

Files changed:

```text
backend/eval_registry/run_convergence_checks.py
backend/eval_registry/README.md
backend/memory/convergence_checklist.md
backend/memory/hotfix_portback_ledger.md
```

Reason:

```text
score_functionality.py emits status for every component, but run_convergence_checks.py did not require that field in score output. The runner now rejects score reports with missing or non-string component status values, and its self-test fixture includes component statuses.
```

Verification:

```text
PYTHONUTF8=1 ./python-runtime/python.exe backend/eval_registry/run_convergence_checks.py --self-test
PYTHONUTF8=1 ./python-runtime/python.exe backend/eval_registry/score_functionality.py --self-test
GAGENT_E2E_DEPS=backend/temp/e2e_deps GAGENT_RUN_OPENAI_E2E=1 GAGENT_RUN_BROWSER_AGENT_E2E=1 npm.cmd run test:convergence:full
```

Rollback:

```text
Remove the component status validation, the bad_component_status self-test case, and the status fields from _score_output_fixture.
```

Status:

```text
convergence runner component status validation applied; source port-back required
```

---

### Convergence runner score mode validation

Files changed:

```text
backend/eval_registry/run_convergence_checks.py
backend/eval_registry/README.md
backend/memory/convergence_checklist.md
backend/memory/hotfix_portback_ledger.md
```

Reason:

```text
run_convergence_checks.py always invokes score_functionality.py with --refresh, and full mode also uses --strict, but it did not verify that the score JSON reported matching refreshed/strict flags. The runner now rejects score reports whose mode flags do not match the command it executed.
```

Verification:

```text
PYTHONUTF8=1 ./python-runtime/python.exe backend/eval_registry/run_convergence_checks.py --self-test
PYTHONUTF8=1 ./python-runtime/python.exe backend/eval_registry/score_functionality.py --self-test
GAGENT_E2E_DEPS=backend/temp/e2e_deps GAGENT_RUN_OPENAI_E2E=1 GAGENT_RUN_BROWSER_AGENT_E2E=1 npm.cmd run test:convergence:full
```

Rollback:

```text
Remove _validate_score_mode, the call from _success_output_for, and the bad_refreshed/bad_strict/missing_strict self-test cases.
```

Status:

```text
convergence runner score mode validation applied; source port-back required
```

---

### Full convergence clean-source gate

Files changed:

```text
backend/eval_registry/run_convergence_checks.py
backend/eval_registry/README.md
backend/memory/convergence_checklist.md
backend/memory/hotfix_portback_ledger.md
```

Reason:

```text
Functionality score evidence included source_git.dirty, but full convergence did not reject dirty worktrees. run_convergence_checks.py now rejects strict score output when evidence.source_git.dirty is true, so a full completion gate must bind to committed source.
```

Verification:

```text
PYTHONUTF8=1 ./python-runtime/python.exe backend/eval_registry/run_convergence_checks.py --self-test
PYTHONUTF8=1 ./python-runtime/python.exe backend/eval_registry/score_functionality.py --self-test
GAGENT_E2E_DEPS=backend/temp/e2e_deps GAGENT_RUN_OPENAI_E2E=1 GAGENT_RUN_BROWSER_AGENT_E2E=1 npm.cmd run test:convergence:full
```

Rollback:

```text
Remove the strict dirty check in _validate_score_evidence and the strict_dirty self-test case.
```

Status:

```text
full convergence clean-source gate applied; source port-back required
```

---

### Functionality score partial blocker diagnostics

Files changed:

```text
backend/eval_registry/score_functionality.py
backend/eval_registry/README.md
backend/memory/convergence_checklist.md
backend/memory/hotfix_portback_ledger.md
```

Reason:

```text
Internal eval cases could all have verdict=pass while the average score stayed below 100. Strict scoring failed correctly, but the component blockers could be empty, making the remaining gap hard to diagnose.
```

Verification:

```text
PYTHONUTF8=1 ./python-runtime/python.exe backend/eval_registry/score_functionality.py --self-test
```

Rollback:

```text
Remove the internal eval average-score blocker/status branch and the self-test assertion for partial blockers.
```

Status:

```text
functionality score partial blocker diagnostics applied; source port-back required
```

---

### Final-answer forbidden fallback scoring

Files changed:

```text
backend/eval_registry/score_final_answer.py
backend/eval_registry/tests/smoke_eval_registry.py
backend/eval_registry/README.md
backend/memory/convergence_checklist.md
backend/memory/hotfix_portback_ledger.md
```

Reason:

```text
Tool and ledger scoring rejected forbidden fallback usage, but final-answer scoring could still pass a failed web_search answer that recommended forbidden fallback tools such as web_scan or browser_agent. The final-answer scorer now rejects recommendation phrasing for tools listed in expected_tools.forbidden.
```

Verification:

```text
PYTHONUTF8=1 ./python-runtime/python.exe backend/eval_registry/tests/smoke_eval_registry.py
```

Rollback:

```text
Remove _forbidden_tool_recommendations, its call from score_final_answer, and the smoke assertion for forbidden fallback recommendations.
```

Status:

```text
final-answer forbidden fallback scoring applied; source port-back required
```

---

### Agent-loop actual final-answer eval

Files changed:

```text
backend/eval_registry/run_eval_cases.py
backend/eval_registry/tests/smoke_eval_registry.py
backend/eval_registry/README.md
backend/memory/convergence_checklist.md
backend/memory/hotfix_portback_ledger.md
```

Reason:

```text
Agent-loop evals exercised the real agent_runner_loop path, but the harness still scored a synthesized final answer. The success-path eval now extracts exit_reason.data.answer and the smoke test verifies the reported final_answer text comes from the loop output.
```

Verification:

```text
PYTHONUTF8=1 ./python-runtime/python.exe backend/eval_registry/tests/smoke_eval_registry.py
```

Rollback:

```text
Remove final_answer_text extraction/use in run_eval_cases.py and the FINAL_LOOP_ANSWER smoke assertion.
```

Status:

```text
agent-loop actual final-answer eval applied; source port-back required
```

---

### Optional E2E passed-evidence scoring

Files changed:

```text
backend/eval_registry/score_functionality.py
backend/eval_registry/README.md
backend/memory/convergence_checklist.md
backend/memory/hotfix_portback_ledger.md
```

Reason:

```text
The functionality score granted full optional E2E credit to any report with status=passed. A thin report without run_id or runtime_ledger evidence could therefore look complete. Optional E2E passed reports now need run_id, matching successful ledger_summary, plus OpenAI sentinel or browser_agent successful tool_result evidence.
```

Verification:

```text
PYTHONUTF8=1 ./python-runtime/python.exe backend/eval_registry/score_functionality.py --self-test
```

Rollback:

```text
Remove _passed_optional_e2e_errors and restore the self-test passed E2E fixtures to status-only reports.
```

Status:

```text
optional E2E passed-evidence scoring applied; source port-back required
```

---

### OpenAI E2E observability score evidence

Files changed:

```text
backend/eval_registry/score_functionality.py
backend/eval_registry/README.md
backend/memory/convergence_checklist.md
backend/memory/hotfix_portback_ledger.md
```

Reason:

```text
OpenAI E2E score evidence required run_id, ledger_summary, and sentinel output, but did not require RuntimeHost observability alignment. A passed report could still be too thin to prove the orchestrated path was observable end to end.
```

Verification:

```text
PYTHONUTF8=1 ./python-runtime/python.exe backend/eval_registry/score_functionality.py --self-test
GAGENT_E2E_DEPS=backend/temp/e2e_deps GAGENT_RUN_OPENAI_E2E=1 GAGENT_RUN_BROWSER_AGENT_E2E=1 npm.cmd run test:convergence:full
```

Rollback:

```text
Remove _openai_observability_errors and the observability block from the self-test OpenAI passed fixture.
```

Status:

```text
OpenAI E2E observability score evidence applied; source port-back required
```

---

### Browser-agent E2E output score evidence

Files changed:

```text
backend/eval_registry/score_functionality.py
backend/eval_registry/README.md
backend/memory/convergence_checklist.md
backend/memory/hotfix_portback_ledger.md
```

Reason:

```text
Browser-agent E2E score evidence required status=passed, run_id, ledger_summary, and successful tool_result, but a tool_result with only success=true was still too thin. Passed browser_agent reports now need non-empty result output and a positive steps_taken count.
```

Verification:

```text
PYTHONUTF8=1 ./python-runtime/python.exe backend/eval_registry/score_functionality.py --self-test
GAGENT_E2E_DEPS=backend/temp/e2e_deps GAGENT_RUN_OPENAI_E2E=1 GAGENT_RUN_BROWSER_AGENT_E2E=1 npm.cmd run test:convergence:full
```

Rollback:

```text
Remove the browser_agent result/steps_taken evidence checks and restore the self-test browser_agent passed fixture to success-only.
```

Status:

```text
browser-agent E2E output score evidence applied; source port-back required
```

---

### Internal eval registry coverage scoring

Files changed:

```text
backend/eval_registry/score_functionality.py
backend/eval_registry/README.md
backend/memory/convergence_checklist.md
backend/memory/hotfix_portback_ledger.md
```

Reason:

```text
Internal eval scoring trusted the result average only. A thin latest_eval_report.json with one passing case could score the full internal_eval weight. The scorer now derives expected case ids from backend/eval_registry/cases/*.json and rejects missing, unexpected, duplicate, or mismatched case_count evidence.
```

Verification:

```text
PYTHONUTF8=1 ./python-runtime/python.exe backend/eval_registry/score_functionality.py --self-test
GAGENT_E2E_DEPS=backend/temp/e2e_deps GAGENT_RUN_OPENAI_E2E=1 GAGENT_RUN_BROWSER_AGENT_E2E=1 npm.cmd run test:convergence:full
```

Rollback:

```text
Remove _internal_eval_coverage_blockers, _expected_eval_case_ids, and the registry-derived internal eval self-test fixtures.
```

Status:

```text
internal eval registry coverage scoring applied; source port-back required
```

---

### Internal eval summary consistency scoring

Files changed:

```text
backend/eval_registry/score_functionality.py
backend/eval_registry/README.md
backend/memory/convergence_checklist.md
backend/memory/hotfix_portback_ledger.md
```

Reason:

```text
Internal eval scoring now checked coverage, but still trusted top-level summary fields implicitly. A report could contain all passing results while status/passed/failed/skipped fields contradicted those results. The scorer now derives summary counts and expected status from result verdicts and rejects mismatches.
```

Verification:

```text
PYTHONUTF8=1 ./python-runtime/python.exe backend/eval_registry/score_functionality.py --self-test
GAGENT_E2E_DEPS=backend/temp/e2e_deps GAGENT_RUN_OPENAI_E2E=1 GAGENT_RUN_BROWSER_AGENT_E2E=1 npm.cmd run test:convergence:full
```

Rollback:

```text
Remove the internal eval status/passed/failed/skipped comparisons from _internal_eval_coverage_blockers and the inconsistent summary self-test block.
```

Status:

```text
internal eval summary consistency scoring applied; source port-back required
```

---

### Eval case allowed-target validation

Files changed:

```text
backend/eval_registry/validate_eval_registry.py
backend/eval_registry/tests/smoke_eval_registry.py
backend/eval_registry/README.md
backend/memory/convergence_checklist.md
backend/memory/hotfix_portback_ledger.md
```

Reason:

```text
Eval cases could set target_tool to one tool while expected_tools.allowed listed a different tool. That made the boundary contract ambiguous. The validator now exposes a per-case helper and rejects cases whose allowed list does not include target_tool; smoke_eval_registry covers the regression with a mutated case.
```

Verification:

```text
PYTHONUTF8=1 ./python-runtime/python.exe backend/eval_registry/validate_eval_registry.py
PYTHONUTF8=1 ./python-runtime/python.exe backend/eval_registry/tests/smoke_eval_registry.py
GAGENT_E2E_DEPS=backend/temp/e2e_deps GAGENT_RUN_OPENAI_E2E=1 GAGENT_RUN_BROWSER_AGENT_E2E=1 npm.cmd run test:convergence:full
```

Rollback:

```text
Inline _validate_loaded_case back into validate(), remove the allowed-target check, and remove the smoke mutation assertion.
```

Status:

```text
eval case allowed-target validation applied; source port-back required
```

---

### Eval case allowed-forbidden disjoint validation

Files changed:

```text
backend/eval_registry/validate_eval_registry.py
backend/eval_registry/tests/smoke_eval_registry.py
backend/eval_registry/README.md
backend/memory/convergence_checklist.md
backend/memory/hotfix_portback_ledger.md
```

Reason:

```text
Eval cases could allow and forbid the same tool in one boundary contract. The validator now rejects overlap between expected_tools.allowed and expected_tools.forbidden; smoke_eval_registry covers the regression with a mutated case.
```

Verification:

```text
PYTHONUTF8=1 ./python-runtime/python.exe backend/eval_registry/validate_eval_registry.py
PYTHONUTF8=1 ./python-runtime/python.exe backend/eval_registry/tests/smoke_eval_registry.py
GAGENT_E2E_DEPS=backend/temp/e2e_deps GAGENT_RUN_OPENAI_E2E=1 GAGENT_RUN_BROWSER_AGENT_E2E=1 npm.cmd run test:convergence:full
```

Rollback:

```text
Remove the allowed/forbidden overlap check and the smoke mutation assertion.
```

Status:

```text
eval case allowed-forbidden disjoint validation applied; source port-back required
```

---

### Eval case expected-tool registry validation

Files changed:

```text
backend/eval_registry/validate_eval_registry.py
backend/eval_registry/tests/smoke_eval_registry.py
backend/eval_registry/README.md
backend/memory/convergence_checklist.md
backend/memory/hotfix_portback_ledger.md
```

Reason:

```text
Eval cases could reference tool names in expected_tools.allowed or expected_tools.forbidden that had no registry definition. The validator now resolves known tools from backend/tool_registry/tools/*.yml and rejects unknown expected tool names; smoke_eval_registry covers both allowed and forbidden lists with a mutated case.
```

Verification:

```text
PYTHONUTF8=1 ./python-runtime/python.exe backend/eval_registry/validate_eval_registry.py
PYTHONUTF8=1 ./python-runtime/python.exe backend/eval_registry/tests/smoke_eval_registry.py
GAGENT_E2E_DEPS=backend/temp/e2e_deps GAGENT_RUN_OPENAI_E2E=1 GAGENT_RUN_BROWSER_AGENT_E2E=1 npm.cmd run test:convergence:full
```

Rollback:

```text
Remove the expected_tools registry-name check and the smoke mutation assertion.
```

Status:

```text
eval case expected-tool registry validation applied; source port-back required
```

---

### Eval case decision-forbidden subset validation

Files changed:

```text
backend/eval_registry/validate_eval_registry.py
backend/eval_registry/tests/smoke_eval_registry.py
backend/eval_registry/README.md
backend/memory/convergence_checklist.md
backend/memory/hotfix_portback_ledger.md
```

Reason:

```text
Eval cases could require ledger decisions to forbid tools that were not listed in expected_tools.forbidden. That split the ledger contract from the tool-boundary contract. The validator now requires expected_ledger.required_decision_forbidden_actions to be a subset of expected_tools.forbidden; smoke_eval_registry covers the regression with a mutated failure case.
```

Verification:

```text
PYTHONUTF8=1 ./python-runtime/python.exe backend/eval_registry/validate_eval_registry.py
PYTHONUTF8=1 ./python-runtime/python.exe backend/eval_registry/tests/smoke_eval_registry.py
GAGENT_E2E_DEPS=backend/temp/e2e_deps GAGENT_RUN_OPENAI_E2E=1 GAGENT_RUN_BROWSER_AGENT_E2E=1 npm.cmd run test:convergence:full
```

Rollback:

```text
Remove the required_decision_forbidden_actions subset check and the smoke mutation assertion.
```

Status:

```text
eval case decision-forbidden subset validation applied; source port-back required
```

---

### Eval case ledger event-name validation

Files changed:

```text
backend/eval_registry/validate_eval_registry.py
backend/eval_registry/tests/smoke_eval_registry.py
backend/eval_registry/README.md
backend/memory/convergence_checklist.md
backend/memory/hotfix_portback_ledger.md
```

Reason:

```text
Eval cases could require ledger event names that runtime_ledger would never write. The validator now checks expected_ledger.required_events and expected_ledger.required_on_failure against runtime_ledger.ledger._ALLOWED_EVENT_TYPES; smoke_eval_registry covers both fields with mutated cases.
```

Verification:

```text
PYTHONUTF8=1 ./python-runtime/python.exe backend/eval_registry/validate_eval_registry.py
PYTHONUTF8=1 ./python-runtime/python.exe backend/eval_registry/tests/smoke_eval_registry.py
GAGENT_E2E_DEPS=backend/temp/e2e_deps GAGENT_RUN_OPENAI_E2E=1 GAGENT_RUN_BROWSER_AGENT_E2E=1 npm.cmd run test:convergence:full
```

Rollback:

```text
Remove the expected_ledger event-name checks and the smoke mutation assertion.
```

Status:

```text
eval case ledger event-name validation applied; source port-back required
```

---

### Eval case expected-result outcome validation

Files changed:

```text
backend/eval_registry/validate_eval_registry.py
backend/eval_registry/tests/smoke_eval_registry.py
backend/eval_registry/README.md
backend/memory/convergence_checklist.md
backend/memory/hotfix_portback_ledger.md
```

Reason:

```text
Eval cases could set both expected_result.allow_success and expected_result.allow_structured_failure to false, making every possible tool outcome invalid. The validator now requires both fields to be booleans and at least one outcome to be allowed; smoke_eval_registry covers the impossible-outcome regression with a mutated case.
```

Verification:

```text
PYTHONUTF8=1 ./python-runtime/python.exe backend/eval_registry/validate_eval_registry.py
PYTHONUTF8=1 ./python-runtime/python.exe backend/eval_registry/tests/smoke_eval_registry.py
GAGENT_E2E_DEPS=backend/temp/e2e_deps GAGENT_RUN_OPENAI_E2E=1 GAGENT_RUN_BROWSER_AGENT_E2E=1 npm.cmd run test:convergence:full
```

Rollback:

```text
Remove the expected_result allow_success/allow_structured_failure checks and the smoke mutation assertion.
```

Status:

```text
eval case expected-result outcome validation applied; source port-back required
```

---

### Eval case tool-specific expected-result validation

Files changed:

```text
backend/eval_registry/validate_eval_registry.py
backend/eval_registry/tests/smoke_eval_registry.py
backend/eval_registry/README.md
backend/memory/convergence_checklist.md
backend/memory/hotfix_portback_ledger.md
```

Reason:

```text
Eval cases could attach tool-specific expected_result checks to the wrong target tool or case type, such as require_navigation_success on web_search. The validator now rejects misplaced search, scan, navigation, browser_agent contract, browser_agent handler, and agent-loop expected_result fields; smoke_eval_registry covers the drift with mutated cases.
```

Verification:

```text
PYTHONUTF8=1 ./python-runtime/python.exe backend/eval_registry/validate_eval_registry.py
PYTHONUTF8=1 ./python-runtime/python.exe backend/eval_registry/tests/smoke_eval_registry.py
GAGENT_E2E_DEPS=backend/temp/e2e_deps GAGENT_RUN_OPENAI_E2E=1 GAGENT_RUN_BROWSER_AGENT_E2E=1 npm.cmd run test:convergence:full
```

Rollback:

```text
Remove the tool-specific expected_result target/type checks and the smoke mutation assertion.
```

Status:

```text
eval case tool-specific expected-result validation applied; source port-back required
```

---

### Eval case required final status scoring

Files changed:

```text
backend/eval_registry/score_eval_result.py
backend/eval_registry/validate_eval_registry.py
backend/eval_registry/tests/smoke_eval_registry.py
backend/eval_registry/README.md
backend/memory/convergence_checklist.md
backend/memory/hotfix_portback_ledger.md
```

Reason:

```text
Eval cases could declare expected_result.require_final_status, but score_case_result only checked that final_status existed. A mismatched final_status could still pass. The scorer now fails mismatched or missing required final_status values, and the validator requires require_final_status to be a non-empty string.
```

Verification:

```text
PYTHONUTF8=1 ./python-runtime/python.exe backend/eval_registry/validate_eval_registry.py
PYTHONUTF8=1 ./python-runtime/python.exe backend/eval_registry/tests/smoke_eval_registry.py
GAGENT_E2E_DEPS=backend/temp/e2e_deps GAGENT_RUN_OPENAI_E2E=1 GAGENT_RUN_BROWSER_AGENT_E2E=1 npm.cmd run test:convergence:full
```

Rollback:

```text
Remove the require_final_status score check, validator type check, and smoke mismatch assertion.
```

Status:

```text
eval case required final status scoring applied; source port-back required
```

---

### Eval case runtime event-name validation

Files changed:

```text
backend/eval_registry/validate_eval_registry.py
backend/eval_registry/tests/smoke_eval_registry.py
backend/eval_registry/README.md
backend/memory/convergence_checklist.md
backend/memory/hotfix_portback_ledger.md
```

Reason:

```text
Agent-loop eval cases could require RuntimeHost event names that RuntimeHost would never emit. The validator now checks expected_result.require_runtime_events against core.runtime.event_schema.RuntimeEventType; smoke_eval_registry covers the regression with a mutated agent_loop_eval case.
```

Verification:

```text
PYTHONUTF8=1 ./python-runtime/python.exe backend/eval_registry/validate_eval_registry.py
PYTHONUTF8=1 ./python-runtime/python.exe backend/eval_registry/tests/smoke_eval_registry.py
GAGENT_E2E_DEPS=backend/temp/e2e_deps GAGENT_RUN_OPENAI_E2E=1 GAGENT_RUN_BROWSER_AGENT_E2E=1 npm.cmd run test:convergence:full
```

Rollback:

```text
Remove the RuntimeEventType require_runtime_events check and the smoke mutation assertion.
```

Status:

```text
eval case runtime event-name validation applied; source port-back required
```

---

### Eval case balanced-turn observability validation

Files changed:

```text
backend/eval_registry/validate_eval_registry.py
backend/eval_registry/tests/smoke_eval_registry.py
backend/eval_registry/README.md
backend/memory/convergence_checklist.md
backend/memory/hotfix_portback_ledger.md
```

Reason:

```text
Agent-loop eval cases could set expected_result.require_balanced_turn_events=true without requiring the llm_call_started and llm_call_completed RuntimeHost events that make the balance check observable. The validator now requires both events; smoke_eval_registry covers the regression with a mutated agent_loop_eval case.
```

Verification:

```text
PYTHONUTF8=1 ./python-runtime/python.exe backend/eval_registry/validate_eval_registry.py
PYTHONUTF8=1 ./python-runtime/python.exe backend/eval_registry/tests/smoke_eval_registry.py
GAGENT_E2E_DEPS=backend/temp/e2e_deps GAGENT_RUN_OPENAI_E2E=1 GAGENT_RUN_BROWSER_AGENT_E2E=1 npm.cmd run test:convergence:full
```

Rollback:

```text
Remove the balanced-turn require_runtime_events subset check and the smoke mutation assertion.
```

Status:

```text
eval case balanced-turn observability validation applied; source port-back required
```

---

### Eval case expected-result field whitelist

Files changed:

```text
backend/eval_registry/validate_eval_registry.py
backend/eval_registry/tests/smoke_eval_registry.py
backend/eval_registry/README.md
backend/memory/convergence_checklist.md
backend/memory/hotfix_portback_ledger.md
```

Reason:

```text
Eval cases could misspell expected_result keys and the validator/scorer would silently ignore those keys. The validator now rejects unknown expected_result fields; smoke_eval_registry covers the regression with a mutated typo field.
```

Verification:

```text
PYTHONUTF8=1 ./python-runtime/python.exe backend/eval_registry/validate_eval_registry.py
PYTHONUTF8=1 ./python-runtime/python.exe backend/eval_registry/tests/smoke_eval_registry.py
GAGENT_E2E_DEPS=backend/temp/e2e_deps GAGENT_RUN_OPENAI_E2E=1 GAGENT_RUN_BROWSER_AGENT_E2E=1 npm.cmd run test:convergence:full
```

Rollback:

```text
Remove the EXPECTED_RESULT_FIELDS check and the smoke mutation assertion.
```

Status:

```text
eval case expected-result field whitelist applied; source port-back required
```

---

### Eval case contract-object field whitelist

Files changed:

```text
backend/eval_registry/validate_eval_registry.py
backend/eval_registry/tests/smoke_eval_registry.py
backend/eval_registry/README.md
backend/memory/convergence_checklist.md
backend/memory/hotfix_portback_ledger.md
```

Reason:

```text
Eval cases could misspell expected_tools, expected_ledger, or score keys and the harness would ignore the extra keys. The validator now rejects unknown fields in those contract objects; smoke_eval_registry covers the regression with mutated typo fields.
```

Verification:

```text
PYTHONUTF8=1 ./python-runtime/python.exe backend/eval_registry/validate_eval_registry.py
PYTHONUTF8=1 ./python-runtime/python.exe backend/eval_registry/tests/smoke_eval_registry.py
GAGENT_E2E_DEPS=backend/temp/e2e_deps GAGENT_RUN_OPENAI_E2E=1 GAGENT_RUN_BROWSER_AGENT_E2E=1 npm.cmd run test:convergence:full
```

Rollback:

```text
Remove the EXPECTED_TOOLS_FIELDS, EXPECTED_LEDGER_FIELDS, and SCORE_FIELDS checks plus the smoke mutation assertion.
```

Status:

```text
eval case contract-object field whitelist applied; source port-back required
```

---

### Eval case top-level field whitelist

Files changed:

```text
backend/eval_registry/registry.py
backend/eval_registry/tests/smoke_eval_registry.py
backend/eval_registry/README.md
backend/memory/convergence_checklist.md
backend/memory/hotfix_portback_ledger.md
```

Reason:

```text
Eval case JSON files could include misspelled top-level fields and load_eval_case would ignore them after checking required fields. The loader now rejects unknown top-level fields; smoke_eval_registry covers the regression with a temporary mutated JSON case.
```

Verification:

```text
PYTHONUTF8=1 ./python-runtime/python.exe backend/eval_registry/validate_eval_registry.py
PYTHONUTF8=1 ./python-runtime/python.exe backend/eval_registry/tests/smoke_eval_registry.py
GAGENT_E2E_DEPS=backend/temp/e2e_deps GAGENT_RUN_OPENAI_E2E=1 GAGENT_RUN_BROWSER_AGENT_E2E=1 npm.cmd run test:convergence:full
```

Rollback:

```text
Remove the load_eval_case unknown-fields check and the smoke temporary-case assertion.
```

Status:

```text
eval case top-level field whitelist applied; source port-back required
```

---

### Eval case input field whitelist

Files changed:

```text
backend/eval_registry/validate_eval_registry.py
backend/eval_registry/tests/smoke_eval_registry.py
backend/eval_registry/README.md
backend/memory/convergence_checklist.md
backend/memory/hotfix_portback_ledger.md
```

Reason:

```text
Eval case input objects could include misspelled or wrong-case fields and the runner would ignore or misroute them. The validator now scopes allowed input fields by (type, target_tool); smoke_eval_registry covers web_search typo input and browser_agent contract-vs-handler input drift.
```

Verification:

```text
PYTHONUTF8=1 ./python-runtime/python.exe backend/eval_registry/validate_eval_registry.py
PYTHONUTF8=1 ./python-runtime/python.exe backend/eval_registry/tests/smoke_eval_registry.py
GAGENT_E2E_DEPS=backend/temp/e2e_deps GAGENT_RUN_OPENAI_E2E=1 GAGENT_RUN_BROWSER_AGENT_E2E=1 npm.cmd run test:convergence:full
```

Rollback:

```text
Remove INPUT_FIELDS_BY_CASE validation and the unknown-input smoke assertion.
```

Status:

```text
eval case input field whitelist applied; source port-back required
```

---

### Eval case type and version whitelist

Files changed:

```text
backend/eval_registry/validate_eval_registry.py
backend/eval_registry/tests/smoke_eval_registry.py
backend/eval_registry/README.md
backend/memory/convergence_checklist.md
backend/memory/hotfix_portback_ledger.md
```

Reason:

```text
Eval case type/version were accepted unless they failed indirectly through another contract. The validator now rejects unsupported type and version explicitly; smoke_eval_registry covers both mutations.
```

Verification:

```text
PYTHONUTF8=1 ./python-runtime/python.exe backend/eval_registry/validate_eval_registry.py
PYTHONUTF8=1 ./python-runtime/python.exe backend/eval_registry/tests/smoke_eval_registry.py
GAGENT_E2E_DEPS=backend/temp/e2e_deps GAGENT_RUN_OPENAI_E2E=1 GAGENT_RUN_BROWSER_AGENT_E2E=1 npm.cmd run test:convergence:full
```

Rollback:

```text
Remove SUPPORTED_CASE_TYPES, SUPPORTED_CASE_VERSIONS, and the unsupported type/version smoke assertion.
```

Status:

```text
eval case type/version whitelist applied; source port-back required
```

---

### Eval case score weight contract

Files changed:

```text
backend/eval_registry/validate_eval_registry.py
backend/eval_registry/tests/smoke_eval_registry.py
backend/eval_registry/README.md
backend/memory/convergence_checklist.md
backend/memory/hotfix_portback_ledger.md
```

Reason:

```text
Eval case score weights could sum to 100 while still being semantically invalid, such as -10/110 or 0/100. The validator now requires the current 60/40 harness contract; smoke_eval_registry covers both invalid distributions.
```

Verification:

```text
PYTHONUTF8=1 ./python-runtime/python.exe backend/eval_registry/validate_eval_registry.py
PYTHONUTF8=1 ./python-runtime/python.exe backend/eval_registry/tests/smoke_eval_registry.py
GAGENT_E2E_DEPS=backend/temp/e2e_deps GAGENT_RUN_OPENAI_E2E=1 GAGENT_RUN_BROWSER_AGENT_E2E=1 npm.cmd run test:convergence:full
```

Rollback:

```text
Remove SCORE_WEIGHTS validation and the invalid-score smoke assertion.
```

Status:

```text
eval case score weight contract applied; source port-back required
```

---

### Eval ledger list duplicate validation

Files changed:

```text
backend/eval_registry/validate_eval_registry.py
backend/eval_registry/tests/smoke_eval_registry.py
backend/eval_registry/README.md
backend/memory/convergence_checklist.md
backend/memory/hotfix_portback_ledger.md
```

Reason:

```text
Eval case expected_ledger list fields could repeat entries, making a case look stricter without adding coverage. The validator now rejects duplicate items in required_events, required_on_failure, and required_decision_forbidden_actions; smoke_eval_registry covers all three.
```

Verification:

```text
PYTHONUTF8=1 ./python-runtime/python.exe backend/eval_registry/validate_eval_registry.py
PYTHONUTF8=1 ./python-runtime/python.exe backend/eval_registry/tests/smoke_eval_registry.py
GAGENT_E2E_DEPS=backend/temp/e2e_deps GAGENT_RUN_OPENAI_E2E=1 GAGENT_RUN_BROWSER_AGENT_E2E=1 npm.cmd run test:convergence:full
```

Rollback:

```text
Remove _duplicate_strings validation and the duplicate-ledger-list smoke assertion.
```

Status:

```text
eval ledger list duplicate validation applied; source port-back required
```

---

### Eval expected-tools duplicate validation

Files changed:

```text
backend/eval_registry/validate_eval_registry.py
backend/eval_registry/tests/smoke_eval_registry.py
backend/eval_registry/README.md
backend/memory/convergence_checklist.md
backend/memory/hotfix_portback_ledger.md
```

Reason:

```text
Eval case expected_tools.allowed and expected_tools.forbidden could repeat tool names, making the contract noisy without adding coverage. The validator now rejects duplicate items in both lists; smoke_eval_registry covers both mutations.
```

Verification:

```text
PYTHONUTF8=1 ./python-runtime/python.exe backend/eval_registry/validate_eval_registry.py
PYTHONUTF8=1 ./python-runtime/python.exe backend/eval_registry/tests/smoke_eval_registry.py
GAGENT_E2E_DEPS=backend/temp/e2e_deps GAGENT_RUN_OPENAI_E2E=1 GAGENT_RUN_BROWSER_AGENT_E2E=1 npm.cmd run test:convergence:full
```

Rollback:

```text
Remove expected_tools duplicate validation and the duplicate-expected-tools smoke assertion.
```

Status:

```text
eval expected-tools duplicate validation applied; source port-back required
```

---

### Eval expected-result duplicate validation

Files changed:

```text
backend/eval_registry/validate_eval_registry.py
backend/eval_registry/tests/smoke_eval_registry.py
backend/eval_registry/README.md
backend/memory/convergence_checklist.md
backend/memory/hotfix_portback_ledger.md
```

Reason:

```text
Eval case expected_result list fields could repeat required runtime events or contract terms, making a case look stricter without adding coverage. The validator now rejects duplicate items in require_runtime_events and require_contract_terms; smoke_eval_registry covers both mutations.
```

Verification:

```text
PYTHONUTF8=1 ./python-runtime/python.exe backend/eval_registry/validate_eval_registry.py
PYTHONUTF8=1 ./python-runtime/python.exe backend/eval_registry/tests/smoke_eval_registry.py
GAGENT_E2E_DEPS=backend/temp/e2e_deps GAGENT_RUN_OPENAI_E2E=1 GAGENT_RUN_BROWSER_AGENT_E2E=1 npm.cmd run test:convergence:full
```

Rollback:

```text
Remove expected_result duplicate validation and the duplicate-expected-result smoke assertion.
```

Status:

```text
eval expected-result duplicate validation applied; source port-back required
```

---

### Eval expected-result boolean switch validation

Files changed:

```text
backend/eval_registry/validate_eval_registry.py
backend/eval_registry/tests/smoke_eval_registry.py
backend/eval_registry/README.md
backend/memory/convergence_checklist.md
backend/memory/hotfix_portback_ledger.md
```

Reason:

```text
Eval case expected_result boolean switches could be strings such as "true" and still be treated as truthy by scorer/runtime checks. The validator now requires all expected_result boolean switches to be real booleans; smoke_eval_registry covers every optional boolean switch.
```

Verification:

```text
PYTHONUTF8=1 ./python-runtime/python.exe backend/eval_registry/validate_eval_registry.py
PYTHONUTF8=1 ./python-runtime/python.exe backend/eval_registry/tests/smoke_eval_registry.py
GAGENT_E2E_DEPS=backend/temp/e2e_deps GAGENT_RUN_OPENAI_E2E=1 GAGENT_RUN_BROWSER_AGENT_E2E=1 npm.cmd run test:convergence:full
```

Rollback:

```text
Remove EXPECTED_RESULT_BOOL_FIELDS validation and the non-bool expected_result smoke assertion.
```

Status:

```text
eval expected-result boolean switch validation applied; source port-back required
```
