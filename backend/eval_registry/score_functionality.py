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
RESULTS_DIR = ROOT / "backend" / "eval_registry" / "results"
OUTPUT_PATH = RESULTS_DIR / "latest_functionality_score.json"

SCORE_COMPONENT_WEIGHTS = {
    "internal_eval": 70,
    "openai_orchestrated_e2e": 15,
    "browser_agent_e2e": 15,
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
        _read_json(base / "latest_eval_report.json"),
        _read_json(base / "latest_openai_e2e_report.json"),
        _read_json(base / "latest_browser_agent_e2e_report.json"),
    )


def score_reports(
    eval_report: dict[str, Any] | None,
    openai_report: dict[str, Any] | None,
    browser_agent_report: dict[str, Any] | None,
) -> dict[str, Any]:
    components = [
        _score_internal_eval(eval_report, SCORE_COMPONENT_WEIGHTS["internal_eval"]),
        _score_optional_e2e(
            "openai_orchestrated_e2e",
            openai_report,
            SCORE_COMPONENT_WEIGHTS["openai_orchestrated_e2e"],
            "OpenAI orchestrated SDK path is not proven",
        ),
        _score_optional_e2e(
            "browser_agent_e2e",
            browser_agent_report,
            SCORE_COMPONENT_WEIGHTS["browser_agent_e2e"],
            "browser_agent real browser/LLM path is not proven",
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
    results = [item for item in report.get("results") or [] if isinstance(item, dict)]
    if not results:
        return _component("internal_eval", weight, 0, "missing", ["latest_eval_report.json has no results"])
    average = sum(float(item.get("total") or 0) for item in results) / len(results)
    score = round(weight * average / 100)
    failed = [str(item.get("case_id") or "") for item in results if item.get("verdict") != "pass"]
    coverage_blockers = _internal_eval_coverage_blockers(report, results)
    if coverage_blockers:
        return {
            **_component("internal_eval", weight, 0, "invalid_evidence", coverage_blockers),
            "case_count": len(results),
            "passed": len(results) - len(failed),
            "failed": len(failed),
            "average_case_score": round(average, 2),
        }
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


def _score_optional_e2e(name: str, report: dict[str, Any] | None, weight: int, missing_msg: str) -> dict[str, Any]:
    if not report:
        return _component(name, weight, 0, "missing", [missing_msg])
    status = str(report.get("status") or "unknown")
    if status == "passed":
        evidence_errors = _passed_optional_e2e_errors(name, report)
        if evidence_errors:
            return _component(name, weight, 0, "invalid_evidence", evidence_errors)
        return _component(name, weight, weight, "passed", [])
    reason = str(report.get("startup_error") or report.get("reason") or missing_msg)
    failure_class = str(report.get("failure_class") or status)
    return {
        **_component(name, weight, 0, failure_class, [reason]),
        "evidence_status": status,
    }


def _passed_optional_e2e_errors(name: str, report: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    run_id = str(report.get("run_id") or "").strip()
    if not run_id:
        errors.append(f"{name} passed report missing run_id")
    ledger = report.get("ledger_summary")
    if not isinstance(ledger, dict):
        errors.append(f"{name} passed report missing ledger_summary")
        return errors
    if run_id and str(ledger.get("run_id") or "") != run_id:
        errors.append(f"{name} ledger_summary.run_id does not match run_id")
    if not isinstance(ledger.get("event_count"), int) or int(ledger.get("event_count") or 0) <= 0:
        errors.append(f"{name} passed report missing ledger events")
    if str(ledger.get("final_status") or "") != "success":
        errors.append(f"{name} passed report final_status is not success")
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
        elif not str(tool_result.get("result") or "").strip():
            errors.append(f"{name} passed report missing browser_agent result")
        elif not isinstance(tool_result.get("steps_taken"), int) or int(tool_result.get("steps_taken") or 0) <= 0:
            errors.append(f"{name} passed report missing positive steps_taken")
        if not isinstance(report.get("ledger_event_count"), int) or int(report.get("ledger_event_count") or 0) <= 0:
            errors.append(f"{name} passed report missing ledger_event_count")
    return errors


def _openai_observability_errors(name: str, report: dict[str, Any]) -> list[str]:
    observability = report.get("observability")
    if not isinstance(observability, dict):
        return [f"{name} passed report missing observability"]
    aligned = observability.get("aligned")
    if not isinstance(aligned, dict):
        return [f"{name} passed report missing observability alignment"]
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
            "GAGENT_E2E_DEPS": os.environ.get("GAGENT_E2E_DEPS", ""),
            "GAGENT_RUN_OPENAI_E2E": os.environ.get("GAGENT_RUN_OPENAI_E2E", ""),
            "GAGENT_RUN_BROWSER_AGENT_E2E": os.environ.get("GAGENT_RUN_BROWSER_AGENT_E2E", ""),
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
    for name in [
        "latest_eval_report.json",
        "latest_openai_e2e_report.json",
        "latest_browser_agent_e2e_report.json",
    ]:
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
    run_id = f"{name}_run"
    report: dict[str, Any] = {
        "status": "passed",
        "run_id": run_id,
        "ledger_summary": {
            "run_id": run_id,
            "event_count": 2,
            "final_status": "success",
        },
    }
    if name == "openai_orchestrated_e2e":
        report["done"] = "OPENAI_E2E_OK"
        report["observability"] = {
            "aligned": {
                "has_ledger_events": True,
                "has_runtime_host_events": True,
                "ledger_run_id_matches_requested": True,
                "runtime_session_matches_run_id": True,
            }
        }
    if name == "browser_agent_e2e":
        report["tool_result"] = {
            "success": True,
            "result": "Example Domain",
            "steps_taken": 2,
        }
        report["ledger_event_count"] = 4
    return report


def _passed_internal_eval_report(*, partial: bool = False) -> dict[str, Any]:
    results = []
    for index, case_id in enumerate(_expected_eval_case_ids()):
        results.append({
            "case_id": case_id,
            "total": 80 if partial and index == 0 else 100,
            "verdict": "pass",
        })
    return {
        "status": "ok",
        "case_count": len(results),
        "passed": len(results),
        "failed": 0,
        "skipped": 0,
        "results": results,
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
