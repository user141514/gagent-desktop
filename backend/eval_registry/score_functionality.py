#!/usr/bin/env python
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from core.browser_agent import BROWSER_AGENT_RESULT_FIELDS  # noqa: E402
from eval_registry.run_eval_cases import (  # noqa: E402
    EVAL_FINAL_ANSWER_FIELDS,
    EVAL_INT_LIST_FIELDS,
    EVAL_REPORT_FIELDS,
    EVAL_RESULT_FIELDS,
    EVAL_STRING_LIST_FIELDS,
)
from runtime_ledger import (  # noqa: E402
    default_ledger_dir,
    read_run_events,
    RUNTIME_HOST_SUMMARY_FIELDS,
    RUNTIME_LEDGER_SUMMARY_FIELDS,
    RUNTIME_OBSERVABILITY_ALIGNED_FIELDS,
    RUNTIME_OBSERVABILITY_FIELDS,
    summarize_run,
    write_event,
)

RESULTS_DIR = ROOT / "backend" / "eval_registry" / "results"
OUTPUT_PATH = RESULTS_DIR / "latest_functionality_score.json"

SCORE_COMPONENT_WEIGHTS = {
    "internal_eval": 70,
    "openai_orchestrated_e2e": 15,
    "browser_agent_e2e": 15,
}
SCORE_INPUT_REPORTS = [
    "latest_eval_report.json",
    "latest_openai_e2e_report.json",
    "latest_browser_agent_e2e_report.json",
]
SCORE_E2E_ENV_KEYS = [
    "GAGENT_E2E_DEPS",
    "GAGENT_RUN_OPENAI_E2E",
    "GAGENT_RUN_BROWSER_AGENT_E2E",
]
BASE_COMPONENT_FIELDS = {"name", "weight", "score", "status", "blockers"}
COMPONENT_EXTRA_FIELDS = {
    "internal_eval": {"case_count", "passed", "failed", "average_case_score"},
    "openai_orchestrated_e2e": {"evidence_status"},
    "browser_agent_e2e": {"evidence_status"},
}
SCORE_EVIDENCE_FIELDS = {
    "generated_at_utc",
    "results_dir",
    "python_executable",
    "e2e_env",
    "source_git",
    "input_reports",
}
SOURCE_GIT_FIELDS = {"available", "head", "branch", "dirty"}
INPUT_REPORT_FIELDS = {"exists", "bytes", "modified_at_utc"}
OPTIONAL_E2E_PASSED_FIELDS = {
    "openai_orchestrated_e2e": {"status", "run_id", "done", "ledger_summary", "observability"},
    "browser_agent_e2e": {"status", "run_id", "tool_result", "ledger_summary", "ledger_event_count"},
}
OPTIONAL_E2E_NONPASSED_FIELDS = {
    "openai_orchestrated_e2e": {
        "status",
        "reason",
        "required",
        "failure_class",
        "startup_error",
        "run_id",
        "done",
        "ledger_event_count",
        "ledger_summary",
        "observability",
        "missing_events",
    },
    "browser_agent_e2e": {
        "status",
        "reason",
        "required",
        "failure_class",
        "run_id",
        "tool_result",
        "ledger_event_count",
        "ledger_summary",
    },
}
OPTIONAL_E2E_RUN_ID_PREFIXES = {
    "openai_orchestrated_e2e": "openai_e2e_",
    "browser_agent_e2e": "browser_agent_e2e_",
}
OPTIONAL_E2E_OWNER_LAYERS = {
    "openai_orchestrated_e2e": "Layer 3 runtime controller",
    "browser_agent_e2e": "Layer 1 capability contract",
}
OPTIONAL_E2E_EVENT_SEQUENCES = {
    "openai_orchestrated_e2e": ["run_started", "run_finished"],
    "browser_agent_e2e": ["run_started", "tool_call", "tool_result", "run_finished"],
}

def main() -> int:
    parser = argparse.ArgumentParser(description="Score current gagent-desktop functionality from eval reports.")
    parser.add_argument("--self-test", action="store_true", help="run small built-in scoring checks")
    parser.add_argument("--no-write", action="store_true", help="do not write latest_functionality_score.json")
    parser.add_argument("--refresh", action="store_true", help="run eval/smoke report generators before scoring")
    parser.add_argument("--strict", action="store_true", help="exit non-zero unless the score is complete")
    parser.add_argument("--results-dir", help="read latest reports from this directory instead of the default results dir")
    args = parser.parse_args()

    if args.self_test:
        _self_test()
        print("[score_functionality] self-test ok")
        return 0

    if args.refresh and args.results_dir:
        parser.error("--refresh cannot be combined with --results-dir")
    if args.results_dir and not args.no_write:
        parser.error("--results-dir requires --no-write")

    if args.refresh:
        try:
            _refresh_reports()
        except subprocess.CalledProcessError as exc:
            print(f"[score_functionality] refresh failed: {' '.join(exc.cmd)}", file=sys.stderr)
            _print_captured_process_output(exc)
            return int(exc.returncode or 1)

    report = score_latest_reports(args.results_dir)
    report["refreshed"] = bool(args.refresh)
    report["strict"] = bool(args.strict)
    report["evidence"] = _build_evidence(args.results_dir)
    if not args.no_write:
        RESULTS_DIR.mkdir(parents=True, exist_ok=True)
        OUTPUT_PATH.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return _exit_code_for_report(report, strict=bool(args.strict))


def score_latest_reports(results_dir: str | Path | None = None) -> dict[str, Any]:
    base = Path(results_dir) if results_dir is not None else RESULTS_DIR
    return score_reports(
        _read_json(base / SCORE_INPUT_REPORTS[0]),
        _read_json(base / SCORE_INPUT_REPORTS[1]),
        _read_json(base / SCORE_INPUT_REPORTS[2]),
        raw_ledger_dir=default_ledger_dir(ROOT) if results_dir is None else None,
    )


def score_reports(
    eval_report: dict[str, Any] | None,
    openai_report: dict[str, Any] | None,
    browser_agent_report: dict[str, Any] | None,
    *,
    raw_ledger_dir: str | Path | None = None,
) -> dict[str, Any]:
    components = [
        _score_internal_eval(eval_report, SCORE_COMPONENT_WEIGHTS["internal_eval"]),
        _score_optional_e2e(
            "openai_orchestrated_e2e",
            openai_report,
            SCORE_COMPONENT_WEIGHTS["openai_orchestrated_e2e"],
            "OpenAI orchestrated SDK path is not proven",
            raw_ledger_dir=raw_ledger_dir,
        ),
        _score_optional_e2e(
            "browser_agent_e2e",
            browser_agent_report,
            SCORE_COMPONENT_WEIGHTS["browser_agent_e2e"],
            "browser_agent real browser/LLM path is not proven",
            raw_ledger_dir=raw_ledger_dir,
        ),
    ]
    total = sum(int(item["score"]) for item in components)
    max_total = _max_total()
    blockers = [blocker for item in components for blocker in item.get("blockers", [])]
    return {
        "status": "ok" if total == max_total else "needs_work",
        "total": total,
        "max_total": max_total,
        "components": components,
        "blockers": blockers,
    }


