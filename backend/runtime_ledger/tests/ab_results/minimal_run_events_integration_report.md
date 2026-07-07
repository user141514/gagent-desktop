# Runtime Ledger Minimal Run Events Integration Report

## Scope

This pass keeps the same narrow owner layer as the previous minimal integration: `do_web_search` only.

New behavior added:

```text
run_started -> tool_call -> tool_result -> decision on failure -> run_finished
```

Control flag:

```text
GENERIC_AGENT_RUNTIME_LEDGER=0 disables event writing.
```

No other tools are wired in this pass.

---

## Why this is still minimal

This does not wire the full agent loop. It only makes the existing per-tool web_search ledger trace complete enough to be summarized as a run-like unit.

Reason:

```text
Full openai_agentmain/agent-loop wiring would increase change radius. This step first verifies that run boundary events are useful and non-invasive on one tool path.
```

---

## A/B method

For each query, run the exact same `GenericAgentHandler.do_web_search` path twice:

```text
Phase A: GENERIC_AGENT_RUNTIME_LEDGER=0
Phase B: default ledger enabled
```

Compare:

```text
visible tool status
number of ledger events
summarize_run output
```

---

## Q2: OpenAI API docs

Observed in this run:

```text
Phase A status: error
Phase B status: error
same_status: true
Phase A ledger events: 0
Phase B ledger events: 5
```

Note:

```text
The external search path was temporarily failing in both phases. This does not invalidate the comparison because the status stayed identical. The test checks whether instrumentation changes behavior; it did not.
```

Phase B summary:

```text
event_count: 5
task: OpenAI API docs
owner_layer: Layer 1 capability contract
failure_count: 1
final_status: structured_failure
decision.action: switch_same_capability
forbidden_actions: web_scan, web_execute_js, browser_agent
```

---

## Q3: yobot GitHub code

Observed:

```text
Phase A status: error
Phase B status: error
same_status: true
Phase A ledger events: 0
Phase B ledger events: 5
error_category: browser_tool_error in the enriched result for this run
```

Phase B summary:

```text
event_count: 5
task: yobot GitHub code
owner_layer: Layer 1 capability contract
failure_count: 1
final_status: structured_failure
decision.action: switch_same_capability
decision.next_tool: web_search
forbidden_actions: web_scan, web_execute_js, browser_agent
```

Interpretation:

```text
The ledger now captures enough data for experience_registry to reconstruct the failure and forbidden fallback boundary.
```

---

## Score update

### Q2

```text
Answer/tool behavior: 60/60
Ledger: 35/40
Total: 95/100
```

Reason:

```text
Status unchanged. Ledger now has run_started/tool_call/tool_result/decision/run_finished. Missing only true global agent-run identity and final natural-language answer linkage.
```

### Q3

```text
Answer/tool behavior: 60/60
Ledger: 35/40
Total: 95/100
```

Reason:

```text
Status unchanged. Failure path includes decision and forbidden_actions. It is sufficient for later experience_registry reuse.
```

---

## Validation commands run

```text
PYTHONUTF8=1 ./python-runtime/python.exe -m py_compile backend/core/ga.py backend/runtime_ledger/ledger.py backend/runtime_ledger/validate_runtime_ledger.py backend/runtime_ledger/tests/smoke_runtime_ledger.py
PYTHONUTF8=1 ./python-runtime/python.exe backend/runtime_ledger/validate_runtime_ledger.py
PYTHONUTF8=1 ./python-runtime/python.exe backend/runtime_ledger/tests/smoke_runtime_ledger.py
PYTHONUTF8=1 ./python-runtime/python.exe backend/tool_registry/validate_tool_registry.py
PYTHONUTF8=1 ./python-runtime/python.exe backend/quality_registry/validate_quality_registry.py
```

Result:

```text
[validate_runtime_ledger] ok
[smoke_runtime_ledger] ok
[validate_tool_registry] ok
[validate_quality_registry] ok
MINIMAL_RUN_EVENTS_INTEGRATION_OK
```

---

## Verdict

```text
PASS
```

The integration improves observability while preserving the same visible tool outcome.

---

## Remaining limitations

```text
1. Still tool-level, not true full agent-run instrumentation.
2. Only web_search is wired.
3. summarize_run currently counts event records carrying a tool name, not unique tool invocations.
4. final_status is tool-run status, not final assistant answer status.
5. No experience_registry is consuming the ledger yet.
```

---

## Next recommended step

Do not wire all tools yet.

Next minimal step:

```text
Add a small helper inside runtime_ledger for scoring/extracting reusable failure records from one run summary.
```

This prepares experience_registry without touching the main agent loop.
