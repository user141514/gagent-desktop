#!/usr/bin/env python
from __future__ import annotations

import sys
from pathlib import Path


BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from eval_registry.registry import default_cases_dir, load_eval_case, load_eval_cases  # noqa: E402


ROOT = Path(__file__).resolve().parents[2]


def validate() -> list[str]:
    errors: list[str] = []
    cases_dir = default_cases_dir(ROOT)
    if not cases_dir.exists():
        return [f"cases directory does not exist: {cases_dir}"]

    case_paths = sorted(cases_dir.glob("*.json"))
    if len(case_paths) < 3:
        errors.append(f"expected at least 3 eval cases, found {len(case_paths)}")

    try:
        cases = load_eval_cases(cases_dir)
    except ValueError as exc:
        return [str(exc)]

    for case in cases:
        try:
            loaded = load_eval_case(case.source_path)
        except ValueError as exc:
            errors.append(str(exc))
            continue
        errors.extend(_validate_loaded_case(loaded))

    return errors


def _validate_loaded_case(loaded) -> list[str]:
    errors: list[str] = []
    if loaded.id != Path(loaded.source_path).stem:
        errors.append(f"{loaded.source_path}: id and filename mismatch")
    tool_dir = ROOT / "backend" / "tool_registry" / "tools"
    registry_tools = {path.stem for path in tool_dir.glob("*.yml")}
    tool_path = tool_dir / f"{loaded.target_tool}.yml"
    if not tool_path.exists():
        errors.append(f"{loaded.id}: target_tool registry missing: {tool_path}")
    allowed = loaded.expected_tools.get("allowed")
    forbidden = loaded.expected_tools.get("forbidden")
    if not isinstance(allowed, list) or not allowed:
        errors.append(f"{loaded.id}: expected_tools.allowed must be a non-empty list")
    elif loaded.target_tool not in [str(tool) for tool in allowed]:
        errors.append(f"{loaded.id}: expected_tools.allowed must include target_tool {loaded.target_tool}")
    if not isinstance(forbidden, list) or not forbidden:
        errors.append(f"{loaded.id}: expected_tools.forbidden must be a non-empty list")
    if isinstance(allowed, list) and isinstance(forbidden, list):
        overlap = sorted(set(str(tool) for tool in allowed) & set(str(tool) for tool in forbidden))
        if overlap:
            errors.append(f"{loaded.id}: expected_tools.allowed and forbidden must not overlap: {', '.join(overlap)}")
    for field_name, tools in (("allowed", allowed), ("forbidden", forbidden)):
        if isinstance(tools, list):
            unknown = sorted({str(tool) for tool in tools if str(tool) not in registry_tools})
            if unknown:
                errors.append(f"{loaded.id}: expected_tools.{field_name} contains unknown tool: {', '.join(unknown)}")
    total_score = int(loaded.score.get("answer_or_tool_behavior", 0)) + int(loaded.score.get("ledger", 0))
    if total_score != 100:
        errors.append(f"{loaded.id}: score weights must sum to 100, got {total_score}")
    required_events = loaded.expected_ledger.get("required_events")
    if not isinstance(required_events, list):
        errors.append(f"{loaded.id}: expected_ledger.required_events must be a list")
    else:
        for event_name in ("tool_call", "tool_result"):
            if event_name not in required_events:
                errors.append(f"{loaded.id}: required_events must include {event_name}")
    return errors


def main() -> int:
    errors = validate()
    if errors:
        print("[validate_eval_registry] failed", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1
    print("[validate_eval_registry] ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
