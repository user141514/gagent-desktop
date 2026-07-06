# Architecture Convergence SOP

## Purpose

This SOP exists to stop scattered fixes from turning into technical debt.

The current problem is not only coupling. The deeper issue is that several concerns are located in the wrong layer:

- tool behavior is mixed with prompt policy;
- tool schema is edited separately from implementation;
- failure recovery is scattered between runtime code, prompt text, memory SOP, and tool descriptions;
- quality gates observe problems but do not consistently control execution;
- generated/runtime package files are being patched without a stable source-of-truth workflow.

Future changes must first classify the issue by layer, then modify the correct owner. Do not fix symptoms by editing whichever file happens to be nearby.

---

## Core principle

Every behavior must have exactly one source of truth.

If the same rule appears in code, tool schema, memory SOP, and system prompt, one of them must be declared authoritative and the others must become generated summaries, references, or runtime hints.

---

## Layer map

### Layer 0: Product goal / user-facing behavior

Owns:

- what the user experience should be;
- what counts as success;
- what behavior is unacceptable.

Does not own:

- tool implementation;
- retry algorithms;
- browser/session details;
- prompt wording hacks.

Examples:

- “History should show full conversations.”
- “Stop should return the UI to an input-ready state.”
- “Search should not return Baidu homepage links as valid results.”

Correct artifact:

- product requirement note;
- acceptance test;
- UI behavior spec.

---

### Layer 1: Capability contract

Owns:

- what a capability does;
- what it explicitly does not do;
- inputs, outputs, error categories, fallback policy;
- examples and smoke tests.

For tools, this is the most important source-of-truth layer.

Example capability split:

```text
web_search      = HTTP/source discovery; does not inspect current browser tab.
web_scan        = current rendered page inspection; does not perform search.
web_execute_js  = JavaScript execution/navigation in current tab; not a search tool.
browser_agent   = multi-step rendered browser workflow; expensive fallback only.
```

Correct artifact:

- current: `backend/tool_registry/tools/<tool>.yml`
- downstream summaries: `backend/memory/<tool>_sop.md` plus matching schema entries.

Rule:

If a tool is misunderstood by the agent, fix its capability contract before changing prompt behavior.

---

### Layer 2: Tool implementation

Owns:

- actual code behavior;
- deterministic parsing;
- API calls;
- local browser bridge mechanics;
- validation of inputs and structured errors.

Does not own:

- high-level agent strategy;
- when a task deserves deep reasoning;
- user-facing product policy;
- broad fallback philosophy beyond returning structured error data.

Current examples:

```text
backend/core/ga.py
backend/core/runtime/web_tool_errors.py
backend/core/api/app.py
```

Rules:

1. Tool functions should return structured success/error objects.
2. Tool functions should not silently switch domains or capabilities.
3. Tool functions should never return polluted results as success.
4. Tool functions should expose enough metadata for the controller to decide the next step.
5. A tool implementation change must include a minimal smoke test.

---

### Layer 3: Runtime controller / decision kernel

Owns:

- which capability to use;
- when to retry;
- when to switch route;
- when to stop repeating failed actions;
- when to escalate to user;
- when quality gates should control behavior.

Does not own:

- HTML parsing details;
- individual tool schemas;
- long natural-language SOPs.

This layer is currently underdeveloped. Many decisions are still encoded in prompt text, memory, or ad hoc fallback logic.

Future target:

```text
observation -> classify state -> choose next action -> execute -> verify -> update state
```

No module should invent its own private retry/fallback strategy if a shared controller exists.

---

### Layer 4: Quality gates

Owns:

- answer-quality constraints;
- first-principles/adversarial review;
- research workflow requirements;
- execution honesty;
- state-driven thinking;
- problem framing.

Does not own:

- direct browser mechanics;
- search engine selection;
- low-level retry code.

Current examples:

```text
backend/core/quality/answer_quality_context.py
backend/core/quality/problem_framing.py
backend/core/quality/research_workflow.py
backend/core/quality/state_driven_thinking.py
backend/core/quality/execution_honesty.py
backend/core/quality/frontier_state.py
```

Rules:

1. Quality gates should not be scattered prompt fragments.
2. If a quality gate is mandatory, it must be runtime-visible and testable.
3. Observing a defect is not enough; important gates need an enforcement path.
4. A quality module must define trigger, output, failure mode, and disable switch.

