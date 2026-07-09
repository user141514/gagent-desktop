#!/usr/bin/env python
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

EVAL_REGISTRY_DIR = Path(__file__).resolve().parent
if str(EVAL_REGISTRY_DIR) not in sys.path:
    sys.path.insert(0, str(EVAL_REGISTRY_DIR))
import score_functionality


ROOT = Path(__file__).resolve().parents[2]
PYTHON = ROOT / "python-runtime" / ("python.exe" if os.name == "nt" else "bin/python")
SCORE_COMPONENT_WEIGHTS = score_functionality.SCORE_COMPONENT_WEIGHTS
SCORE_INPUT_REPORTS = score_functionality.SCORE_INPUT_REPORTS
SCORE_E2E_ENV_KEYS = score_functionality.SCORE_E2E_ENV_KEYS
BASE_COMPONENT_FIELDS = score_functionality.BASE_COMPONENT_FIELDS
COMPONENT_EXTRA_FIELDS = score_functionality.COMPONENT_EXTRA_FIELDS
SCORE_EVIDENCE_FIELDS = score_functionality.SCORE_EVIDENCE_FIELDS
SOURCE_GIT_FIELDS = score_functionality.SOURCE_GIT_FIELDS
INPUT_REPORT_FIELDS = score_functionality.INPUT_REPORT_FIELDS
REFRESH_REPORT_MAX_AGE = timedelta(minutes=30)
REFRESH_REPORT_FUTURE_SKEW = timedelta(minutes=2)
INPUT_REPORT_STAT_SKEW = timedelta(seconds=2)
E2E_DEPS_MARKERS = ("agents", "browser_use", "playwright")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run gagent-desktop convergence gates.")
    parser.add_argument("--self-test", action="store_true", help="run runner self-tests")
    parser.add_argument("--full", action="store_true", help="run strict full-flow score gate after baseline checks")
    args = parser.parse_args()

    if args.self_test:
        _self_test()
        print("[run_convergence_checks] self-test ok")
        return 0

    commands = _commands(full=bool(args.full))
    env = {**os.environ, "PYTHONUTF8": "1"}
    for command in commands:
        label = " ".join(command[1:])
        result = subprocess.run(
            command,
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if result.returncode != 0:
            print(f"[run_convergence_checks] failed: {label}", file=sys.stderr)
            if result.stdout.strip():
                print(result.stdout.strip(), file=sys.stderr)
            if result.stderr.strip():
                print(result.stderr.strip(), file=sys.stderr)
            return int(result.returncode or 1)
        print(f"[run_convergence_checks] ok: {label}")
        try:
            success_output = _success_output_for(command, result.stdout, validate_written_artifact=True)
        except ValueError as exc:
            print(f"[run_convergence_checks] failed: {label}", file=sys.stderr)
            print(str(exc), file=sys.stderr)
            return 1
        if success_output:
            print(success_output)
    print("[run_convergence_checks] ok")
    return 0


def _commands(*, full: bool) -> list[list[str]]:
    score_command = [str(PYTHON), "backend/eval_registry/score_functionality.py", "--refresh"]
    if full:
        score_command.append("--strict")
    return [
        [str(PYTHON), "backend/tool_registry/validate_tool_registry.py"],
        [str(PYTHON), "backend/quality_registry/validate_quality_registry.py"],
        [str(PYTHON), "backend/tool_registry/tests/smoke_web_tools.py"],
        [str(PYTHON), "backend/eval_registry/validate_eval_registry.py"],
        [str(PYTHON), "backend/eval_registry/tests/smoke_eval_registry.py"],
        score_command,
        [str(PYTHON), "backend/runtime_ledger/validate_runtime_ledger.py"],
        [str(PYTHON), "backend/runtime_ledger/tests/smoke_runtime_ledger.py"],
    ]


def _success_output_for(command: list[str], stdout: str, *, validate_written_artifact: bool = False) -> str:
    if not _is_score_command(command):
        return ""
    try:
        score = json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise ValueError(f"score_functionality output is not valid JSON: {exc}") from exc
    if not isinstance(score, dict):
        raise ValueError("score_functionality output is not a JSON object")
    _validate_score_mode(command, score)
    _validate_score_components(score)
    _validate_score_evidence(command, score)
    if validate_written_artifact and "--refresh" in command:
        _validate_score_artifact_matches_stdout(score_functionality.OUTPUT_PATH, score)
    return json.dumps(score, indent=2, ensure_ascii=False)


def _is_score_command(command: list[str]) -> bool:
    return len(command) > 1 and command[1].replace("\\", "/").endswith(
        "backend/eval_registry/score_functionality.py"
    )


def _validate_score_mode(command: list[str], score: dict) -> None:
    if score.get("refreshed") is not ("--refresh" in command):
        raise ValueError("score_functionality refreshed flag does not match runner command")
    if score.get("strict") is not ("--strict" in command):
        raise ValueError("score_functionality strict flag does not match runner command")


def _validate_score_components(score: dict) -> None:
    components = score.get("components")
    if not isinstance(components, list):
        raise ValueError("score_functionality components are missing")
    if len(components) != len(SCORE_COMPONENT_WEIGHTS):
        raise ValueError("score_functionality component count is invalid")

    seen: set[str] = set()
    total = 0
    blockers: list[str] = []
    for component in components:
        if not isinstance(component, dict):
            raise ValueError("score_functionality component is invalid")
        name = component.get("name")
        if not isinstance(name, str) or name not in SCORE_COMPONENT_WEIGHTS:
            raise ValueError("score_functionality component name is invalid")
        allowed_fields = BASE_COMPONENT_FIELDS | COMPONENT_EXTRA_FIELDS.get(name, set())
        unknown_fields = sorted(set(component) - allowed_fields)
        if unknown_fields:
            raise ValueError(f"score_functionality component {name} has unknown fields: {', '.join(unknown_fields)}")
        status = component.get("status")
        if not isinstance(status, str) or not status:
            raise ValueError(f"score_functionality component {name} status is invalid")
        if name in seen:
            raise ValueError(f"score_functionality component {name} is duplicated")
        seen.add(name)
        if component.get("weight") != SCORE_COMPONENT_WEIGHTS[name]:
            raise ValueError(f"score_functionality component {name} weight is invalid")
        component_score = component.get("score")
        if not isinstance(component_score, int) or component_score < 0 or component_score > SCORE_COMPONENT_WEIGHTS[name]:
            raise ValueError(f"score_functionality component {name} score is invalid")
        total += component_score
        component_blockers = component.get("blockers")
        if not isinstance(component_blockers, list) or not all(isinstance(item, str) for item in component_blockers):
            raise ValueError(f"score_functionality component {name} blockers are invalid")
        blockers.extend(component_blockers)

    max_total = sum(SCORE_COMPONENT_WEIGHTS.values())
    if score.get("total") != total:
        raise ValueError("score_functionality total does not match component scores")
    if score.get("max_total") != max_total:
        raise ValueError("score_functionality max_total does not match component weights")
    expected_status = "ok" if total == max_total else "needs_work"
    if score.get("status") != expected_status:
        raise ValueError("score_functionality status does not match total")
    if score.get("blockers") != blockers:
        raise ValueError("score_functionality blockers do not match component blockers")


def _validate_score_evidence(command: list[str], score: dict) -> None:
    evidence = score.get("evidence")
    if not isinstance(evidence, dict):
        raise ValueError("score_functionality evidence is missing")
    unknown_evidence_fields = sorted(set(evidence) - SCORE_EVIDENCE_FIELDS)
    if unknown_evidence_fields:
        raise ValueError("score_functionality evidence has unknown fields: " + ", ".join(unknown_evidence_fields))
    for key in ["generated_at_utc", "results_dir", "python_executable"]:
        if not isinstance(evidence.get(key), str) or not evidence[key]:
            raise ValueError(f"score_functionality evidence.{key} is missing")
    if _canonical_path(evidence["results_dir"]) != _canonical_path(ROOT / "backend" / "eval_registry" / "results"):
        raise ValueError("score_functionality evidence.results_dir does not match expected results directory")
    if _canonical_path(evidence["python_executable"]) != _canonical_path(PYTHON):
        raise ValueError("score_functionality evidence.python_executable does not match bundled Python")
    if not evidence["generated_at_utc"].endswith("Z"):
        raise ValueError("score_functionality evidence.generated_at_utc must be UTC")
    generated_at = _parse_utc_timestamp(
        evidence["generated_at_utc"],
        "score_functionality evidence.generated_at_utc",
    )

    e2e_env = evidence.get("e2e_env")
    if not isinstance(e2e_env, dict):
        raise ValueError("score_functionality evidence.e2e_env is missing")
    unknown_e2e_env_fields = sorted(set(e2e_env) - set(SCORE_E2E_ENV_KEYS))
    if unknown_e2e_env_fields:
        raise ValueError("score_functionality evidence.e2e_env has unknown fields: " + ", ".join(unknown_e2e_env_fields))
    for key in SCORE_E2E_ENV_KEYS:
        if not isinstance(e2e_env.get(key), str):
            raise ValueError(f"score_functionality evidence.e2e_env.{key} is missing")
    if "--strict" in command:
        if not e2e_env.get("GAGENT_E2E_DEPS", "").strip():
            raise ValueError("score_functionality evidence.e2e_env.GAGENT_E2E_DEPS is required for strict convergence")
        e2e_deps_path = ROOT / "backend" / "temp" / "e2e_deps"
        if _canonical_path(e2e_env["GAGENT_E2E_DEPS"]) != _canonical_path(e2e_deps_path):
            raise ValueError("score_functionality evidence.e2e_env.GAGENT_E2E_DEPS does not match expected e2e deps path")
        _validate_e2e_deps_dir(e2e_deps_path)
        for key in ["GAGENT_RUN_OPENAI_E2E", "GAGENT_RUN_BROWSER_AGENT_E2E"]:
            if e2e_env.get(key) != "1":
                raise ValueError(f"score_functionality evidence.e2e_env.{key} must be 1 for strict convergence")

    source_git = evidence.get("source_git")
    if not isinstance(source_git, dict):
        raise ValueError("score_functionality evidence.source_git is missing")
    unknown_source_git_fields = sorted(set(source_git) - SOURCE_GIT_FIELDS)
    if unknown_source_git_fields:
        raise ValueError(
            "score_functionality evidence.source_git has unknown fields: " + ", ".join(unknown_source_git_fields)
        )
    if source_git.get("available") is not True:
        raise ValueError("score_functionality evidence.source_git is unavailable")
    if not isinstance(source_git.get("head"), str) or len(source_git["head"]) < 7:
        raise ValueError("score_functionality evidence.source_git.head is missing")
    current_head = _current_git_head()
    if not current_head:
        raise ValueError("current git HEAD is unavailable")
    if source_git["head"] != current_head:
        raise ValueError("score_functionality evidence.source_git.head does not match current HEAD")
    if not isinstance(source_git.get("branch"), str):
        raise ValueError("score_functionality evidence.source_git.branch is missing")
    current_branch = _current_git_branch()
    if current_branch is None:
        raise ValueError("current git branch is unavailable")
    if source_git["branch"] != current_branch:
        raise ValueError("score_functionality evidence.source_git.branch does not match current branch")
    if not isinstance(source_git.get("dirty"), bool):
        raise ValueError("score_functionality evidence.source_git.dirty is missing")
    if "--strict" in command and source_git["dirty"]:
        raise ValueError("score_functionality evidence.source_git.dirty must be false for strict convergence")

    results_dir = Path(evidence["results_dir"])
    input_reports = evidence.get("input_reports")
    if not isinstance(input_reports, dict):
        raise ValueError("score_functionality evidence.input_reports is missing")
    unknown_input_reports = sorted(set(input_reports) - set(SCORE_INPUT_REPORTS))
    if unknown_input_reports:
        raise ValueError("score_functionality evidence.input_reports has unknown reports: " + ", ".join(unknown_input_reports))
    for name in SCORE_INPUT_REPORTS:
        report = input_reports.get(name)
        if not isinstance(report, dict):
            raise ValueError(f"score_functionality evidence.input_reports.{name} is missing")
        unknown_report_fields = sorted(set(report) - INPUT_REPORT_FIELDS)
        if unknown_report_fields:
            raise ValueError(
                f"score_functionality evidence.input_reports.{name} has unknown fields: "
                + ", ".join(unknown_report_fields)
            )
        if not isinstance(report.get("exists"), bool):
            raise ValueError(f"score_functionality evidence.input_reports.{name}.exists is missing")
        if not report["exists"]:
            raise ValueError(f"score_functionality evidence.input_reports.{name} is missing")
        if not isinstance(report.get("bytes"), int) or report["bytes"] <= 0:
            raise ValueError(f"score_functionality evidence.input_reports.{name}.bytes is invalid")
        modified_at_utc = report.get("modified_at_utc")
        if not isinstance(modified_at_utc, str) or not modified_at_utc.endswith("Z"):
            raise ValueError(f"score_functionality evidence.input_reports.{name}.modified_at_utc is invalid")
        modified_at = _parse_utc_timestamp(
            modified_at_utc,
            f"score_functionality evidence.input_reports.{name}.modified_at_utc",
        )
        if "--refresh" in command:
            _validate_refresh_report_timing(name, generated_at, modified_at)
            _validate_input_report_file_stat(name, results_dir, report, modified_at)


def _validate_score_artifact_matches_stdout(path: Path, expected_score: dict) -> None:
    try:
        artifact = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("latest_functionality_score.json is missing or invalid") from exc
    if not isinstance(artifact, dict):
        raise ValueError("latest_functionality_score.json is not a JSON object")
    if artifact != expected_score:
        raise ValueError("latest_functionality_score.json does not match score_functionality stdout")


def _validate_e2e_deps_dir(path: Path) -> None:
    if not path.is_dir():
        raise ValueError("score_functionality evidence.e2e_env.GAGENT_E2E_DEPS directory is missing")
    missing = [marker for marker in E2E_DEPS_MARKERS if not (path / marker).exists()]
    if missing:
        raise ValueError("score_functionality evidence.e2e_env.GAGENT_E2E_DEPS missing markers: " + ", ".join(missing))


def _parse_utc_timestamp(value: str, label: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.removesuffix("Z") + "+00:00")
    except ValueError as exc:
        raise ValueError(f"{label} is invalid") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{label} must include timezone")
    return parsed.astimezone(timezone.utc)


def _format_utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _canonical_path(value: str | Path) -> str:
    return os.path.normcase(os.path.abspath(str(value)))


def _validate_refresh_report_timing(name: str, generated_at: datetime, modified_at: datetime) -> None:
    if modified_at > generated_at + REFRESH_REPORT_FUTURE_SKEW:
        raise ValueError(f"score_functionality evidence.input_reports.{name} modified_at is in the future")
    if generated_at - modified_at > REFRESH_REPORT_MAX_AGE:
        raise ValueError(f"score_functionality evidence.input_reports.{name} is stale for refreshed score output")


def _validate_input_report_file_stat(name: str, results_dir: Path, report: dict, modified_at: datetime) -> None:
    path = results_dir / name
    try:
        stat = path.stat()
    except OSError as exc:
        raise ValueError(f"score_functionality evidence.input_reports.{name} file is missing on disk") from exc
    if stat.st_size != report.get("bytes"):
        raise ValueError(f"score_functionality evidence.input_reports.{name}.bytes does not match disk file")
    actual_modified_at = datetime.fromtimestamp(stat.st_mtime, timezone.utc)
    if abs(actual_modified_at - modified_at) > INPUT_REPORT_STAT_SKEW:
        raise ValueError(
            f"score_functionality evidence.input_reports.{name}.modified_at_utc does not match disk file"
        )


def _current_git_head() -> str | None:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def _current_git_branch() -> str | None:
    branch = _git_output("branch", "--show-current")
    if branch:
        return branch
    return _git_output("rev-parse", "--abbrev-ref", "HEAD")


def _git_output(*args: str) -> str | None:
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


def _self_test() -> None:
    score_command = [str(PYTHON), "backend/eval_registry/score_functionality.py", "--refresh"]
    strict_score_command = [*score_command, "--strict"]
    smoke_command = [str(PYTHON), "backend/eval_registry/tests/smoke_eval_registry.py"]
    assert _is_score_command(score_command)
    assert not _is_score_command(smoke_command)
    assert _commands(full=False)[5] == score_command
    assert _commands(full=True)[5] == strict_score_command
    assert SCORE_COMPONENT_WEIGHTS is score_functionality.SCORE_COMPONENT_WEIGHTS
    assert SCORE_INPUT_REPORTS is score_functionality.SCORE_INPUT_REPORTS
    assert SCORE_E2E_ENV_KEYS is score_functionality.SCORE_E2E_ENV_KEYS
    assert BASE_COMPONENT_FIELDS is score_functionality.BASE_COMPONENT_FIELDS
    assert COMPONENT_EXTRA_FIELDS is score_functionality.COMPONENT_EXTRA_FIELDS
    assert SCORE_EVIDENCE_FIELDS is score_functionality.SCORE_EVIDENCE_FIELDS
    assert SOURCE_GIT_FIELDS is score_functionality.SOURCE_GIT_FIELDS
    assert INPUT_REPORT_FIELDS is score_functionality.INPUT_REPORT_FIELDS
    original_weight = SCORE_COMPONENT_WEIGHTS["browser_agent_e2e"]
    try:
        SCORE_COMPONENT_WEIGHTS["browser_agent_e2e"] = original_weight + 5
        shifted_fixture = json.loads(_score_output_fixture())
        assert shifted_fixture["max_total"] == sum(SCORE_COMPONENT_WEIGHTS.values())
        assert shifted_fixture["components"][2]["weight"] == SCORE_COMPONENT_WEIGHTS["browser_agent_e2e"]
    finally:
        SCORE_COMPONENT_WEIGHTS["browser_agent_e2e"] = original_weight
    assert json.loads(_success_output_for(score_command, _score_output_fixture()))["status"] == "needs_work"
    assert json.loads(_success_output_for(strict_score_command, _score_output_fixture(strict=True)))["strict"] is True
    strict_missing_e2e_env = json.loads(_score_output_fixture(strict=True, e2e_enabled=False))
    try:
        _success_output_for(strict_score_command, json.dumps(strict_missing_e2e_env))
    except ValueError as exc:
        assert "GAGENT_E2E_DEPS" in str(exc)
    else:
        raise AssertionError("strict score output without e2e opt-in env unexpectedly passed")
    strict_missing_openai_env = json.loads(_score_output_fixture(strict=True))
    strict_missing_openai_env["evidence"]["e2e_env"]["GAGENT_RUN_OPENAI_E2E"] = ""
    try:
        _success_output_for(strict_score_command, json.dumps(strict_missing_openai_env))
    except ValueError as exc:
        assert "GAGENT_RUN_OPENAI_E2E" in str(exc)
    else:
        raise AssertionError("strict score output without OpenAI e2e opt-in unexpectedly passed")
    strict_wrong_e2e_deps = json.loads(_score_output_fixture(strict=True))
    strict_wrong_e2e_deps["evidence"]["e2e_env"]["GAGENT_E2E_DEPS"] = "C:/tmp/e2e_deps"
    try:
        _success_output_for(strict_score_command, json.dumps(strict_wrong_e2e_deps))
    except ValueError as exc:
        assert "GAGENT_E2E_DEPS" in str(exc)
    else:
        raise AssertionError("strict score output with wrong e2e deps path unexpectedly passed")
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_deps = Path(tmp_dir)
        (tmp_deps / "agents").mkdir()
        (tmp_deps / "browser_use").mkdir()
        try:
            _validate_e2e_deps_dir(tmp_deps)
        except ValueError as exc:
            assert "playwright" in str(exc)
        else:
            raise AssertionError("e2e deps dir without playwright marker unexpectedly passed")
    strict_dirty = json.loads(_score_output_fixture(strict=True, dirty=True))
    try:
        _success_output_for(strict_score_command, json.dumps(strict_dirty))
    except ValueError as exc:
        assert "dirty" in str(exc)
    else:
        raise AssertionError("strict score output with dirty git unexpectedly passed")
    assert _success_output_for(smoke_command, "noisy child output") == ""
    try:
        _success_output_for(score_command, "log before json\n{\"status\":\"needs_work\"}")
    except ValueError as exc:
        assert "not valid JSON" in str(exc)
    else:
        raise AssertionError("noisy score output unexpectedly passed")
    missing_evidence = json.loads(_score_output_fixture())
    missing_evidence.pop("evidence")
    try:
        _success_output_for(score_command, json.dumps(missing_evidence))
    except ValueError as exc:
        assert "evidence is missing" in str(exc)
    else:
        raise AssertionError("score output without evidence unexpectedly passed")
    with tempfile.TemporaryDirectory() as tmp_dir:
        score_artifact = Path(tmp_dir) / "latest_functionality_score.json"
        expected_score = json.loads(_score_output_fixture())
        score_artifact.write_text(json.dumps(expected_score, indent=2, ensure_ascii=False), encoding="utf-8")
        _validate_score_artifact_matches_stdout(score_artifact, expected_score)
        mismatched_score = dict(expected_score)
        mismatched_score["total"] = 0
        score_artifact.write_text(json.dumps(mismatched_score, indent=2, ensure_ascii=False), encoding="utf-8")
        try:
            _validate_score_artifact_matches_stdout(score_artifact, expected_score)
        except ValueError as exc:
            assert "latest_functionality_score.json" in str(exc)
        else:
            raise AssertionError("mismatched latest_functionality_score.json unexpectedly passed")
    wrong_results_dir = json.loads(_score_output_fixture(results_dir="C:/tmp/gagent-results"))
    try:
        _success_output_for(score_command, json.dumps(wrong_results_dir))
    except ValueError as exc:
        assert "results_dir" in str(exc)
    else:
        raise AssertionError("score output with wrong results_dir unexpectedly passed")
    wrong_python_executable = json.loads(_score_output_fixture(python_executable="C:/Python/python.exe"))
    try:
        _success_output_for(score_command, json.dumps(wrong_python_executable))
    except ValueError as exc:
        assert "python_executable" in str(exc)
    else:
        raise AssertionError("score output with wrong python_executable unexpectedly passed")
    evidence_drift_cases = []
    extra_evidence_field = json.loads(_score_output_fixture())
    extra_evidence_field["evidence"]["mystery_field"] = True
    evidence_drift_cases.append((extra_evidence_field, "evidence unknown"))
    extra_e2e_env_field = json.loads(_score_output_fixture())
    extra_e2e_env_field["evidence"]["e2e_env"]["MYSTERY_ENV"] = "1"
    evidence_drift_cases.append((extra_e2e_env_field, "e2e_env unknown"))
    extra_source_git_field = json.loads(_score_output_fixture())
    extra_source_git_field["evidence"]["source_git"]["mystery_field"] = True
    evidence_drift_cases.append((extra_source_git_field, "source_git unknown"))
    extra_input_report = json.loads(_score_output_fixture())
    extra_input_report["evidence"]["input_reports"]["latest_mystery_report.json"] = {"exists": False}
    evidence_drift_cases.append((extra_input_report, "input_reports unknown"))
    extra_input_report_field = json.loads(_score_output_fixture())
    extra_input_report_field["evidence"]["input_reports"]["latest_eval_report.json"]["mystery_field"] = True
    evidence_drift_cases.append((extra_input_report_field, "input report field unknown"))
    missing_input_report = json.loads(_score_output_fixture())
    missing_input_report["evidence"]["input_reports"]["latest_eval_report.json"] = {"exists": False}
    for fixture, label in evidence_drift_cases:
        try:
            _success_output_for(score_command, json.dumps(fixture))
        except ValueError as exc:
            assert "evidence" in str(exc) and "unknown" in str(exc)
        else:
            raise AssertionError(f"score output with {label} unexpectedly passed")
    try:
        _success_output_for(score_command, json.dumps(missing_input_report))
    except ValueError as exc:
        assert "input_reports.latest_eval_report.json" in str(exc)
    else:
        raise AssertionError("score output with missing input report unexpectedly passed")
    wrong_input_report_bytes = json.loads(_score_output_fixture())
    wrong_input_report_bytes["evidence"]["input_reports"]["latest_eval_report.json"]["bytes"] += 1
    try:
        _success_output_for(score_command, json.dumps(wrong_input_report_bytes))
    except ValueError as exc:
        assert "bytes" in str(exc)
    else:
        raise AssertionError("score output with mismatched input report bytes unexpectedly passed")
    wrong_input_report_mtime = json.loads(_score_output_fixture())
    current_mtime = _parse_utc_timestamp(
        wrong_input_report_mtime["evidence"]["input_reports"]["latest_eval_report.json"]["modified_at_utc"],
        "fixture modified_at_utc",
    )
    wrong_input_report_mtime["evidence"]["input_reports"]["latest_eval_report.json"]["modified_at_utc"] = _format_utc(
        current_mtime + timedelta(seconds=10)
    )
    try:
        _success_output_for(score_command, json.dumps(wrong_input_report_mtime))
    except ValueError as exc:
        assert "modified_at_utc" in str(exc)
    else:
        raise AssertionError("score output with mismatched input report mtime unexpectedly passed")
    stale_input_report = json.loads(_score_output_fixture())
    stale_input_report["evidence"]["input_reports"]["latest_eval_report.json"]["modified_at_utc"] = "2025-12-31T23:00:00Z"
    try:
        _success_output_for(score_command, json.dumps(stale_input_report))
    except ValueError as exc:
        assert "stale" in str(exc)
    else:
        raise AssertionError("score output with stale input report unexpectedly passed")
    future_input_report = json.loads(_score_output_fixture())
    generated_at = _parse_utc_timestamp(future_input_report["evidence"]["generated_at_utc"], "fixture generated_at")
    future_input_report["evidence"]["input_reports"]["latest_eval_report.json"]["modified_at_utc"] = _format_utc(
        generated_at + timedelta(minutes=3)
    )
    try:
        _success_output_for(score_command, json.dumps(future_input_report))
    except ValueError as exc:
        assert "future" in str(exc)
    else:
        raise AssertionError("score output with future-dated input report unexpectedly passed")
    wrong_head = json.loads(_score_output_fixture(source_head="0000000"))
    try:
        _success_output_for(score_command, json.dumps(wrong_head))
    except ValueError as exc:
        assert "head" in str(exc)
    else:
        raise AssertionError("score output with mismatched source_git head unexpectedly passed")
    wrong_branch = json.loads(_score_output_fixture(source_branch="wrong-branch"))
    try:
        _success_output_for(score_command, json.dumps(wrong_branch))
    except ValueError as exc:
        assert "branch" in str(exc)
    else:
        raise AssertionError("score output with mismatched source_git branch unexpectedly passed")
    bad_weight = json.loads(_score_output_fixture())
    bad_weight["components"][0]["weight"] = 99
    try:
        _success_output_for(score_command, json.dumps(bad_weight))
    except ValueError as exc:
        assert "component" in str(exc)
    else:
        raise AssertionError("score output with wrong component weight unexpectedly passed")
    bad_name = json.loads(_score_output_fixture())
    bad_name["components"][0]["name"] = "surprise_score"
    try:
        _success_output_for(score_command, json.dumps(bad_name))
    except ValueError as exc:
        assert "component name" in str(exc)
    else:
        raise AssertionError("score output with wrong component name unexpectedly passed")
    bad_total = json.loads(_score_output_fixture())
    bad_total["total"] = 100
    try:
        _success_output_for(score_command, json.dumps(bad_total))
    except ValueError as exc:
        assert "total" in str(exc)
    else:
        raise AssertionError("score output with wrong total unexpectedly passed")
    bad_max_total = json.loads(_score_output_fixture())
    bad_max_total["max_total"] = 99
    try:
        _success_output_for(score_command, json.dumps(bad_max_total))
    except ValueError as exc:
        assert "max_total" in str(exc)
    else:
        raise AssertionError("score output with wrong max_total unexpectedly passed")
    bad_status = json.loads(_score_output_fixture())
    bad_status["status"] = "ok"
    try:
        _success_output_for(score_command, json.dumps(bad_status))
    except ValueError as exc:
        assert "status" in str(exc)
    else:
        raise AssertionError("score output with wrong status unexpectedly passed")
    bad_component_score = json.loads(_score_output_fixture())
    bad_component_score["components"][1]["score"] = 99
    try:
        _success_output_for(score_command, json.dumps(bad_component_score))
    except ValueError as exc:
        assert "component" in str(exc)
    else:
        raise AssertionError("score output with invalid component score unexpectedly passed")
    bad_component_status = json.loads(_score_output_fixture())
    bad_component_status["components"][1]["status"] = 123
    try:
        _success_output_for(score_command, json.dumps(bad_component_status))
    except ValueError as exc:
        assert "component" in str(exc)
    else:
        raise AssertionError("score output with invalid component status unexpectedly passed")
    extra_component_field = json.loads(_score_output_fixture())
    extra_component_field["components"][0]["mystery_field"] = True
    try:
        _success_output_for(score_command, json.dumps(extra_component_field))
    except ValueError as exc:
        assert "component" in str(exc) and "unknown" in str(exc)
    else:
        raise AssertionError("score output with unknown component field unexpectedly passed")
    bad_refreshed = json.loads(_score_output_fixture())
    bad_refreshed["refreshed"] = False
    try:
        _success_output_for(score_command, json.dumps(bad_refreshed))
    except ValueError as exc:
        assert "refreshed" in str(exc)
    else:
        raise AssertionError("score output with wrong refreshed flag unexpectedly passed")
    bad_strict = json.loads(_score_output_fixture())
    bad_strict["strict"] = True
    try:
        _success_output_for(score_command, json.dumps(bad_strict))
    except ValueError as exc:
        assert "strict" in str(exc)
    else:
        raise AssertionError("score output with wrong strict flag unexpectedly passed")
    missing_strict = json.loads(_score_output_fixture())
    try:
        _success_output_for(strict_score_command, json.dumps(missing_strict))
    except ValueError as exc:
        assert "strict" in str(exc)
    else:
        raise AssertionError("strict score output without strict flag unexpectedly passed")
    bad_blockers = json.loads(_score_output_fixture())
    bad_blockers["blockers"] = ["hidden blocker"]
    try:
        _success_output_for(score_command, json.dumps(bad_blockers))
    except ValueError as exc:
        assert "blockers" in str(exc)
    else:
        raise AssertionError("score output with wrong blockers unexpectedly passed")


def _score_output_fixture(
    *,
    strict: bool = False,
    dirty: bool = False,
    e2e_enabled: bool = True,
    source_head: str | None = None,
    source_branch: str | None = None,
    results_dir: str | None = None,
    python_executable: str | None = None,
) -> str:
    internal_score = SCORE_COMPONENT_WEIGHTS["internal_eval"]
    expected_results_dir = ROOT / "backend" / "eval_registry" / "results"
    input_report_evidence = _input_report_fixture_evidence(expected_results_dir)
    generated_at_utc = _fixture_generated_at_utc(input_report_evidence)
    components = [
        {
            "name": "internal_eval",
            "weight": SCORE_COMPONENT_WEIGHTS["internal_eval"],
            "score": internal_score,
            "status": "passed",
            "blockers": [],
        },
        {
            "name": "openai_orchestrated_e2e",
            "weight": SCORE_COMPONENT_WEIGHTS["openai_orchestrated_e2e"],
            "score": 0,
            "status": "skipped",
            "blockers": [],
        },
        {
            "name": "browser_agent_e2e",
            "weight": SCORE_COMPONENT_WEIGHTS["browser_agent_e2e"],
            "score": 0,
            "status": "skipped",
            "blockers": [],
        },
    ]
    return json.dumps(
        {
            "status": "needs_work",
            "total": internal_score,
            "max_total": sum(SCORE_COMPONENT_WEIGHTS.values()),
            "blockers": [],
            "refreshed": True,
            "strict": strict,
            "components": components,
            "evidence": {
                "generated_at_utc": generated_at_utc,
                "results_dir": results_dir if results_dir is not None else str(expected_results_dir.resolve()),
                "python_executable": python_executable if python_executable is not None else str(PYTHON.resolve()),
                "e2e_env": {
                    "GAGENT_E2E_DEPS": "backend/temp/e2e_deps" if e2e_enabled else "",
                    "GAGENT_RUN_OPENAI_E2E": "1" if e2e_enabled else "",
                    "GAGENT_RUN_BROWSER_AGENT_E2E": "1" if e2e_enabled else "",
                },
                "source_git": {
                    "available": True,
                    "head": source_head if source_head is not None else (_current_git_head() or "abcdef1234567890"),
                    "branch": source_branch if source_branch is not None else (_current_git_branch() or "main"),
                    "dirty": dirty,
                },
                "input_reports": input_report_evidence,
            },
        }
    )


def _input_report_fixture_evidence(results_dir: Path) -> dict[str, dict[str, object]]:
    evidence: dict[str, dict[str, object]] = {}
    for name in SCORE_INPUT_REPORTS:
        path = results_dir / name
        try:
            stat = path.stat()
        except OSError:
            evidence[name] = {
                "exists": True,
                "bytes": 1,
                "modified_at_utc": "2026-01-01T00:00:00Z",
            }
            continue
        evidence[name] = {
            "exists": True,
            "bytes": stat.st_size,
            "modified_at_utc": _format_utc(datetime.fromtimestamp(stat.st_mtime, timezone.utc)),
        }
    return evidence


def _fixture_generated_at_utc(input_reports: dict[str, dict[str, object]]) -> str:
    modified_times: list[datetime] = []
    for report in input_reports.values():
        modified_at = report.get("modified_at_utc")
        if isinstance(modified_at, str):
            modified_times.append(_parse_utc_timestamp(modified_at, "fixture modified_at_utc"))
    if not modified_times:
        return "2026-01-01T00:00:01Z"
    return _format_utc(max(modified_times) + timedelta(seconds=1))


if __name__ == "__main__":
    raise SystemExit(main())