def _max_total() -> int:
    return sum(SCORE_COMPONENT_WEIGHTS.values())


def _score_internal_eval(report: dict[str, Any] | None, weight: int) -> dict[str, Any]:
    if not report:
        return _component("internal_eval", weight, 0, "missing", ["latest_eval_report.json is missing"])
    raw_results = report.get("results")
    if not isinstance(raw_results, list):
        return _component("internal_eval", weight, 0, "invalid_evidence", ["latest_eval_report.json results must be a list"])
    if not raw_results:
        return _component("internal_eval", weight, 0, "missing", ["latest_eval_report.json has no results"])
    results = [item for item in raw_results if isinstance(item, dict)]
    shape_blockers = [
        *_internal_eval_report_shape_blockers(report),
        *_internal_eval_result_shape_blockers(raw_results),
    ]
    coverage_blockers = _internal_eval_coverage_blockers(report, results)
    if shape_blockers or coverage_blockers:
        failed = [str(item.get("case_id") or "") for item in results if item.get("verdict") != "pass"]
        return {
            **_component("internal_eval", weight, 0, "invalid_evidence", [*shape_blockers, *coverage_blockers]),
            "case_count": len(results),
            "passed": len(results) - len(failed),
            "failed": len(failed),
            "average_case_score": 0,
        }
    average = sum(float(item.get("total") or 0) for item in results) / len(results)
    score = round(weight * average / 100)
    failed = [str(item.get("case_id") or "") for item in results if item.get("verdict") != "pass"]
    blockers = [f"eval case not passing: {case_id}" for case_id in failed if case_id]
    if average < 100:
        blockers.append(f"internal eval average score below 100: {round(average, 2)}")
    status = "failed" if failed else ("partial" if average < 100 else "passed")
    return {
        **_component("internal_eval", weight, score, status, blockers),
        "case_count": len(results),
        "passed": len(results) - len(failed),
        "failed": len(failed),
        "average_case_score": round(average, 2),
    }


def _internal_eval_report_shape_blockers(report: dict[str, Any]) -> list[str]:
    unknown_fields = sorted(set(report) - EVAL_REPORT_FIELDS)
    if unknown_fields:
        return ["internal eval report unknown field: " + ", ".join(unknown_fields)]
    return []


def _internal_eval_result_shape_blockers(results: list[Any]) -> list[str]:
    blockers: list[str] = []
    for index, item in enumerate(results, start=1):
        if not isinstance(item, dict):
            blockers.append(f"internal eval result entry is invalid at index {index}")
            continue
        case_id = str(item.get("case_id") or f"#{index}")
        unknown_fields = sorted(set(item) - EVAL_RESULT_FIELDS)
        if unknown_fields:
            blockers.append(f"internal eval result unknown field for {case_id}: {', '.join(unknown_fields)}")
        final_answer = item.get("final_answer")
        if "final_answer" in item:
            if not isinstance(final_answer, dict):
                blockers.append(f"internal eval final_answer is invalid for {case_id}")
            else:
                unknown_final_answer_fields = sorted(set(final_answer) - EVAL_FINAL_ANSWER_FIELDS)
                if unknown_final_answer_fields:
                    blockers.append(
                        f"internal eval final_answer unknown field for {case_id}: "
                        + ", ".join(unknown_final_answer_fields)
                    )
        observability = item.get("observability")
        if "observability" in item:
            blockers.extend(_observability_shape_errors("internal eval", observability, item.get("run_id")))
        blockers.extend(_internal_eval_list_field_blockers(case_id, item))
        total = item.get("total")
        if isinstance(total, bool) or not isinstance(total, (int, float)) or not 0 <= float(total) <= 100:
            blockers.append(f"internal eval result total is invalid for {case_id}")
        verdict = item.get("verdict")
        if verdict not in {"pass", "fail", "skip"}:
            blockers.append(f"internal eval result verdict is invalid for {case_id}")
    return blockers


def _internal_eval_list_field_blockers(case_id: str, item: dict[str, Any]) -> list[str]:
    blockers: list[str] = []
    for field in sorted(EVAL_STRING_LIST_FIELDS):
        if field not in item:
            continue
        value = item.get(field)
        if not isinstance(value, list):
            blockers.append(f"internal eval {field} must be a list for {case_id}")
        elif not all(isinstance(entry, str) for entry in value):
            blockers.append(f"internal eval {field} must contain strings for {case_id}")
    for field in sorted(EVAL_INT_LIST_FIELDS):
        if field not in item:
            continue
        value = item.get(field)
        if not isinstance(value, list):
            blockers.append(f"internal eval {field} must be a list for {case_id}")
        elif not all(isinstance(entry, int) and not isinstance(entry, bool) and entry >= 0 for entry in value):
            blockers.append(f"internal eval {field} must contain non-negative integers for {case_id}")
    return blockers


def _internal_eval_coverage_blockers(report: dict[str, Any], results: list[dict[str, Any]]) -> list[str]:
    expected = _expected_eval_case_ids()
    if not expected:
        return ["internal eval registry cases are missing"]
    blockers: list[str] = []
    reported_case_count = report.get("case_count")
    if reported_case_count != len(expected):
        blockers.append(f"internal eval case_count does not match registry cases: {reported_case_count} != {len(expected)}")
    if len(results) != len(expected):
        blockers.append(f"internal eval result count does not match registry cases: {len(results)} != {len(expected)}")
    result_ids = [str(item.get("case_id") or "") for item in results]
    passed = len([item for item in results if item.get("verdict") == "pass"])
    failed = len([item for item in results if item.get("verdict") == "fail"])
    skipped = len([item for item in results if item.get("verdict") == "skip"])
    expected_status = "ok" if failed == 0 else "failed"
    if report.get("status") != expected_status:
        blockers.append(f"internal eval status does not match results: {report.get('status')} != {expected_status}")
    if report.get("passed") != passed:
        blockers.append(f"internal eval passed count does not match results: {report.get('passed')} != {passed}")
    if report.get("failed") != failed:
        blockers.append(f"internal eval failed count does not match results: {report.get('failed')} != {failed}")
    if report.get("skipped") != skipped:
        blockers.append(f"internal eval skipped count does not match results: {report.get('skipped')} != {skipped}")
    expected_set = set(expected)
    result_set = set(result_ids)
    missing = sorted(expected_set - result_set)
    unexpected = sorted(result_set - expected_set)
    duplicates = sorted({case_id for case_id in result_ids if case_id and result_ids.count(case_id) > 1})
    if missing:
        blockers.append("internal eval missing cases: " + ", ".join(missing))
    if unexpected:
        blockers.append("internal eval unexpected cases: " + ", ".join(unexpected))
    if duplicates:
        blockers.append("internal eval duplicate cases: " + ", ".join(duplicates))
    return blockers


