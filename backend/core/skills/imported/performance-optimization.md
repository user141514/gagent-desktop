# performance-optimization

- source_url: https://github.com/addyosmani/agent-skills/tree/main/skills/performance-optimization
- status: placeholder local import

## Intent

Use this skill when runtime cost, latency, repeated work, or prompt bloat are the main problem.

## Minimal SOP

1. Measure before changing behavior.
2. Find the dominant bottleneck first.
3. Prefer removing repeated LLM calls, repeated tool work, or oversized prompt sections before micro-optimizing.
4. Validate every optimization with before/after numbers.
5. Keep safety and correctness checks in place.
