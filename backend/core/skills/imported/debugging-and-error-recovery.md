# debugging-and-error-recovery

- source_url: https://github.com/addyosmani/agent-skills/tree/main/skills/debugging-and-error-recovery
- status: placeholder local import

## Intent

Use this skill when a task is blocked by an exception, traceback, failed call, or unstable runtime behavior.

## Minimal SOP

1. Capture the exact error and failing call site.
2. Reproduce with the smallest stable input.
3. Separate symptom, root cause, and side effects.
4. Fix the smallest defensible layer.
5. Re-run the failing path and one adjacent path.
