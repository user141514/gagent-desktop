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

INTERNAL_EVAL_WEIGHT = 70
OPENAI_E2E_WEIGHT = 15
BROWSER_AGENT_E2E_WEIGHT = 15


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
        _score_internal_eval(eval_report, INTERNAL_EVAL_WEIGHT),
        _score_optional_e2e(
            "openai_orchestrated_e2e",
            openai_report,
            OPENAI_E2E_WEIGHT,
            "OpenAI orchestrated SDK path is not proven",
        ),
        _score_optional_e2e(
            "browser_agent_e2e",
            browser_agent_report,
            BROWSER_AGENT_E2E_WEIGHT,
            "browser_agent real browser/LLM path is not proven",
        ),
    ]
    total = sum(int(item["score"]) for item in components)
    blockers = [blocker for item in components for blocker in item.get("blockers", [])]
    return {
        "status": "ok" if total == 100 else "needs_work",
        "total": total,
        "max_total": 100,
        "components": components,
        "blockers": blockers,
    }


def _score_internal_eval(report: dict[str, Any] | None, weight: int) -> dict[str, Any]:
    if not report:
        return _component("internal_eval", weight, 0, "missing", ["latest_eval_report.json is missing"])
    results = [item for item in report.get("results") or [] if isinstance(item, dict)]
    if not results:
        return _component("internal_eval", weight, 0, "missing", ["latest_eval_report.json has no results"])
    average = sum(float(item.get("total") or 0) for item in results) / len(results)
    score = round(weight * average / 100)
    failed = [str(item.get("case_id") or "") for item in results if item.get("verdict") != "pass"]
    blockers = [f"eval case not passing: {case_id}" for case_id in failed if case_id]
    return {
        **_component("internal_eval", weight, score, "passed" if not failed else "failed", blockers),
        "case_count": len(results),
        "passed": len(results) - len(failed),
        "failed": len(failed),
        "average_case_score": round(average, 2),
    }


def _score_optional_e2e(name: str, report: dict[str, Any] | None, weight: int, missing_msg: str) -> dict[str, Any]:
    if not report:
        return _component(name, weight, 0, "missing", [missing_msg])
    status = str(report.get("status") or "unknown")
    if status == "passed":
        return _component(name, weight, weight, "passed", [])
    reason = str(report.get("startup_error") or report.get("reason") or missing_msg)
    failure_class = str(report.get("failure_class") or status)
    return {
        **_component(name, weight, 0, failure_class, [reason]),
        "evidence_status": status,
    }


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


def _self_test() -> None:
    passing_eval = {
        "results": [
            {"case_id": "a", "total": 100, "verdict": "pass"},
            {"case_id": "b", "total": 80, "verdict": "pass"},
        ]
    }
    passed = score_reports(passing_eval, {"status": "passed"}, {"status": "passed"})
    assert passed["status"] == "needs_work"
    assert passed["total"] == 93
    assert _exit_code_for_report(passed, strict=False) == 0
    assert _exit_code_for_report(passed, strict=True) == 1

    complete = score_reports(
        {"results": [{"case_id": "a", "total": 100, "verdict": "pass"}]},
        {"status": "passed"},
        {"status": "passed"},
    )
    assert complete["status"] == "ok"
    assert _exit_code_for_report(complete, strict=True) == 0

    skipped_optional = score_reports(
        {"results": [{"case_id": "a", "total": 100, "verdict": "pass"}]},
        {"status": "skipped", "reason": "openai e2e disabled"},
        {"status": "skipped", "reason": "browser e2e disabled"},
    )
    assert skipped_optional["status"] == "needs_work"
    assert skipped_optional["total"] == 70
    assert _exit_code_for_report(skipped_optional, strict=True) == 1

    failed_optional = score_reports(
        {"results": [{"case_id": "a", "total": 100, "verdict": "pass"}]},
        {"status": "failed", "failure_class": "readiness_failure", "reason": "openai-agents missing"},
        {"status": "failed", "failure_class": "readiness_failure", "reason": "browser-use missing"},
    )
    assert failed_optional["total"] == 70
    assert len(failed_optional["blockers"]) == 2

    startup_detail = score_reports(
        {"results": [{"case_id": "a", "total": 100, "verdict": "pass"}]},
        {"status": "failed", "reason": "not ready", "startup_error": "agents module missing"},
        {"status": "passed"},
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
            json.dumps({"status": "passed"}),
            encoding="utf-8",
        )
        (tmp_path / "latest_browser_agent_e2e_report.json").write_text(
            json.dumps({"status": "passed"}),
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