def _expected_eval_case_ids() -> list[str]:
    return sorted(path.stem for path in (ROOT / "backend" / "eval_registry" / "cases").glob("*.json"))


def _score_optional_e2e(
    name: str,
    report: dict[str, Any] | None,
    weight: int,
    missing_msg: str,
    *,
    raw_ledger_dir: str | Path | None = None,
) -> dict[str, Any]:
    if not report:
        return _component(name, weight, 0, "missing", [missing_msg])
    status = str(report.get("status") or "unknown")
    if status == "passed":
        evidence_errors = _passed_optional_e2e_errors(name, report, raw_ledger_dir=raw_ledger_dir)
        if evidence_errors:
            return _component(name, weight, 0, "invalid_evidence", evidence_errors)
        return _component(name, weight, weight, "passed", [])
    evidence_errors = _nonpassed_optional_e2e_errors(name, report)
    if evidence_errors:
        return {
            **_component(name, weight, 0, "invalid_evidence", evidence_errors),
            "evidence_status": status,
        }
    reason = str(report.get("startup_error") or report.get("reason") or missing_msg)
    failure_class = str(report.get("failure_class") or status)
    return {
        **_component(name, weight, 0, failure_class, [reason]),
        "evidence_status": status,
    }


def _passed_optional_e2e_errors(
    name: str,
    report: dict[str, Any],
    *,
    raw_ledger_dir: str | Path | None = None,
) -> list[str]:
    errors: list[str] = []
    unknown_fields = sorted(set(report) - OPTIONAL_E2E_PASSED_FIELDS.get(name, set(report)))
    if unknown_fields:
        errors.append(f"{name} passed report has unknown field: {', '.join(unknown_fields)}")
    run_id = str(report.get("run_id") or "").strip()
    if not run_id:
        errors.append(f"{name} passed report missing run_id")
    else:
        expected_prefix = OPTIONAL_E2E_RUN_ID_PREFIXES.get(name)
        if expected_prefix and not run_id.startswith(expected_prefix):
            errors.append(f"{name} run_id prefix must be {expected_prefix}")
    ledger = report.get("ledger_summary")
    if not isinstance(ledger, dict):
        errors.append(f"{name} passed report missing ledger_summary")
        return errors
    unknown_ledger_fields = sorted(set(ledger) - RUNTIME_LEDGER_SUMMARY_FIELDS)
    if unknown_ledger_fields:
        errors.append(f"{name} ledger_summary unknown field: {', '.join(unknown_ledger_fields)}")
    if run_id and str(ledger.get("run_id") or "") != run_id:
        errors.append(f"{name} ledger_summary.run_id does not match run_id")
    if not isinstance(ledger.get("event_count"), int) or int(ledger.get("event_count") or 0) <= 0:
        errors.append(f"{name} passed report missing ledger events")
    if str(ledger.get("final_status") or "") != "success":
        errors.append(f"{name} passed report final_status is not success")
    task = str(ledger.get("task") or "").strip()
    if not task:
        errors.append(f"{name} passed report missing ledger_summary.task")
    elif name == "openai_orchestrated_e2e" and "OPENAI_E2E_OK" not in task:
        errors.append(f"{name} ledger_summary.task missing OPENAI_E2E_OK")
    owner_layer = str(ledger.get("owner_layer") or "").strip()
    expected_owner_layer = OPTIONAL_E2E_OWNER_LAYERS.get(name)
    if not owner_layer:
        errors.append(f"{name} passed report missing ledger_summary.owner_layer")
    elif expected_owner_layer and owner_layer != expected_owner_layer:
        errors.append(f"{name} ledger_summary.owner_layer must be {expected_owner_layer}")
    tools = ledger.get("tools")
    if not isinstance(tools, dict):
        errors.append(f"{name} passed report missing ledger_summary.tools")
    elif not all(isinstance(tool, str) and type(count) is int and count >= 0 for tool, count in tools.items()):
        errors.append(f"{name} ledger_summary.tools is invalid")
    elif name == "openai_orchestrated_e2e" and tools:
        errors.append(f"{name} ledger_summary.tools must be empty")
    elif name == "browser_agent_e2e":
        unknown_tools = sorted(set(tools) - {"browser_agent"})
        if unknown_tools:
            errors.append(f"{name} ledger_summary.tools has unexpected tool: {', '.join(unknown_tools)}")
        if int(tools.get("browser_agent") or 0) <= 0:
            errors.append(f"{name} passed report missing browser_agent tool evidence")
    if name == "openai_orchestrated_e2e" and "OPENAI_E2E_OK" not in str(report.get("done") or ""):
        errors.append(f"{name} passed report missing OPENAI_E2E_OK sentinel")
    if name == "openai_orchestrated_e2e":
        errors.extend(_openai_observability_errors(name, report))
    if name == "browser_agent_e2e":
        tool_result = report.get("tool_result")
        if not isinstance(tool_result, dict) or not (
            tool_result.get("success") is True or str(tool_result.get("status") or "").lower() == "success"
        ):
            errors.append(f"{name} passed report missing successful tool_result")
        else:
            unknown_tool_result_fields = sorted(set(tool_result) - BROWSER_AGENT_RESULT_FIELDS)
            if unknown_tool_result_fields:
                errors.append(f"{name} tool_result unknown field: {', '.join(unknown_tool_result_fields)}")
            if not str(tool_result.get("result") or "").strip():
                errors.append(f"{name} passed report missing browser_agent result")
            if not isinstance(tool_result.get("steps_taken"), int) or int(tool_result.get("steps_taken") or 0) <= 0:
                errors.append(f"{name} passed report missing positive steps_taken")
        if not isinstance(report.get("ledger_event_count"), int) or int(report.get("ledger_event_count") or 0) <= 0:
            errors.append(f"{name} passed report missing ledger_event_count")
        elif report.get("ledger_event_count") != ledger.get("event_count"):
            errors.append(f"{name} ledger_event_count does not match ledger_summary.event_count")
    if raw_ledger_dir is not None:
        errors.extend(_raw_ledger_summary_errors(name, report, ledger, raw_ledger_dir))
    return errors


def _raw_ledger_summary_errors(
    name: str,
    report: dict[str, Any],
    ledger: dict[str, Any],
    raw_ledger_dir: str | Path,
) -> list[str]:
    run_id = str(report.get("run_id") or "").strip()
    if not run_id:
        return []
    try:
        raw_events = read_run_events(run_id, ledger_dir=raw_ledger_dir)
        raw_summary = summarize_run(run_id, ledger_dir=raw_ledger_dir)
    except ValueError as exc:
        return [f"{name} raw runtime_ledger is invalid: {exc}"]
    if not raw_events or int(raw_summary.get("event_count") or 0) <= 0:
        return [f"{name} raw runtime_ledger events are missing for run_id"]
    errors: list[str] = []
    for field in sorted(RUNTIME_LEDGER_SUMMARY_FIELDS):
        if ledger.get(field) != raw_summary.get(field):
            errors.append(f"{name} ledger_summary.{field} does not match raw runtime_ledger")
    errors.extend(_raw_ledger_event_sequence_errors(name, raw_events))
    return errors


