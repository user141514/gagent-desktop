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

Checks:

```text
PYTHONUTF8=1 ./python-runtime/python.exe backend/runtime_ledger/validate_runtime_ledger.py
PYTHONUTF8=1 ./python-runtime/python.exe backend/runtime_ledger/tests/smoke_runtime_ledger.py
```

CTest note: this package currently has no CMake project, so Python smoke tests are the source of truth. If CMake is introduced later, wrap these commands with add_test().
