# Eval Registry

Owner layer: Layer 4 quality gates plus Layer 3 runtime observability.

This is the first internal evaluation harness for gagent-desktop. It runs deterministic eval cases from `cases/*.json`, executes supported web tool boundary paths, reads `runtime_ledger` JSONL events, and scores tool behavior, ledger completeness, and final-answer consistency.

Supported executable targets:

```text
web_search
web_scan
web_execute_js
browser_agent contract
browser_agent handler stub
agent_loop runtime mapper
```

`web_scan` and `web_execute_js` use a fake local browser bridge but still call the real `GenericAgentHandler` methods, so their boundary evals are offline, deterministic, and covered by handler-level `runtime_ledger` events. `browser_agent` has a registry contract eval plus a stubbed handler eval; the real high-cost browser/LLM workflow is not launched.

Final-answer scoring is rule-based and deterministic. It checks that a successful tool result is not described as a failure, that successful source URLs are surfaced, and that structured failures are not reported as successful findings.

`agent_loop runtime mapper` is a local fake-client/fake-handler path through the real `agent_runner_loop`. It verifies that runtime mapper turn and tool events are emitted, started/completed LLM turns stay balanced, and `agent_runner_loop(runtime_ledger_run_id=...)` writes turn-tagged `runtime_ledger` tool events.

It intentionally does not use an LLM judge, external benchmarks, CTest, PyYAML, SWE-bench, GAIA, Judgeval, Kiln, or frontend code.

Run:

```text
PYTHONUTF8=1 ./python-runtime/python.exe backend/eval_registry/validate_eval_registry.py
PYTHONUTF8=1 ./python-runtime/python.exe backend/eval_registry/tests/smoke_eval_registry.py
PYTHONUTF8=1 ./python-runtime/python.exe backend/eval_registry/run_eval_cases.py
```

Source of truth:

```text
backend/eval_registry/cases/*.json
```

Runtime artifact:

```text
backend/eval_registry/results/latest_eval_report.json
```