---

### Layer 5: Context / prompt assembly

Owns:

- ordering of injected blocks;
- role selection (`system` vs `user`);
- context markers;
- token/char budgets;
- final prompt shape.

Does not own:

- capability semantics;
- business logic;
- search engine selection;
- fallback policy.

Current examples:

```text
backend/assets/sys_prompt.txt
backend/core/context/adapters.py
backend/core/openai_agentmain.py
```

Rules:

1. Do not fix tool behavior by adding more prompt warnings.
2. Prompt text may summarize policy, but should not be the only implementation of policy.
3. If quality blocks are injected, the system prompt must not contradict them.
4. Context assembly must record which blocks were injected and how many chars they used.

---

### Layer 6: UI / API boundary

Owns:

- frontend state machine;
- API endpoints;
- session/history display;
- stop/cancel behavior;
- user feedback signals.

Does not own:

- model reasoning policy;
- tool parsing;
- search fallback;
- quality-gate internals.

Current examples:

```text
backend/core/api/app.py
packages/gagent-desktop frontend source when available
dist/assets/*.js only as generated output, not preferred source
```

Rules:

1. UI state must not infer backend state from silence if an explicit event can be sent.
2. Viewing history and restoring agent context are separate operations.
3. Stop/cancel must produce a terminal event or timeout fallback.

---

### Layer 7: Generated/runtime artifacts

Owns:

- packaged npm install output;
- built frontend assets;
- copied backend snapshot;
- generated schemas.

Does not own:

- durable source-of-truth changes.

Rules:

1. Prefer changing source repo over installed package.
2. If the installed package must be hotfixed, document the change and later port it to source.
3. Do not treat `dist/assets/*.js` as the canonical frontend source.
4. Every hotfix needs a “port-back required” note.

---

## Change classification protocol

Before modifying anything, classify the request:

```text
1. Is this a product behavior issue?
2. Is this a capability contract issue?
3. Is this a tool implementation issue?
4. Is this a runtime controller issue?
5. Is this a quality-gate issue?
6. Is this a prompt/context assembly issue?
7. Is this a UI/API state issue?
8. Is this only a generated/runtime artifact issue?
```

Then apply the rule:

```text
Fix the lowest layer that owns the incorrect behavior.
Update higher-layer docs/prompts only to reflect the corrected source of truth.
```

Example:

```text
Problem: web_search returns Baidu homepage as search result.
Wrong fix: tell the model “do not use Baidu” in prompt only.
Correct fix:
  Layer 2: filter polluted results in web_search implementation.
  Layer 1: update web_search contract.
  Layer 5: update prompt/schema summary only if needed.
```

---

## File ownership rules

### `backend/core/ga.py`

Owns:

- concrete tool implementations;
- local browser bridge calls;
- basic structured tool returns.

Should not own:

- high-level policy;
- long SOP text;
- broad agent reasoning behavior.

Large future action:

Split this file into smaller modules:

```text
backend/core/tools/search.py
backend/core/tools/browser_scan.py
backend/core/tools/browser_js.py
backend/core/tools/code_run.py
backend/core/tools/file_ops.py
```

---

### `backend/assets/tools_schema*.json`

Owns:

- tool interface exposed to the model.

Should not be hand-divergent.

Rule:

English and Chinese schemas must stay semantically identical.

Future action:

Generate both files from a tool registry.

---

### `backend/memory/*_sop.md`

Owns:

- operational norms and recovery procedures.

Should not own:

- behavior that must be enforced in code;
- schema definitions;
- critical safety constraints without runtime support.

---

### `backend/assets/sys_prompt.txt`

Owns:

- concise global behavior principles.

Should not own:

- detailed tool contracts;
- fallback algorithms;
- long quality rubrics;
- implementation-specific fixes.

---

### `backend/core/quality/*`

Owns:

- quality triggers;
- quality blocks;
- quality scoring/checking;
- quality enforcement or repair if implemented.

Should not own:

- web search mechanics;
- browser behavior;
- file operation semantics.

---

## Anti-patterns

### Anti-pattern 1: Prompt patching a code bug

Symptom:

```text
The tool returns polluted data, so we add a prompt warning.
```

Fix:

```text
Reject polluted data in code. Then update the prompt only as documentation.
```

---

### Anti-pattern 2: Schema says one thing, implementation does another

