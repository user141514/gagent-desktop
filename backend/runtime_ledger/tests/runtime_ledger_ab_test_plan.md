# Runtime Ledger Minimal Integration A/B Test Plan

## Purpose

Test whether minimal Runtime Ledger integration improves observability without degrading answer quality.

This is not a model-obedience test. The goal is to compare:

```text
A. Before integration: answer behavior only; no structured runtime trajectory expected.
B. After minimal integration: same answer behavior plus factual JSONL events.
```

The first integration target should be narrow:

```text
web_search path only, then optionally web_scan and web_execute_js.
```

Do not wire every tool in the first pass.

---

## CTest decision

Current package has no CMake project:

```text
No CMakeLists.txt
No CTestTestfile.cmake
```

Therefore CTest is not the correct first test runner. Use Python validator/smoke tests now:

```text
PYTHONUTF8=1 ./python-runtime/python.exe backend/runtime_ledger/validate_runtime_ledger.py
PYTHONUTF8=1 ./python-runtime/python.exe backend/runtime_ledger/tests/smoke_runtime_ledger.py
```

If the source repository later adopts CMake, wrap the Python tests with `add_test()`. Do not introduce CMake solely for Runtime Ledger.

---

## Experiment protocol

Use the same model, same app version, same network/proxy condition, and same prompt set.

### Phase A: baseline / no integration

1. Ensure Runtime Ledger is not wired into `ga.py` or `openai_agentmain.py`.
2. Run the test questions below in order.
3. Save each final answer manually to:

```text
backend/runtime_ledger/tests/ab_results/baseline_answers.md
```

4. Check that no new JSONL run files are created by normal Q&A.

Expected result:

```text
Answers may be good or bad, but there is no structured trajectory data.
```

### Phase B: minimal integration

1. Wire only the smallest path first:

```text
web_search tool_call -> web_search tool_result -> optional decision event
```

2. Run the same questions again.
3. Save each final answer to:

```text
backend/runtime_ledger/tests/ab_results/ledger_answers.md
```

4. Save/copy the generated JSONL run files.

Expected result:

```text
Answer quality should not degrade materially.
Ledger should record tool_call/tool_result/decision for tool-using questions.
```

---

## Test questions

### Q1: no-tool boundary / YAGNI

```text
用两句话解释 web_search 和 web_scan 的区别。不要调用工具，不要展开架构。
```

Expected behavior:

- Should answer directly.
- Should not call web_search or web_scan.
- After integration, ledger may record run_started/run_finished only, or no event if only tool-level integration is active.

Primary signal:

```text
No over-instrumentation and no unnecessary tool call.
```

---

### Q2: ordinary HTTP search success path

```text
查一下 OpenAI API docs 的官方入口，给出 2 个标题和 URL。不要打开浏览器，不要使用 web_scan。
```

Expected behavior:

- Should use `web_search`, preferably `engine=auto` or `engine=bing`.
- Must not use Baidu.
- Must not use `web_scan`, `web_execute_js`, or `browser_agent` for ordinary search.
- If search succeeds, answer with source candidates.
- If search fails, return structured blocker and do not fake success.

Ledger expectation after integration:

```text
run_started optional
tool_call: web_search
tool_result: web_search, status success/error
decision optional if error
run_finished optional
```

---

### Q3: GitHub/API failure path

```text
搜索 yobot GitHub code，找可能的仓库候选。如果 GitHub/API/网络失败，明确报告失败链路。不要把 web_search 失败 fallback 到 web_scan。
```

Expected behavior:

- Should not treat GitHub timeout as reason to inspect current browser tab.
- Should try same-capability search fallback if available.
- Should report structured network/search failure if all HTTP paths fail.
- Must not return Baidu homepage or search engine homepage as success.

Ledger expectation after integration:

```text
tool_call: web_search
tool_result: status error/success
decision if error: switch_same_capability or stop_with_blocker
forbidden_actions should include web_scan/browser_agent if decision event is implemented
```

---

### Q4: rendered-page inspection boundary

```text
只检查当前浏览器标签页是什么页面，不要执行搜索，不要导航。
```

Expected behavior:

- Should use `web_scan(tabs_only=True)` or equivalent current-tab inspection.
- Should not call `web_search`.
- Should not navigate.

Ledger expectation after integration if web_scan is wired:

```text
tool_call: web_scan
tool_result: web_scan
No search_url/results-shaped data required
```

If first minimal integration wires only web_search, this question is scored for answer/tool behavior only, not ledger completeness.

---

### Q5: JavaScript navigation boundary

```text
把当前浏览器标签页导航到 https://example.com，然后报告新 URL。不要搜索。
```

Expected behavior:

- Should use `web_execute_js` or explicit browser navigation path.
- Should not call `web_search`.
- Should not trigger the historical `set.get` navigation bug.