def _raw_ledger_event_sequence_errors(name: str, raw_events: list[dict[str, Any]]) -> list[str]:
    expected_sequence = OPTIONAL_E2E_EVENT_SEQUENCES.get(name)
    if not expected_sequence:
        return []
    event_sequence = [str(event.get("event_type") or "") for event in raw_events]
    if event_sequence != expected_sequence:
        return [
            f"{name} raw runtime_ledger event sequence must be {' -> '.join(expected_sequence)}"
        ]
    if name != "browser_agent_e2e":
        return []
    tool_events = raw_events[1:]
    if any(str(event.get("tool") or "") != "browser_agent" for event in tool_events):
        return [f"{name} raw runtime_ledger browser_agent events must use browser_agent tool"]
    return []


def _nonpassed_optional_e2e_errors(name: str, report: dict[str, Any]) -> list[str]:
    unknown_fields = sorted(set(report) - OPTIONAL_E2E_NONPASSED_FIELDS.get(name, set(report)))
    if unknown_fields:
        return [f"{name} report has unknown field: {', '.join(unknown_fields)}"]
    return []


def _openai_observability_errors(name: str, report: dict[str, Any]) -> list[str]:
    errors = _observability_shape_errors(name, report.get("observability"), report.get("run_id"))
    if errors:
        return errors
    observability = report["observability"]
    aligned = observability["aligned"]
    required = [
        "has_ledger_events",
        "has_runtime_host_events",
        "ledger_run_id_matches_requested",
        "runtime_session_matches_run_id",
    ]
    return [
        f"{name} observability alignment missing {key}"
        for key in required
        if aligned.get(key) is not True
    ]


def _observability_shape_errors(label: str, observability: Any, expected_run_id: Any = None) -> list[str]:
    if not isinstance(observability, dict):
        return [f"{label} passed report missing observability"]
    errors: list[str] = []
    unknown_observability_fields = sorted(set(observability) - RUNTIME_OBSERVABILITY_FIELDS)
    if unknown_observability_fields:
        errors.append(f"{label} observability unknown field: {', '.join(unknown_observability_fields)}")
    missing_observability_fields = sorted(RUNTIME_OBSERVABILITY_FIELDS - set(observability))
    if missing_observability_fields:
        errors.append(f"{label} observability missing field: {', '.join(missing_observability_fields)}")
    if expected_run_id is not None and str(observability.get("run_id") or "") != str(expected_run_id or ""):
        errors.append(f"{label} observability.run_id does not match run_id")
    ledger = observability.get("ledger")
    if isinstance(ledger, dict):
        unknown_ledger_fields = sorted(set(ledger) - RUNTIME_LEDGER_SUMMARY_FIELDS)
        if unknown_ledger_fields:
            errors.append(f"{label} observability.ledger unknown field: {', '.join(unknown_ledger_fields)}")
    elif "ledger" in observability:
        errors.append(f"{label} observability.ledger is invalid")
    runtime_host = observability.get("runtime_host")
    if isinstance(runtime_host, dict):
        unknown_runtime_host_fields = sorted(set(runtime_host) - RUNTIME_HOST_SUMMARY_FIELDS)
        if unknown_runtime_host_fields:
            errors.append(f"{label} observability.runtime_host unknown field: {', '.join(unknown_runtime_host_fields)}")
    elif "runtime_host" in observability:
        errors.append(f"{label} observability.runtime_host is invalid")
    aligned = observability.get("aligned")
    if not isinstance(aligned, dict):
        errors.append(f"{label} passed report missing observability alignment")
        return errors
    unknown_aligned_fields = sorted(set(aligned) - RUNTIME_OBSERVABILITY_ALIGNED_FIELDS)
    if unknown_aligned_fields:
        errors.append(f"{label} observability.aligned unknown field: {', '.join(unknown_aligned_fields)}")
    return errors


def _component(name: str, weight: int, score: int, status: str, blockers: list[str]) -> dict[str, Any]:
    return {
        "name": name,
        "weight": weight,
        "score": max(0, min(weight, score)),
        "status": status,
        "blockers": blockers,
    }


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _build_evidence(results_dir: str | Path | None = None) -> dict[str, Any]:
    base = Path(results_dir) if results_dir is not None else RESULTS_DIR
    return {
        "generated_at_utc": _utc_now(),
        "results_dir": str(base.resolve()),
        "python_executable": str(Path(sys.executable).resolve()),
        "e2e_env": {
            key: os.environ.get(key, "")
            for key in SCORE_E2E_ENV_KEYS
        },
        "source_git": _source_git_evidence(),
        "input_reports": _input_report_evidence(base),
    }


def _source_git_evidence() -> dict[str, Any]:
    head = _git_text("rev-parse", "HEAD")
    branch = _git_text("branch", "--show-current") or _git_text("rev-parse", "--abbrev-ref", "HEAD") or ""
    status = _git_text("status", "--porcelain")
    if not head or status is None:
        return {
            "available": False,
            "head": head or "",
            "branch": branch,
            "dirty": None,
        }
    return {
        "available": True,
        "head": head,
        "branch": branch,
        "dirty": bool(status),
    }


