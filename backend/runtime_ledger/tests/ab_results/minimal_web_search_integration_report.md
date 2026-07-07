# Runtime Ledger Minimal Web Search Integration A/B Report

## Scope

Only `do_web_search` in `backend/core/ga.py` was minimally integrated with Runtime Ledger.

Events written when enabled:

```text
tool_call
tool_result
decision, only on structured failure
```

Control flag:

```text
GENERIC_AGENT_RUNTIME_LEDGER=0 disables event writing.
```

No other tools were wired in this pass.

---

## Phase A / baseline

Method:

```text
Run the same GenericAgentHandler.do_web_search path with GENERIC_AGENT_RUNTIME_LEDGER=0.
```

### Q2: OpenAI API docs

```text
status: success
ledger events: 0
```

### Q3: yobot GitHub code

```text
status: error
ledger events: 0
```

Baseline conclusion:

```text
Tool behavior works as before; no structured runtime trajectory is emitted.
```

---

## Phase B / minimal integration enabled

Method:

```text
Run the same GenericAgentHandler.do_web_search path with default GENERIC_AGENT_RUNTIME_LEDGER enabled.
```

### Q2: OpenAI API docs

```text
phase_a_status: success
phase_b_status: success
same_status: true
ledger events: 2
```

Ledger summary:

```text
event_count: 2
task: OpenAI API docs
owner_layer: Layer 1 capability contract
failure_count: 0
```

Interpretation:

```text
Ledger added observability without changing success behavior.
```

### Q3: yobot GitHub code

```text
phase_a_status: error
phase_b_status: error
same_status: true
ledger events: 3
error_category: network_error
```

Decision event:

```text
action: switch_same_capability
next_tool: web_search
recommended_next_tool: web_search(engine='bing', 'google', 'duckduckgo', or 'auto') / PowerShell HTTP transport / local-offline evidence
forbidden_actions:
  - web_scan
  - web_execute_js
  - browser_agent
```

Interpretation:

```text
Ledger captured the failure and the intended same-capability fallback boundary without altering the visible tool status.
```

---

## Scoring

### Q2

```text
Answer/tool behavior: 60/60
Ledger: 30/40
Total: 90/100
```

Rationale:

```text
Success path is preserved. Ledger records tool_call/tool_result with run_id, args, and result. No decision event is expected on success. No final_status yet because only web_search path is wired.
```

### Q3

```text
Answer/tool behavior: 60/60
Ledger: 35/40
Total: 95/100
```

Rationale:

```text
Failure path is preserved. Ledger records tool_call/tool_result/decision. Decision explicitly forbids web_scan/web_execute_js/browser_agent. Missing final_status because run-level instrumentation is not wired yet.
```

---

## Pass/fail criteria

Pass condition from test plan:

```text
1. Q2/Q3 ledger score >= 25/40
2. Average answer quality delta >= -5 compared with baseline
3. No Baidu/search-homepage fake success
4. JSONL validates and can be summarized
5. web_search failure does not route to web_scan
```

Observed:

```text
Q2 ledger score: 30/40
Q3 ledger score: 35/40
Answer status delta: 0
No Baidu/search-homepage fake success observed
Validators passed
web_search failure decision forbids web_scan/web_execute_js/browser_agent
```

Verdict:

```text
PASS
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
AB_MINIMAL_INTEGRATION_VALIDATED
```

---

## Limitations

```text
1. This is tool-level A/B, not full natural-language answer A/B.
2. Only web_search is wired.
3. No run_started/run_finished events are emitted from the main agent loop yet.
4. final_status remains null for real web_search events.
5. summarize_run currently counts all events with a tool field, not unique tool invocations.
```

---

## Next step

Recommended next minimal integration:

```text
Add run_started/run_finished events at the narrowest available agent-loop boundary, while keeping tool-level event writing unchanged.
```

Do not wire every tool yet.