Symptom:

```text
schema says web_search is HTTP-only, but code opens a browser for normal engines.
```

Fix:

```text
Make implementation match schema or change schema. Never leave them divergent.
```

---

### Anti-pattern 3: Fallback changes capability class

Symptom:

```text
web_search fails -> web_scan recommended.
```

This is wrong because search and page inspection are different capabilities.

Fix:

```text
web_search fails -> try another HTTP search engine -> report network blocker -> only use browser if rendered search is explicitly needed.
```

---

### Anti-pattern 4: Generated asset becomes source of truth

Symptom:

```text
Patch dist/assets/index-*.js directly.
```

Fix:

```text
Find source frontend. If hotfixing dist is unavoidable, write a port-back note.
```

---

### Anti-pattern 5: More modules instead of owner cleanup

Symptom:

```text
Add another guard, SOP, prompt block, or wrapper for every failure.
```

Fix:

```text
First ask which existing layer should own the behavior. Move logic there.
```

---

## Required change template

Every future non-trivial change must answer:

```text
CHANGE TITLE:
USER-FACING PROBLEM:
LAYER OWNER:
WRONG CURRENT OWNER:
FILES TO CHANGE:
FILES NOT TO CHANGE:
SOURCE OF TRUTH AFTER CHANGE:
SMOKE TEST:
ROLLBACK:
PORT-BACK REQUIRED: yes/no
```

Example:

```text
CHANGE TITLE: Decouple web_search from browser scan
USER-FACING PROBLEM: search failure opens/pollutes browser and returns Baidu page
LAYER OWNER: Layer 1 capability contract + Layer 2 tool implementation
WRONG CURRENT OWNER: prompt/memory/browser fallback
FILES TO CHANGE:
  - backend/core/ga.py
  - backend/core/runtime/web_tool_errors.py
  - backend/assets/tools_schema*.json
  - backend/memory/web_search_tool_sop.md
FILES NOT TO CHANGE:
  - sys_prompt.txt unless only summarizing policy
  - frontend unless UI behavior changes
SOURCE OF TRUTH AFTER CHANGE: web_search_tool_sop + ga.py implementation
SMOKE TEST: web_search('OpenAI API docs', engine='auto') returns non-search-engine result
ROLLBACK: revert changed files
PORT-BACK REQUIRED: yes, if applied in installed package
```

---

## Priority rules for debt reduction

### P0: Stop wrong ownership

Fix behaviors that are in the wrong layer and causing repeated edits.

Examples:

- search fallback policy inside prompt;
- browser scan used as search fallback;
- quality module disabled despite being the correct owner;
- history view coupled to context restore.

### P1: Create source-of-truth registries

Create structured registries for:

- tools;
- quality gates;
- runtime policies;
- UI state machines.

### P2: Generate downstream artifacts

Generate or synchronize:

- tools schema EN/CN;
- SOP index;
- prompt summaries;
- smoke tests.

### P3: Remove duplicates

Delete or deprecate duplicated policy fragments after the source of truth exists.

---

## Immediate convergence backlog

### 1. Tool registry

Current source-of-truth files:

```text
backend/tool_registry/tools/web_search.yml
backend/tool_registry/tools/web_scan.yml
backend/tool_registry/tools/web_execute_js.yml
backend/tool_registry/tools/browser_agent.yml
```

Generate or validate:

```text
backend/assets/tools_schema.json
backend/assets/tools_schema_cn.json
backend/memory/web_search_tool_sop.md
```

### 2. Quality gate registry

Create a table of:

```text
name, default_enabled, trigger, injected_role, max_chars, owner, enforcement_level
```

### 3. Context assembly policy

Define:

```text
which blocks are system-level;
which blocks are user-level;
priority order;
char budgets;
when to drop optional blocks.
```

### 4. Runtime controller policy

Define central fallback rules:

```text
tool failure -> classify -> retry same class if safe -> switch same capability -> escalate -> stop
```

No individual module should invent fallback chains independently.

### 5. Port-back discipline

If editing installed package, record:

```text
changed file;
reason;
source repo file to update later;
verification;
rollback.
```

---

## Minimal rule for future work

Before every fix, ask:

```text
Am I fixing the behavior at its owner layer, or am I adding another patch above the real owner?
```

If the answer is “patch above the owner”, stop and relocate the change.
