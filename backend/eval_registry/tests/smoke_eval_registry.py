#!/usr/bin/env python
from __future__ import annotations

import sys
from pathlib import Path


BACKEND = Path(__file__).resolve().parents[2]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from eval_registry.registry import load_eval_cases  # noqa: E402
from eval_registry.run_eval_cases import run_eval_cases  # noqa: E402
from eval_registry.validate_eval_registry import validate  # noqa: E402


def main() -> int:
    cases = load_eval_cases()
    errors = validate()
    if errors:
        print("[smoke_eval_registry] failed", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1

    summary = run_eval_cases(write_report=True)
    results = summary.get("results") or []
    if len(cases) < 3:
        raise AssertionError("expected at least 3 eval cases")
    if len(results) < 3:
        raise AssertionError("expected at least 3 executed or skipped case results")
    for result in results:
        if result.get("verdict") == "skip":
            continue
        for key in ("total", "verdict", "reasons", "penalties"):
            if key not in result:
                raise AssertionError(f"{result.get('case_id')}: missing {key}")
        if result.get("target_tool") == "web_search" and int(result.get("ledger_event_count") or 0) <= 0:
            raise AssertionError(f"{result.get('case_id')}: missing ledger events")
        if result.get("forbidden_tools_used"):
            raise AssertionError(f"{result.get('case_id')}: forbidden tool used: {result.get('forbidden_tools_used')}")
    if summary.get("case_count", 0) < 3:
        raise AssertionError("summary case_count is less than 3")
    print("[smoke_eval_registry] ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
