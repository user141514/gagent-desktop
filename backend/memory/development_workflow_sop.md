# Development Workflow SOP

## Purpose

This SOP is the required workflow for non-trivial gagent-desktop changes. The goal is to stop fixes from scattering across prompt, schema, SOP, runtime code, UI, and packaged artifacts.

Every change must start here:

```text
Problem ownership -> owner layer -> source of truth -> minimal implementation -> smoke test -> doc/schema sync -> audit
```

Do not edit "where it is convenient." Edit the layer that owns the behavior.

## Change Template

```text
CHANGE TITLE:
USER-FACING PROBLEM:
LAYER OWNER:
WRONG CURRENT OWNER:
SOURCE OF TRUTH:
FILES TO CHANGE:
FILES NOT TO CHANGE:
SMOKE TEST:
ROLLBACK:
PORT-BACK REQUIRED:
```

## 1. Development Flow Overview

1. Classify the problem against `architecture_convergence_sop.md`.
2. Pick the lowest owner layer that actually owns the behavior.
3. Name the source of truth before editing.
4. Make the smallest source change that fixes the owner-layer problem.
5. Add or run one smoke test that fails for the wrong behavior.
6. Sync downstream schema, SOP, prompt summary, or package metadata only as summaries.
7. Audit the diff for wrong-layer edits, generated artifact edits, and missing rollback.

## 2. Bug Fix Flow

- State the user-visible failure and unacceptable behavior.
- Identify whether the bug is product, capability contract, tool implementation, runtime controller, quality gate, prompt/context, UI/API, or generated artifact.
- Fix the shared owner path, not one caller.
- Keep prompt changes as summaries only.
- Add the smallest regression smoke test.
- Rollback must be a clean file revert or a documented runtime flag.

## 3. Feature Change Flow

- Define the user-facing behavior and success contract.
- Decide whether the feature belongs in an existing owner layer.
- Reuse existing handlers, registries, schemas, and tests before adding modules.
- Add source-of-truth contract first, implementation second, generated summaries last.
- Do not add future extension points until a second real user need exists.

## 4. Tool Change Flow

Source of truth:

```text
backend/tool_registry/tools/<tool>.yml
```

Required order:

1. Update the tool registry contract.
2. Update implementation only if behavior changes.
3. Sync `tools_schema.json` and `tools_schema_cn.json`.
4. Sync relevant SOP summary.
5. Run registry lint and tool smoke tests.

Prompt text must not be the only place where tool behavior exists.

## 5. Quality Gate Change Flow

Source of truth:

```text
backend/quality_registry/gates.yml
```

Source of truth must name:

- trigger;
- default enabled state;
- injected role or runtime path;
- output;
- failure mode;
- disable switch;
- enforcement level.

If a gate only observes but does not enforce, document it as advisory. Do not describe advisory checks as mandatory.

## 6. UI/API State Change Flow

- UI state belongs to Layer 6, not prompt or tool code.
- API state must expose explicit events for start, progress, stop, failure, and terminal completion when the UI depends on them.
- History display and agent context restore are separate flows.
- Do not patch `dist/assets/*.js` as source. Use source UI files when available.

## 7. Hotfix -> Source Port-Back Flow

When an installed package hotfix is unavoidable:

```text
HOTFIX FILE:
REASON:
SOURCE FILE TO PORT BACK:
VERIFICATION:
ROLLBACK:
PORT-BACK OWNER:
```

Port-back is required before the hotfix can be considered complete. Generated/runtime artifacts are not durable source of truth.

## 8. Smoke Test Requirements

Every non-trivial behavior change needs one runnable smoke test.

The smoke test must:

- exercise the owner-layer behavior;
- distinguish logic failure from network or browser bridge failure when applicable;
- avoid external network as the only proof when a deterministic local check is possible;
- fail on polluted success results, silent fallback, or wrong capability routing;
- be documented in the source-of-truth registry or SOP.

## 9. Rollback Requirements

Rollback must be named before implementation.

Acceptable rollback:

- revert the source files in the change template;
- disable with a documented environment flag;
- remove a generated artifact and regenerate from source.

Unacceptable rollback:

- manually patching packaged output without source port-back;
- adding prompt warnings over broken runtime behavior;
- deleting local runtime data to hide a state bug.

## 10. Code Review Checklist

Before merge or publish, check:

- The owner layer is named.
- The source of truth is named.
- Files changed match the owner layer.
- Files explicitly not changed were actually left alone.
- Schema EN/CN semantics match.
- Tool registry and SOP summaries do not contradict runtime code.
- Smoke tests ran and classify external failures correctly.
- Rollback is realistic.
- Hotfixes have port-back notes.
- No generated/runtime artifact became the source of truth.

## Minimal Rule

If the change cannot answer the template, stop and classify the owner layer first.
