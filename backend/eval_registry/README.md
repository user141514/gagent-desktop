# Eval Registry

Owner layer: Layer 4 quality gates plus Layer 3 runtime observability.

This is the first internal evaluation harness for gagent-desktop. It runs deterministic eval cases from `cases/*.json`, executes supported web tool boundary paths, reads `runtime_ledger` JSONL events, and scores tool behavior plus ledger completeness.

Supported executable targets:

```text
web_search
web_scan
web_execute_js
```

`web_scan` and `web_execute_js` use a fake local browser bridge in the harness, so their boundary evals are offline and deterministic. `browser_agent` remains contract-only in step 1 because it is a high-cost rendered workflow.

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
