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
