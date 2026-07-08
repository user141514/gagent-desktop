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
agent_loop runtime mapper success/failure
```

`web_scan` and `web_execute_js` use a fake local browser bridge but still call the real `GenericAgentHandler` methods, so their boundary evals are offline, deterministic, and covered by handler-level `runtime_ledger` events. `browser_agent` has a registry contract eval plus a stubbed handler eval; the real high-cost browser/LLM workflow is not launched.

Final-answer scoring is rule-based and deterministic. It checks that a successful tool result is not described as a failure, that successful source URLs are surfaced, and that structured failures are not reported as successful findings.

`agent_loop runtime mapper` is a local fake-client/fake-handler path through the real `agent_runner_loop`. It verifies that runtime mapper turn and tool events are emitted, started/completed LLM turns stay balanced, and `agent_runner_loop(runtime_ledger_run_id=...)` writes turn-tagged `runtime_ledger` tool events. It covers both success and structured web_search failure paths.

Agent-loop eval reports also include a read-only `observability` summary that joins RuntimeHost events with `runtime_ledger` events for the same run id.

It intentionally does not use an LLM judge, external benchmarks, CTest, PyYAML, SWE-bench, GAIA, Judgeval, Kiln, or frontend code.

Run:

```text
PYTHONUTF8=1 ./python-runtime/python.exe backend/eval_registry/validate_eval_registry.py
PYTHONUTF8=1 ./python-runtime/python.exe backend/eval_registry/tests/smoke_eval_registry.py
PYTHONUTF8=1 ./python-runtime/python.exe backend/eval_registry/run_convergence_checks.py
PYTHONUTF8=1 ./python-runtime/python.exe backend/eval_registry/run_convergence_checks.py --full
npm.cmd run test:convergence
PYTHONUTF8=1 ./python-runtime/python.exe backend/eval_registry/run_eval_cases.py
PYTHONUTF8=1 ./python-runtime/python.exe backend/eval_registry/score_functionality.py
PYTHONUTF8=1 ./python-runtime/python.exe backend/eval_registry/score_functionality.py --refresh
PYTHONUTF8=1 ./python-runtime/python.exe backend/eval_registry/score_functionality.py --refresh --strict
npm.cmd run test:convergence:full
```

`score_functionality.py --refresh` suppresses successful child-command logs and prints one JSON score report. If a refresh child command fails, its captured stdout/stderr is printed to stderr for debugging.
`score_functionality.py --self-test` includes a local failing child command to verify that refresh failure output is retained.
Use `--strict` when the command is acting as a completion gate; `needs_work` remains exit 0 without `--strict` for advisory reports.
Use `--results-dir <dir> --no-write` to score isolated report fixtures without touching the default latest score artifact; `--results-dir` requires `--no-write`.
`--results-dir` is intentionally incompatible with `--refresh`; refresh writes the default latest reports.
Score reports include an `evidence` object with the results directory, input report file status, Git HEAD/dirty state, Python executable, and non-secret E2E env switches.
Skipped optional OpenAI/browser_agent E2E reports count as `needs_work`; full completion requires enabling the opt-in E2E env vars before running `--refresh --strict`.
`run_convergence_checks.py` validates the score JSON, runner mode flags, expected component names/weights/status fields, total/max_total/status/blockers consistency, and required `evidence` fields, then prints it on success so baseline runs expose current blockers instead of only saying `ok`; `--full` also runs the baseline validators before strict scoring.
Strict/full convergence also requires `evidence.source_git.dirty` to be false.
The expected component weights are exported by `score_functionality.py`; score totals and the convergence runner both use that source of truth instead of keeping second copies.
The runner self-test fixture is also generated from those weights so test samples do not drift from the score contract.

Optional OpenAI orchestrated SDK smoke:

```text
PYTHONUTF8=1 ./python-runtime/python.exe -m pip install --target backend/temp/e2e_deps -r backend/requirements-e2e.txt
PYTHONUTF8=1 ./python-runtime/python.exe backend/eval_registry/tests/smoke_openai_orchestrated_e2e.py
GAGENT_E2E_DEPS=backend/temp/e2e_deps GAGENT_RUN_OPENAI_E2E=1 PYTHONUTF8=1 ./python-runtime/python.exe backend/eval_registry/tests/smoke_openai_orchestrated_e2e.py
PYTHONUTF8=1 ./python-runtime/python.exe backend/eval_registry/tests/smoke_browser_agent_e2e.py
GAGENT_E2E_DEPS=backend/temp/e2e_deps GAGENT_RUN_BROWSER_AGENT_E2E=1 PYTHONUTF8=1 ./python-runtime/python.exe backend/eval_registry/tests/smoke_browser_agent_e2e.py
```

The default OpenAI/browser_agent commands must structured-skip without network/API access. The opt-in commands are real e2e paths and require their SDKs, browser/runtime dependencies, and API/network access.
`GAGENT_E2E_DEPS` is explicit because the packaged Windows `python-runtime/python313._pth` ignores `PYTHONPATH`.
`browser_agent` also requires browser LLM credentials such as `OPENAI_API_KEY` or `OPENAI_ADMIN_KEY` unless the handler supplies an API key.
DeepSeek thinking variants are mapped to a browser-use-compatible DeepSeek chat model for `browser_agent` because the browser loop requires structured tool calls.

Source of truth:

```text
backend/eval_registry/cases/*.json
backend/eval_registry/tests/smoke_openai_orchestrated_e2e.py
backend/eval_registry/tests/smoke_browser_agent_e2e.py
backend/eval_registry/score_functionality.py
backend/requirements-e2e.txt
```

Runtime artifact:

```text
backend/eval_registry/results/latest_eval_report.json
backend/eval_registry/results/latest_openai_e2e_report.json
backend/eval_registry/results/latest_browser_agent_e2e_report.json
backend/eval_registry/results/latest_functionality_score.json
```