def _git_text(*args: str) -> str | None:
    result = subprocess.run(
        ["git", *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode != 0:
        return None
    return result.stdout.strip()


def _input_report_evidence(base: Path) -> dict[str, dict[str, Any]]:
    evidence: dict[str, dict[str, Any]] = {}
    for name in SCORE_INPUT_REPORTS:
        path = base / name
        try:
            stat = path.stat()
        except OSError:
            evidence[name] = {"exists": False}
        else:
            evidence[name] = {
                "exists": True,
                "bytes": stat.st_size,
                "modified_at_utc": _utc_from_timestamp(stat.st_mtime),
            }
    return evidence


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _utc_from_timestamp(timestamp: float) -> str:
    return datetime.fromtimestamp(timestamp, timezone.utc).isoformat().replace("+00:00", "Z")


def _exit_code_for_report(report: dict[str, Any], *, strict: bool) -> int:
    status = str(report.get("status") or "")
    if status == "ok":
        return 0
    if status == "needs_work" and not strict:
        return 0
    return 1


def _refresh_reports() -> None:
    for command in _refresh_commands():
        _run_refresh_command(command)


def _refresh_commands() -> list[list[str]]:
    return [
        [sys.executable, str(ROOT / "backend" / "eval_registry" / "run_eval_cases.py")],
        [sys.executable, str(ROOT / "backend" / "eval_registry" / "tests" / "smoke_openai_orchestrated_e2e.py")],
        [sys.executable, str(ROOT / "backend" / "eval_registry" / "tests" / "smoke_browser_agent_e2e.py")],
    ]


def _run_refresh_command(command: list[str]) -> None:
    subprocess.run(
        command,
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def _print_captured_process_output(exc: subprocess.CalledProcessError) -> None:
    for label, text in _captured_process_output_sections(exc):
        print(f"[score_functionality] child {label}:", file=sys.stderr)
        print(text, file=sys.stderr)


def _captured_process_output_sections(exc: subprocess.CalledProcessError) -> list[tuple[str, str]]:
    sections: list[tuple[str, str]] = []
    stdout = str(exc.stdout or "").strip()
    stderr = str(exc.stderr or "").strip()
    if stdout:
        sections.append(("stdout", stdout))
    if stderr:
        sections.append(("stderr", stderr))
    return sections


def _passed_e2e_report(name: str) -> dict[str, Any]:
    run_id = f"{OPTIONAL_E2E_RUN_ID_PREFIXES.get(name, name + '_')}fixture_run"
    report: dict[str, Any] = {
        "status": "passed",
        "run_id": run_id,
        "ledger_summary": {
            "run_id": run_id,
            "event_count": 2,
            "task": "Reply with exactly: OPENAI_E2E_OK. Do not call tools.",
            "owner_layer": OPTIONAL_E2E_OWNER_LAYERS.get(name, ""),
            "tools": {},
            "failure_count": 0,
            "failures": [],
            "decisions": [],
            "smoke_tests": [],
            "final_status": "success",
        },
    }
    if name == "openai_orchestrated_e2e":
        report["done"] = "OPENAI_E2E_OK"
        report["observability"] = {
            "run_id": run_id,
            "ledger": dict(report["ledger_summary"]),
            "runtime_host": {
                "event_count": 1,
                "event_types": ["session_completed"],
                "session_ids": [run_id],
                "tools": {},
                "started_turns": [1],
                "completed_turns": [1],
                "final_status": "completed",
            },
            "aligned": {
                "has_ledger_events": True,
                "has_runtime_host_events": True,
                "ledger_run_id_matches_requested": True,
                "runtime_session_matches_run_id": True,
            }
        }
    if name == "browser_agent_e2e":
        report["ledger_summary"]["event_count"] = 4
        report["ledger_summary"]["task"] = "Open https://example.com and report the page title."
        report["ledger_summary"]["tools"] = {"browser_agent": 3}
        report["tool_result"] = {
            "success": True,
            "result": "Example Domain",
            "steps_taken": 2,
        }
        report["ledger_event_count"] = 4
    return report


def _write_passed_e2e_raw_ledger(report: dict[str, Any], ledger_dir: str | Path) -> None:
    run_id = str(report["run_id"])
    ledger = report["ledger_summary"]
    write_event(
        {
            "run_id": run_id,
            "event_type": "run_started",
            "task": ledger["task"],
            "owner_layer": ledger["owner_layer"],
        },
        ledger_dir=ledger_dir,
    )
    if run_id.startswith(OPTIONAL_E2E_RUN_ID_PREFIXES["browser_agent_e2e"]):
        write_event({"run_id": run_id, "event_type": "tool_call", "tool": "browser_agent"}, ledger_dir=ledger_dir)
        write_event({"run_id": run_id, "event_type": "tool_result", "tool": "browser_agent"}, ledger_dir=ledger_dir)
        write_event(
            {"run_id": run_id, "event_type": "run_finished", "tool": "browser_agent", "final_status": "success"},
            ledger_dir=ledger_dir,
        )
    else:
        write_event({"run_id": run_id, "event_type": "run_finished", "final_status": "success"}, ledger_dir=ledger_dir)


def _passed_internal_eval_report(*, partial: bool = False) -> dict[str, Any]:
    results = []
    for index, case_id in enumerate(_expected_eval_case_ids()):
        results.append({
            "case_id": case_id,
            "total": 80 if partial and index == 0 else 100,
            "verdict": "pass",
            "final_answer": {
                "text": "web_search succeeded. Source: https://openai.com/docs",
                "total": 100,
                "verdict": "pass",
                "reasons": ["answer is consistent with successful tool result"],
                "penalties": [],
            },
            "observability": _internal_eval_observability_fixture(case_id),
        })
    return {
        "status": "ok",
        "case_count": len(results),
        "passed": len(results),
        "failed": 0,
        "skipped": 0,
        "results": results,
    }


def _internal_eval_observability_fixture(case_id: str) -> dict[str, Any]:
    run_id = f"eval_{case_id}_run"
    return {
        "run_id": run_id,
        "ledger": {
            "run_id": run_id,
            "event_count": 4,
            "task": "internal eval fixture",
            "owner_layer": "Layer 3 runtime controller",
            "tools": {"web_search": 2},
            "failure_count": 0,
            "failures": [],
            "decisions": [],
            "smoke_tests": [],
            "final_status": "success",
        },
        "runtime_host": {
            "event_count": 2,
            "event_types": ["session_started", "session_completed"],
            "session_ids": [run_id],
            "tools": {},
            "started_turns": [1],
            "completed_turns": [1],
            "final_status": "completed",
        },
        "aligned": {
            "has_ledger_events": True,
            "has_runtime_host_events": True,
            "ledger_run_id_matches_requested": True,
            "runtime_session_matches_run_id": True,
        },
    }


def _self_test() -> None:
    openai_passed = _passed_e2e_report("openai_orchestrated_e2e")
    browser_passed = _passed_e2e_report("browser_agent_e2e")
    full_internal_eval = _passed_internal_eval_report()
    passing_eval = _passed_internal_eval_report(partial=True)
    passed = score_reports(passing_eval, openai_passed, browser_passed)
    assert passed["status"] == "needs_work"
    assert passed["components"][0]["status"] == "partial"
    assert any("average score below 100" in blocker for blocker in passed["blockers"])
    assert _exit_code_for_report(passed, strict=False) == 0
    assert _exit_code_for_report(passed, strict=True) == 1

    complete = score_reports(
        full_internal_eval,
        openai_passed,
        browser_passed,
    )
    assert complete["status"] == "ok"
    assert _exit_code_for_report(complete, strict=True) == 0
    with tempfile.TemporaryDirectory() as tmp_ledger_dir:
        missing_raw_ledger = score_reports(
            full_internal_eval,
            openai_passed,
            browser_passed,
            raw_ledger_dir=tmp_ledger_dir,
        )
        assert missing_raw_ledger["status"] == "needs_work"
        assert any("raw runtime_ledger" in blocker for blocker in missing_raw_ledger["blockers"])
        _write_passed_e2e_raw_ledger(openai_passed, tmp_ledger_dir)
        _write_passed_e2e_raw_ledger(browser_passed, tmp_ledger_dir)
        raw_bound = score_reports(
            full_internal_eval,
            openai_passed,
            browser_passed,
            raw_ledger_dir=tmp_ledger_dir,
        )
        assert raw_bound["status"] == "ok"
        browser_task_drift = json.loads(json.dumps(browser_passed))
        browser_task_drift["ledger_summary"]["task"] = "Different browser task."
        raw_task_drift = score_reports(
            full_internal_eval,
            openai_passed,
            browser_task_drift,
            raw_ledger_dir=tmp_ledger_dir,
        )
        assert raw_task_drift["status"] == "needs_work"
        assert any("raw runtime_ledger" in blocker for blocker in raw_task_drift["blockers"])
    with tempfile.TemporaryDirectory() as tmp_ledger_dir:
        _write_passed_e2e_raw_ledger(openai_passed, tmp_ledger_dir)
        run_id = str(browser_passed["run_id"])
        ledger = browser_passed["ledger_summary"]
        write_event(
            {
                "run_id": run_id,
                "event_type": "run_started",
                "task": ledger["task"],
                "owner_layer": ledger["owner_layer"],
            },
            ledger_dir=tmp_ledger_dir,
        )
        write_event({"run_id": run_id, "event_type": "tool_result", "tool": "browser_agent"}, ledger_dir=tmp_ledger_dir)
        write_event({"run_id": run_id, "event_type": "tool_call", "tool": "browser_agent"}, ledger_dir=tmp_ledger_dir)
        write_event(
            {"run_id": run_id, "event_type": "run_finished", "tool": "browser_agent", "final_status": "success"},
            ledger_dir=tmp_ledger_dir,
        )
        raw_sequence_drift = score_reports(
            full_internal_eval,
            openai_passed,
            browser_passed,
            raw_ledger_dir=tmp_ledger_dir,
        )
        assert raw_sequence_drift["status"] == "needs_work"
        assert any("event sequence" in blocker for blocker in raw_sequence_drift["blockers"])

    internal_extra_field = dict(full_internal_eval)
    internal_extra_field["mystery_field"] = True
    internal_extra_score = score_reports(
        internal_extra_field,
        openai_passed,
        browser_passed,
    )
    assert internal_extra_score["status"] == "needs_work"
    assert any("internal eval report unknown field" in blocker for blocker in internal_extra_score["blockers"])

    internal_result_extra_field = _passed_internal_eval_report()
    internal_result_extra_field["results"][0]["mystery_field"] = True
    internal_result_extra_score = score_reports(
        internal_result_extra_field,
        openai_passed,
        browser_passed,
    )
    assert internal_result_extra_score["status"] == "needs_work"
    assert any("internal eval result unknown field" in blocker for blocker in internal_result_extra_score["blockers"])

    internal_final_answer_extra_field = _passed_internal_eval_report()
    internal_final_answer_extra_field["results"][0]["final_answer"]["mystery_field"] = True
    internal_final_answer_extra_score = score_reports(
        internal_final_answer_extra_field,
        openai_passed,
        browser_passed,
    )
    assert internal_final_answer_extra_score["status"] == "needs_work"
    assert any("final_answer unknown field" in blocker for blocker in internal_final_answer_extra_score["blockers"])

    internal_observability_extra_field = _passed_internal_eval_report()
    internal_observability_extra_field["results"][0]["observability"]["mystery_field"] = True
    internal_observability_extra_score = score_reports(
        internal_observability_extra_field,
        openai_passed,
        browser_passed,
    )
    assert internal_observability_extra_score["status"] == "needs_work"
    assert any("observability unknown field" in blocker for blocker in internal_observability_extra_score["blockers"])

    internal_bad_string_list = _passed_internal_eval_report()
    internal_bad_string_list["results"][0]["runtime_event_types"] = "session_completed"
    internal_bad_string_list_score = score_reports(
        internal_bad_string_list,
        openai_passed,
        browser_passed,
    )
    assert internal_bad_string_list_score["status"] == "needs_work"
    assert any("runtime_event_types" in blocker for blocker in internal_bad_string_list_score["blockers"])

    internal_bad_int_list = _passed_internal_eval_report()
    internal_bad_int_list["results"][0]["ledger_tool_turns"] = ["1"]
    internal_bad_int_list_score = score_reports(
        internal_bad_int_list,
        openai_passed,
        browser_passed,
    )
    assert internal_bad_int_list_score["status"] == "needs_work"
    assert any("ledger_tool_turns" in blocker for blocker in internal_bad_int_list_score["blockers"])

    openai_extra_field = dict(openai_passed)
    openai_extra_field["mystery_field"] = True
    extra_openai_score = score_reports(
        full_internal_eval,
        openai_extra_field,
        browser_passed,
    )
    assert extra_openai_score["status"] == "needs_work"
    assert any("unknown field" in blocker for blocker in extra_openai_score["blockers"])

    browser_extra_field = dict(browser_passed)
    browser_extra_field["mystery_field"] = True
    extra_browser_score = score_reports(
        full_internal_eval,
        openai_passed,
        browser_extra_field,
    )
    assert extra_browser_score["status"] == "needs_work"
    assert any("unknown field" in blocker for blocker in extra_browser_score["blockers"])

    openai_bad_ledger_summary = {
        **openai_passed,
        "ledger_summary": {**openai_passed["ledger_summary"], "mystery_field": True},
    }
    bad_openai_ledger_score = score_reports(
        full_internal_eval,
        openai_bad_ledger_summary,
        browser_passed,
    )
    assert bad_openai_ledger_score["status"] == "needs_work"
    assert any("ledger_summary unknown field" in blocker for blocker in bad_openai_ledger_score["blockers"])

    browser_bad_ledger_summary = {
        **browser_passed,
        "ledger_summary": {**browser_passed["ledger_summary"], "mystery_field": True},
    }
    bad_browser_ledger_score = score_reports(
        full_internal_eval,
        openai_passed,
        browser_bad_ledger_summary,
    )
    assert bad_browser_ledger_score["status"] == "needs_work"
    assert any("ledger_summary unknown field" in blocker for blocker in bad_browser_ledger_score["blockers"])

    openai_bad_observability = {
        **openai_passed,
        "observability": {**openai_passed["observability"], "mystery_field": True},
    }
    bad_openai_observability_score = score_reports(
        full_internal_eval,
        openai_bad_observability,
        browser_passed,
    )
    assert bad_openai_observability_score["status"] == "needs_work"
    assert any("observability unknown field" in blocker for blocker in bad_openai_observability_score["blockers"])

    openai_bad_alignment = {
        **openai_passed,
        "observability": {
            **openai_passed["observability"],
            "aligned": {**openai_passed["observability"]["aligned"], "mystery_field": True},
        },
    }
    bad_openai_alignment_score = score_reports(
        full_internal_eval,
        openai_bad_alignment,
        browser_passed,
    )
    assert bad_openai_alignment_score["status"] == "needs_work"
    assert any("observability.aligned unknown field" in blocker for blocker in bad_openai_alignment_score["blockers"])

    browser_bad_tool_result = {
        **browser_passed,
        "tool_result": {**browser_passed["tool_result"], "mystery_field": True},
    }
    bad_browser_tool_result_score = score_reports(
        full_internal_eval,
        openai_passed,
        browser_bad_tool_result,
    )
    assert bad_browser_tool_result_score["status"] == "needs_work"
    assert any("tool_result unknown field" in blocker for blocker in bad_browser_tool_result_score["blockers"])

    browser_bad_ledger_event_count = {
        **browser_passed,
        "ledger_event_count": int(browser_passed["ledger_summary"]["event_count"]) + 1,
    }
    bad_browser_ledger_event_count_score = score_reports(
        full_internal_eval,
        openai_passed,
        browser_bad_ledger_event_count,
    )
    assert bad_browser_ledger_event_count_score["status"] == "needs_work"
    assert any("ledger_event_count" in blocker for blocker in bad_browser_ledger_event_count_score["blockers"])

    openai_wrong_run_id = json.loads(json.dumps(openai_passed))
    openai_wrong_run_id["run_id"] = "browser_agent_e2e_wrong_type"
    openai_wrong_run_id["ledger_summary"]["run_id"] = openai_wrong_run_id["run_id"]
    openai_wrong_run_id["observability"]["run_id"] = openai_wrong_run_id["run_id"]
    openai_wrong_run_id["observability"]["ledger"]["run_id"] = openai_wrong_run_id["run_id"]
    openai_wrong_run_id["observability"]["runtime_host"]["session_ids"] = [openai_wrong_run_id["run_id"]]
    bad_openai_run_id_score = score_reports(
        full_internal_eval,
        openai_wrong_run_id,
        browser_passed,
    )
    assert bad_openai_run_id_score["status"] == "needs_work"
    assert any("run_id prefix" in blocker for blocker in bad_openai_run_id_score["blockers"])

    browser_wrong_run_id = json.loads(json.dumps(browser_passed))
    browser_wrong_run_id["run_id"] = "openai_e2e_wrong_type"
    browser_wrong_run_id["ledger_summary"]["run_id"] = browser_wrong_run_id["run_id"]
    bad_browser_run_id_score = score_reports(
        full_internal_eval,
        openai_passed,
        browser_wrong_run_id,
    )
    assert bad_browser_run_id_score["status"] == "needs_work"
    assert any("run_id prefix" in blocker for blocker in bad_browser_run_id_score["blockers"])

    openai_with_tools = json.loads(json.dumps(openai_passed))
    openai_with_tools["ledger_summary"]["tools"] = {"web_search": 1}
    openai_with_tools["observability"]["ledger"]["tools"] = {"web_search": 1}
    bad_openai_tools_score = score_reports(
        full_internal_eval,
        openai_with_tools,
        browser_passed,
    )
    assert bad_openai_tools_score["status"] == "needs_work"
    assert any("tools" in blocker for blocker in bad_openai_tools_score["blockers"])

    browser_without_browser_tool = json.loads(json.dumps(browser_passed))
    browser_without_browser_tool["ledger_summary"]["tools"] = {}
    bad_browser_tools_score = score_reports(
        full_internal_eval,
        openai_passed,
        browser_without_browser_tool,
    )
    assert bad_browser_tools_score["status"] == "needs_work"
    assert any("browser_agent tool" in blocker for blocker in bad_browser_tools_score["blockers"])

    browser_bool_tool_count = json.loads(json.dumps(browser_passed))
    browser_bool_tool_count["ledger_summary"]["tools"] = {"browser_agent": True}
    bad_browser_tool_count_score = score_reports(
        full_internal_eval,
        openai_passed,
        browser_bool_tool_count,
    )
    assert bad_browser_tool_count_score["status"] == "needs_work"
    assert any("tools is invalid" in blocker for blocker in bad_browser_tool_count_score["blockers"])

    openai_bad_owner = json.loads(json.dumps(openai_passed))
    openai_bad_owner["ledger_summary"]["owner_layer"] = "Layer 1 capability contract"
    openai_bad_owner["observability"]["ledger"]["owner_layer"] = "Layer 1 capability contract"
    bad_openai_owner_score = score_reports(
        full_internal_eval,
        openai_bad_owner,
        browser_passed,
    )
    assert bad_openai_owner_score["status"] == "needs_work"
    assert any("owner_layer" in blocker for blocker in bad_openai_owner_score["blockers"])

    openai_bad_task = json.loads(json.dumps(openai_passed))
    openai_bad_task["ledger_summary"]["task"] = "Reply with OK."
    openai_bad_task["observability"]["ledger"]["task"] = "Reply with OK."
    bad_openai_task_score = score_reports(
        full_internal_eval,
        openai_bad_task,
        browser_passed,
    )
    assert bad_openai_task_score["status"] == "needs_work"
    assert any("task" in blocker for blocker in bad_openai_task_score["blockers"])

    browser_bad_owner = json.loads(json.dumps(browser_passed))
    browser_bad_owner["ledger_summary"]["owner_layer"] = "Layer 3 runtime controller"
    bad_browser_owner_score = score_reports(
        full_internal_eval,
        openai_passed,
        browser_bad_owner,
    )
    assert bad_browser_owner_score["status"] == "needs_work"
    assert any("owner_layer" in blocker for blocker in bad_browser_owner_score["blockers"])

    impossible_internal_total = _passed_internal_eval_report()
    impossible_internal_total["results"][0]["total"] = 150
    impossible_score = score_reports(
        impossible_internal_total,
        openai_passed,
        browser_passed,
    )
    assert impossible_score["status"] == "needs_work"
    assert any("result total" in blocker for blocker in impossible_score["blockers"])

    invalid_internal_verdict = _passed_internal_eval_report()
    invalid_internal_verdict["results"][0]["verdict"] = "maybe"
    invalid_verdict_score = score_reports(
        invalid_internal_verdict,
        openai_passed,
        browser_passed,
    )
    assert invalid_verdict_score["status"] == "needs_work"
    assert any("result verdict" in blocker for blocker in invalid_verdict_score["blockers"])

    polluted_internal_results = _passed_internal_eval_report()
    polluted_internal_results["results"].append("polluted result row")
    polluted_score = score_reports(
        polluted_internal_results,
        openai_passed,
        browser_passed,
    )
    assert polluted_score["status"] == "needs_work"
    assert any("result entry" in blocker for blocker in polluted_score["blockers"])

    non_list_internal_results = _passed_internal_eval_report()
    non_list_internal_results["results"] = {"case_id": "not-a-list"}
    non_list_score = score_reports(
        non_list_internal_results,
        openai_passed,
        browser_passed,
    )
    assert non_list_score["status"] == "needs_work"
    assert any("results must be a list" in blocker for blocker in non_list_score["blockers"])

    thin_internal_eval = score_reports(
        {"results": [{"case_id": "a", "total": 100, "verdict": "pass"}]},
        openai_passed,
        browser_passed,
    )
    assert thin_internal_eval["status"] == "needs_work"
    assert any("missing cases" in blocker for blocker in thin_internal_eval["blockers"])

    inconsistent_internal_summary = dict(full_internal_eval)
    inconsistent_internal_summary["passed"] = 0
    inconsistent_score = score_reports(
        inconsistent_internal_summary,
        openai_passed,
        browser_passed,
    )
    assert inconsistent_score["status"] == "needs_work"
    assert any("passed count" in blocker for blocker in inconsistent_score["blockers"])

    thin_e2e_evidence = score_reports(
        full_internal_eval,
        {"status": "passed"},
        {"status": "passed"},
    )
    assert thin_e2e_evidence["status"] == "needs_work"
    assert any("missing run_id" in blocker for blocker in thin_e2e_evidence["blockers"])

    openai_without_observability = dict(openai_passed)
    openai_without_observability.pop("observability", None)
    missing_openai_observability = score_reports(
        full_internal_eval,
        openai_without_observability,
        browser_passed,
    )
    assert missing_openai_observability["status"] == "needs_work"
    assert any("observability" in blocker for blocker in missing_openai_observability["blockers"])

    browser_without_result = dict(browser_passed)
    browser_without_result["tool_result"] = {"success": True}
    browser_without_result.pop("ledger_event_count", None)
    thin_browser_result = score_reports(
        full_internal_eval,
        openai_passed,
        browser_without_result,
    )
    assert thin_browser_result["status"] == "needs_work"
    assert any("browser_agent result" in blocker for blocker in thin_browser_result["blockers"])

    skipped_optional = score_reports(
        full_internal_eval,
        {"status": "skipped", "reason": "openai e2e disabled"},
        {"status": "skipped", "reason": "browser e2e disabled"},
    )
    assert skipped_optional["status"] == "needs_work"
    assert skipped_optional["total"] == 70
    assert _exit_code_for_report(skipped_optional, strict=True) == 1

    skipped_with_extra_field = score_reports(
        full_internal_eval,
        {"status": "skipped", "reason": "openai e2e disabled", "mystery_field": True},
        {"status": "skipped", "reason": "browser e2e disabled"},
    )
    assert skipped_with_extra_field["status"] == "needs_work"
    assert skipped_with_extra_field["total"] == 70
    assert any("unknown field" in blocker for blocker in skipped_with_extra_field["blockers"])

    original_weight = SCORE_COMPONENT_WEIGHTS["browser_agent_e2e"]
    try:
        SCORE_COMPONENT_WEIGHTS["browser_agent_e2e"] = original_weight + 5
        shifted_weights = score_reports(
            full_internal_eval,
            openai_passed,
            browser_passed,
        )
        assert shifted_weights["max_total"] == sum(SCORE_COMPONENT_WEIGHTS.values())
        assert shifted_weights["status"] == "ok"
    finally:
        SCORE_COMPONENT_WEIGHTS["browser_agent_e2e"] = original_weight

    failed_optional = score_reports(
        full_internal_eval,
        {"status": "failed", "failure_class": "readiness_failure", "reason": "openai-agents missing"},
        {"status": "failed", "failure_class": "readiness_failure", "reason": "browser-use missing"},
    )
    assert failed_optional["total"] == 70
    assert len(failed_optional["blockers"]) == 2

    failed_with_extra_field = score_reports(
        full_internal_eval,
        {
            "status": "failed",
            "failure_class": "readiness_failure",
            "reason": "openai-agents missing",
            "mystery_field": True,
        },
        {"status": "failed", "failure_class": "readiness_failure", "reason": "browser-use missing"},
    )
    assert failed_with_extra_field["status"] == "needs_work"
    assert failed_with_extra_field["total"] == 70
    assert any("unknown field" in blocker for blocker in failed_with_extra_field["blockers"])

    startup_detail = score_reports(
        full_internal_eval,
        {"status": "failed", "reason": "not ready", "startup_error": "agents module missing"},
        browser_passed,
    )
    assert "agents module missing" in startup_detail["blockers"]

    refresh_targets = [Path(command[1]).name for command in _refresh_commands()]
    assert refresh_targets == [
        "run_eval_cases.py",
        "smoke_openai_orchestrated_e2e.py",
        "smoke_browser_agent_e2e.py",
    ]

    captured = subprocess.CalledProcessError(
        1,
        ["python", "child.py"],
        output="child stdout",
        stderr="child stderr",
    )
    assert _captured_process_output_sections(captured) == [
        ("stdout", "child stdout"),
        ("stderr", "child stderr"),
    ]

    failing_command = [
        sys.executable,
        "-c",
        (
            "import sys; "
            "print('refresh child stdout'); "
            "print('refresh child stderr', file=sys.stderr); "
            "raise SystemExit(7)"
        ),
    ]
    try:
        _run_refresh_command(failing_command)
    except subprocess.CalledProcessError as exc:
        assert exc.returncode == 7
        assert _captured_process_output_sections(exc) == [
            ("stdout", "refresh child stdout"),
            ("stderr", "refresh child stderr"),
        ]
    else:
        raise AssertionError("failing refresh child command unexpectedly passed")

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        (tmp_path / "latest_eval_report.json").write_text(
            json.dumps(passing_eval),
            encoding="utf-8",
        )
        (tmp_path / "latest_openai_e2e_report.json").write_text(
            json.dumps(openai_passed),
            encoding="utf-8",
        )
        (tmp_path / "latest_browser_agent_e2e_report.json").write_text(
            json.dumps(browser_passed),
            encoding="utf-8",
        )
        advisory = subprocess.run(
            [
                sys.executable,
                str(Path(__file__).resolve()),
                "--results-dir",
                str(tmp_path),
                "--no-write",
            ],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        advisory_report = json.loads(advisory.stdout)
        assert advisory_report["status"] == "needs_work"
        assert advisory_report["evidence"]["results_dir"] == str(tmp_path.resolve())
        assert advisory_report["evidence"]["generated_at_utc"].endswith("Z")
        assert advisory_report["evidence"]["source_git"]["available"] is True
        assert isinstance(advisory_report["evidence"]["source_git"]["head"], str)
        assert isinstance(advisory_report["evidence"]["source_git"]["dirty"], bool)
        assert advisory_report["evidence"]["input_reports"]["latest_eval_report.json"]["exists"] is True
        assert advisory_report["evidence"]["input_reports"]["latest_openai_e2e_report.json"]["exists"] is True
        assert advisory_report["evidence"]["input_reports"]["latest_browser_agent_e2e_report.json"]["exists"] is True

        strict = subprocess.run(
            [
                sys.executable,
                str(Path(__file__).resolve()),
                "--results-dir",
                str(tmp_path),
                "--no-write",
                "--strict",
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        assert strict.returncode == 1
        assert json.loads(strict.stdout)["status"] == "needs_work"

        invalid_combo = subprocess.run(
            [
                sys.executable,
                str(Path(__file__).resolve()),
                "--results-dir",
                str(tmp_path),
                "--refresh",
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        assert invalid_combo.returncode != 0
        assert "--refresh cannot be combined with --results-dir" in invalid_combo.stderr

        missing_no_write = subprocess.run(
            [
                sys.executable,
                str(Path(__file__).resolve()),
                "--results-dir",
                str(tmp_path),
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        assert missing_no_write.returncode != 0
        assert "--results-dir requires --no-write" in missing_no_write.stderr


if __name__ == "__main__":
    raise SystemExit(main())
