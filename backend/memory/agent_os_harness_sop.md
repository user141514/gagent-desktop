# Agent OS / Harness SOP

## Purpose

This SOP defines the development philosophy for gagent-desktop as an Agent OS / Harness project.

It absorbs these ideas:

1. YAGNI instinct / ponytail: prefer the smallest change that works.
2. Filesystem as interface: behavior is organized by directories and files, not hidden registration magic.
3. Loop engineering: agent execution is a designed loop with audit, context, and cost controls.
4. Harness first: memory, skills, safety, context, tools, and policy matter more than raw model capability.

It explicitly excludes one idea for now:

```text
No default multi-agent cross-review requirement.
```

Reason: multi-agent review can add cost and complexity before the single-agent harness is stable. Use one-agent role separation or manual audit first. Multi-agent review can be added later as an optional policy, not as a default dependency.

---

## Core doctrine

```text
Less by default.
Files are the interface.
Loops are engineered.
Harness owns behavior.
Prompt is generated policy, not the source of truth.
```

---

## 1. YAGNI instinct: default to the laziest working solution

Agent systems naturally overbuild. A coding agent tends to add wrappers, registries, abstractions, retries, config switches, and docs even when the correct fix is a two-line owner-layer change.

Therefore every non-trivial change must pass the Minimal Action Gate.

### Minimal Action Gate

Before implementation, answer:

```text
1. What is the smallest user-visible failure?
2. What is the lowest owner layer that can fix it?
3. What is the smallest file set that can fix it?
4. What tempting abstraction should not be added yet?
5. What smoke test proves the fix?
```

### YAGNI rules

- Do not add a framework when a function is enough.
- Do not add a registry until at least two consumers need the same source of truth.
- Do not add an environment flag unless rollback or experiment control is needed.
- Do not add prompt text to compensate for broken implementation.
- Do not add a new tool if an existing tool can satisfy the contract with a small fix.
- Do not add a new agent role for what a deterministic check can do.

### Accepted shortcuts

A minimal solution is allowed when it is explicit:

```text
This is a narrow fix.
It changes only the owner layer.
It has a smoke test.
It does not create hidden policy drift.
```

### Rejected shortcuts

A shortcut is not allowed when it:

- hides a broken contract;
- moves behavior into prompt only;
- patches generated assets as source of truth;
- skips the smoke test;
- increases future change radius.

---

## 2. Filesystem as interface

The project should become understandable by inspecting directories.

A future maintainer or agent should be able to answer:

```text
Where are tools defined?
Where are quality gates defined?
Where are runtime policies defined?
Where are skills stored?
Where are smoke tests stored?
Where are hotfixes recorded?
```

without reading the whole codebase.

### Current canonical locations

```text
backend/tool_registry/tools/*.yml          # tool capability contracts
backend/tool_registry/policies/*.yml       # runtime fallback policies
backend/tool_registry/tests/*.py           # tool smoke tests
backend/quality_registry/gates.yml         # quality gate registry
backend/memory/*_sop.md                    # operational procedures
backend/memory/hotfix_portback_ledger.md   # installed-package hotfix tracking
backend/memory/convergence_checklist.md    # checks before claiming completion
```

### Naming conventions

- Tool contract: `backend/tool_registry/tools/<tool_name>.yml`
- Tool SOP: `backend/memory/<tool_name>_tool_sop.md`
- Runtime policy: `backend/tool_registry/policies/<policy_name>.yml`
- Quality registry: `backend/quality_registry/gates.yml`
- Process SOP: `backend/memory/<process_name>_sop.md`
- Smoke test: `backend/tool_registry/tests/smoke_<domain>.py`

### Source-of-truth rule

```text
If a behavior is important, it must have one canonical file.
```

Examples:

```text
Tool behavior          -> tool_registry/tools/<tool>.yml
Tool implementation    -> backend/core/... implementation file
Tool model-facing API  -> tools_schema*.json, eventually generated
Quality gate behavior  -> quality_registry/gates.yml + quality module
Development process    -> development_workflow_sop.md
Architecture ownership -> architecture_convergence_sop.md
```

### Downstream artifact rule

Prompt text, schema text, README text, and memory summaries may describe source-of-truth behavior. They must not invent separate behavior.

---

## 3. Loop engineering

An agent is not a single prompt. It is a loop:

