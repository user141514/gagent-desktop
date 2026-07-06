# planning-and-task-breakdown

- source_url: https://github.com/addyosmani/agent-skills/tree/main/skills/planning-and-task-breakdown
- adapted_for: GenericAgent-Workbench
- status: imported local SOP

## When to use

Use this skill when the task needs planning, decomposition, scope control, staged delivery, read-only analysis, or early risk framing before implementation. This is a planning-mode SOP, not an implementation checklist.

## SOP

1. Enter read-only planning mode first. Read the request, the most relevant files, nearby docs, and established repo patterns before proposing changes.
2. Define scope explicitly before proposing steps:
   - target outcome
   - non-goals
   - hard constraints
   - what must stay unchanged
3. Identify likely affected files and boundaries. Name the narrowest set of modules, configs, tests, UI surfaces, and runtime paths that may move.
4. Surface dependencies and coupling early:
   - internal imports and shared helpers
   - config or data-flow assumptions
   - integrations and hidden touch points
   - operational constraints
5. Before offering a plan, list the main risks and unknowns:
   - regression risk
   - missing context
   - ambiguous requirements
   - verification gaps
6. Prefer small, ordered phases over broad rewrites. Each phase should have a clear objective, affected files, success criteria, and a verification path.
7. Avoid coding in the planning phase unless the user explicitly asks to implement immediately. If the task is too large, return a staged roadmap instead of a big-bang solution.
8. End with a concrete verification plan. If automation is missing, specify the exact manual checks needed for the first increment.