Ledger expectation after integration if web_execute_js is wired:

```text
tool_call: web_execute_js
tool_result: navigated true or structured browser-bridge failure
```

If first minimal integration wires only web_search, score answer/tool behavior only.

---

### Q6: owner-layer diagnosis

```text
web_search 失败后推荐 web_scan，这个设计是否合理？请按 owner layer 判断，并给出最小修复点。
```

Expected behavior:

- Should identify capability-class mismatch.
- Should say this belongs to runtime fallback policy / decision layer, not prompt-only fix.
- Should mention tool contract and smoke test.
- Should not propose broad refactor as first action.

Ledger expectation:

- No tool needed unless it reads existing SOP/registry.
- If it reads, ledger should show file_read only after broader wiring; not required for first minimal web_search integration.

---

### Q7: verification discipline after change

```text
假设你刚刚改了 web_search fallback，请列出最小验证命令。不要改代码。
```

Expected behavior:

Must include at least:

```text
backend/tool_registry/validate_tool_registry.py
backend/tool_registry/tests/smoke_web_tools.py
backend/runtime_ledger/validate_runtime_ledger.py
backend/runtime_ledger/tests/smoke_runtime_ledger.py
```

Should not claim tests were run.

---

### Q8: ledger usefulness check

```text
如果一次工具调用失败，runtime_ledger 最少应该记录哪些字段，才能让后续 experience_registry 复用这次失败？
```

Expected behavior:

Should include:

```text
run_id
event_type
task
tool
args
result.status
result.msg/error_category
decision action/next_tool/forbidden_actions
experience_ids_used or experience_candidate
smoke_tests
final_status
```

No tool required.

---

## Scoring

Score each answer out of 100.

### A. Answer quality score: 60 points

```text
Correctness: 15
  - technically correct, no fake facts, no fake verification

Owner-layer reasoning: 10
  - identifies whether issue belongs to tool contract, implementation, runtime controller, quality gate, context, or UI/API

Tool selection: 10
  - uses the correct tool class or explicitly avoids tools when not needed

Failure handling: 15
  - no fake success, no Baidu/search-homepage pollution, reports blockers clearly, avoids repeated same-input retry

YAGNI/minimality: 5
  - does not propose broad refactor when minimal owner-layer fix is enough

Actionability: 5
  - gives clear next step or verification command
```

### B. Ledger score: 40 points

Baseline/no-integration expected score is usually 0 or N/A. After integration, score tool-using questions.

```text
Run identity: 5
  - run_id present and stable across events

Tool trace: 10
  - tool_call and tool_result recorded with tool name, args, result status

Failure trace: 10
  - failed result includes msg/error category enough for experience reuse

Decision trace: 10
  - decision event records action, reason/next_tool, and forbidden_actions when applicable

Data hygiene: 5
  - no excessive raw content, no secrets, no huge payloads, JSONL valid
```

### Total score

```text
Total = Answer quality score + Ledger score
```

For no-tool questions Q1/Q6/Q7/Q8, ledger score can be marked N/A unless run-level instrumentation is active.

---

## Comparison criteria

### Pass condition for minimal integration

After minimal web_search integration:

```text
1. Q2/Q3 ledger score >= 25/40
2. Q1 answer still does not call tools
3. Average answer quality delta >= -5 compared with baseline
4. No question introduces Baidu/search-homepage fake success
5. JSONL validates and can be summarized by summarize_run()
```

### Fail conditions

```text
1. Integration changes answer behavior materially without reason
2. Ledger records invalid JSONL
3. Tool args/results are missing from tool-using questions
4. web_search failure still routes to web_scan for ordinary search
5. Ledger stores huge raw page/text payloads or sensitive data
6. Tests require live network as the only proof of correctness
```

---

## Suggested manual score table

```text
Question | Phase | Answer Quality /60 | Ledger /40 | Total | Notes
Q1       | A     |                   | N/A        |       |
Q1       | B     |                   | N/A        |       |
Q2       | A     |                   | 0/N/A      |       |
Q2       | B     |                   |            |       |
Q3       | A     |                   | 0/N/A      |       |
Q3       | B     |                   |            |       |
Q4       | A     |                   | 0/N/A      |       |
Q4       | B     |                   |            |       |
Q5       | A     |                   | 0/N/A      |       |
Q5       | B     |                   |            |       |
Q6       | A     |                   | N/A        |       |
Q6       | B     |                   | N/A        |       |
Q7       | A     |                   | N/A        |       |
Q7       | B     |                   | N/A        |       |
Q8       | A     |                   | N/A        |       |
Q8       | B     |                   | N/A        |       |
```

---

## Minimal integration target after this plan

First code integration should only add event writes around `web_search` execution path:

```text
before web_search: tool_call
after web_search: tool_result
on error after enrich_web_tool_result: decision or failure metadata
```

Do not wire every tool yet.
