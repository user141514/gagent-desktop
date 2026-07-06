# test-driven-development

- source_url: https://github.com/addyosmani/agent-skills/tree/main/skills/test-driven-development
- adapted_for: GenericAgent-Workbench
- status: imported local SOP

## When to use

Use this skill when the task needs verification discipline: bug fixes, acceptance criteria, regression protection, test-first changes, or explicit “how do we validate this?” guidance.

## SOP

1. Define observable behavior before touching code. State what should happen, what currently happens, and how success will be checked.
2. Prefer the smallest useful test first:
   - failing unit test if the repo already has a test harness
   - narrow integration test if behavior crosses modules
   - precise manual reproduction steps if no test framework exists
3. For bug fixes, reproduce before fixing. Do not accept “probably fixed” without a failing case or a clear before/after verification path.
4. Use the smallest defensible loop:
   - failing test or failing reproduction
   - minimal implementation
   - passing test
   - regression check on one adjacent path
5. Do not treat missing tests as permission to skip validation. When automation is absent, provide executable manual steps with inputs and expected outputs.
6. For performance work, preserve before/after evidence such as latency, prompt size, token count, or LLM call count.
7. For UI, Streamlit, or agent behaviors, define an end-to-end acceptance flow that can actually be run after the change.
8. When reporting completion, separate what was tested, what passed, and what remains unverified.