```text
input -> classify -> retrieve context -> choose action -> execute -> observe -> audit -> update state -> decide stop/continue
```

Each loop needs explicit controls.

### Standard loop checkpoints

#### loop-init

At task start, classify:

```text
- user-facing goal
- owner layer
- expected output
- risk class
- needed tools
- smoke test
```

#### loop-context

Before tool/model execution, decide:

```text
- required context
- optional context
- context budget
- stale context to drop
- source-of-truth files to read
```

#### loop-action

Before acting, state:

```text
- action type
- target file/resource
- expected state transition
- rollback/no-op option
```

#### loop-audit

After action, check:

```text
- did the action actually happen?
- did it affect the owner layer?
- did it create schema/SOP/prompt drift?
- did it pass smoke test?
```

#### loop-cost

Track at least lightweight cost signals:

```text
- tool calls used
- context blocks injected
- large files read
- external network calls
- retries/failures
```

#### loop-stop

Stop only when:

```text
- owner-layer behavior is fixed or blocker is explicit;
- smoke test passed or external failure is classified;
- rollback is known;
- source-of-truth and summaries are not contradictory.
```

---

## 4. Harness first

A model is replaceable. The harness is the durable asset.

The harness owns:

```text
- memory policy
- skill loading
- tool contracts
- runtime fallback
- safety gates
- quality gates
- context assembly
- execution honesty
- telemetry
- smoke tests
- rollback discipline
```

The model should not be expected to remember these rules from raw prompt text. The harness must expose them through registries, policies, validators, and tests.

### Harness layers

```text
Layer 0: product behavior
Layer 1: capability contracts
Layer 2: tool implementation
Layer 3: runtime controller
Layer 4: quality gates
Layer 5: context / prompt assembly
Layer 6: UI / API boundary
Layer 7: generated/runtime artifacts
```

See:

```text
backend/memory/architecture_convergence_sop.md
```

---

## 5. Prompt generation over hand-written prompt sprawl

Hand-written prompt fragments should not become independent sources of truth.

Future direction:

```text
registry/policy/SOP -> generated compact prompt blocks -> injected at runtime
```

Do not manually duplicate long rules across:

```text
sys_prompt.txt
tools_schema.json
tools_schema_cn.json
memory/*.md
quality modules
```

If duplication is unavoidable in the installed package, record it in the hotfix ledger and port it back to a generated source workflow.

---

## 6. Skill loading principle

Prefer on-demand skill files over all-capability injection.

A skill should be:

```text
- self-contained;
- stored as a readable file;
- activated by explicit triggers;
- limited in scope;
- cheap enough to inject only when needed;
- connected to owner-layer behavior or a workflow.
```

Skill files should not be a dumping ground for policy that belongs in runtime code or registries.

---

## 7. No default multi-agent review

This project does not currently require multiple agents to review every critical change.

Use instead:

```text
- deterministic validators;
- smoke tests;
- one-agent role shift: implement -> self-audit -> summarize evidence;
- manual human audit when needed.
```

Multi-agent review may be useful later, but it should be opt-in and justified by failure data.

---

## Required development ritual

Before any non-trivial change, read or apply:

```text
backend/memory/architecture_convergence_sop.md
backend/memory/development_workflow_sop.md
backend/memory/agent_os_harness_sop.md
```

Then fill:

```text
CHANGE TITLE:
USER-FACING PROBLEM:
OWNER LAYER:
MINIMAL ACTION:
SOURCE OF TRUTH:
FILES TO CHANGE:
FILES NOT TO CHANGE:
SMOKE TEST:
ROLLBACK:
PORT-BACK REQUIRED:
```

---

## Immediate application priorities

### P0

- Use Minimal Action Gate in every change.
- Keep tool registry and quality registry passing.
- Keep web_search / web_scan / web_execute_js / browser_agent boundaries explicit.
- Maintain hotfix port-back ledger.

### P1

- Generate tools schema from tool registry.
- Generate compact prompt summaries from registries.
- Add context budget tracking to context assembly.
- Add basic loop-cost telemetry.

### P2

- Add runtime controller policy as executable code, not just YAML.
- Add a harness dashboard or report command.
- Add optional multi-agent review only if deterministic checks are insufficient.

---

## Minimal rule

```text
Do less, but do it at the owner layer with a test.
```
