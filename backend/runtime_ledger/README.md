# Runtime Ledger

Owner: Layer 3 runtime controller / observability.

Runtime Ledger records factual agent trajectories as JSONL events. It is code, not prompt policy.

Files:

```text
ledger.py
validate_runtime_ledger.py
tests/smoke_runtime_ledger.py
runs/*.jsonl
```

Event types:

```text
run_started, context_injected, tool_call, tool_result, decision,
quality_gate, experience_candidate, smoke_test, file_change, run_finished
```

Current direct handler integrations:

```text
agent_runner_loop(runtime_ledger_run_id=...)
OpenAIOrchestratedAgent.run
GenericAgentHandler.do_web_search
GenericAgentHandler.do_web_scan
GenericAgentHandler.do_web_execute_js
GenericAgentHandler.do_browser_agent
```

`agent_runner_loop` integration is opt-in at the loop boundary. Classic `agentmain.py` passes its task `run_id`, so normal classic-agent runs record `run_started`, per-tool `tool_call`/`tool_result` with `turn`, and `run_finished`. OpenAI orchestrated runs write the same event family from their run and streamed tool-event lifecycle.

Checks:

```text
PYTHONUTF8=1 ./python-runtime/python.exe backend/runtime_ledger/validate_runtime_ledger.py
PYTHONUTF8=1 ./python-runtime/python.exe backend/runtime_ledger/tests/smoke_runtime_ledger.py
```

CTest note: this package currently has no CMake project, so Python smoke tests are the source of truth. If CMake is introduced later, wrap these commands with add_test().
