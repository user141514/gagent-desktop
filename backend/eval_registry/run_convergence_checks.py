#!/usr/bin/env python
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

EVAL_REGISTRY_DIR = Path(__file__).resolve().parent
if str(EVAL_REGISTRY_DIR) not in sys.path:
    sys.path.insert(0, str(EVAL_REGISTRY_DIR))
import score_functionality


ROOT = Path(__file__).resolve().parents[2]
PYTHON = ROOT / "python-runtime" / ("python.exe" if os.name == "nt" else "bin/python")
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
SCORE_COMPONENT_WEIGHTS = score_functionality.SCORE_COMPONENT_WEIGHTS


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
            success_output = _success_output_for(command, result.stdout)
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


def _success_output_for(command: list[str], stdout: str) -> str:
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
    for key in ["generated_at_utc", "results_dir", "python_executable"]:
        if not isinstance(evidence.get(key), str) or not evidence[key]:
            raise ValueError(f"score_functionality evidence.{key} is missing")
    if not evidence["generated_at_utc"].endswith("Z"):
        raise ValueError("score_functionality evidence.generated_at_utc must be UTC")

    e2e_env = evidence.get("e2e_env")
    if not isinstance(e2e_env, dict):
        raise ValueError("score_functionality evidence.e2e_env is missing")
    for key in SCORE_E2E_ENV_KEYS:
        if not isinstance(e2e_env.get(key), str):
            raise ValueError(f"score_functionality evidence.e2e_env.{key} is missing")

    source_git = evidence.get("source_git")
    if not isinstance(source_git, dict):
        raise ValueError("score_functionality evidence.source_git is missing")
    if source_git.get("available") is not True:
        raise ValueError("score_functionality evidence.source_git is unavailable")
    if not isinstance(source_git.get("head"), str) or len(source_git["head"]) < 7:
        raise ValueError("score_functionality evidence.source_git.head is missing")
    if not isinstance(source_git.get("branch"), str):
        raise ValueError("score_functionality evidence.source_git.branch is missing")
    if not isinstance(source_git.get("dirty"), bool):
        raise ValueError("score_functionality evidence.source_git.dirty is missing")
    if "--strict" in command and source_git["dirty"]:
        raise ValueError("score_functionality evidence.source_git.dirty must be false for strict convergence")

    input_reports = evidence.get("input_reports")
    if not isinstance(input_reports, dict):
        raise ValueError("score_functionality evidence.input_reports is missing")
    for name in SCORE_INPUT_REPORTS:
        report = input_reports.get(name)
        if not isinstance(report, dict):
            raise ValueError(f"score_functionality evidence.input_reports.{name} is missing")
        if not isinstance(report.get("exists"), bool):
            raise ValueError(f"score_functionality evidence.input_reports.{name}.exists is missing")
        if report["exists"]:
            if not isinstance(report.get("bytes"), int) or report["bytes"] < 0:
                raise ValueError(f"score_functionality evidence.input_reports.{name}.bytes is invalid")
            modified_at_utc = report.get("modified_at_utc")
            if not isinstance(modified_at_utc, str) or not modified_at_utc.endswith("Z"):
                raise ValueError(f"score_functionality evidence.input_reports.{name}.modified_at_utc is invalid")


def _self_test() -> None:
    score_command = [str(PYTHON), "backend/eval_registry/score_functionality.py", "--refresh"]
    strict_score_command = [*score_command, "--strict"]
    smoke_command = [str(PYTHON), "backend/eval_registry/tests/smoke_eval_registry.py"]
    assert _is_score_command(score_command)
    assert not _is_score_command(smoke_command)
    assert _commands(full=False)[5] == score_command
    assert _commands(full=True)[5] == strict_score_command
    assert SCORE_COMPONENT_WEIGHTS is score_functionality.SCORE_COMPONENT_WEIGHTS
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


def _score_output_fixture(*, strict: bool = False, dirty: bool = False) -> str:
    internal_score = SCORE_COMPONENT_WEIGHTS["internal_eval"]
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
                "generated_at_utc": "2026-01-01T00:00:00Z",
                "results_dir": "backend/eval_registry/results",
                "python_executable": "python-runtime/python.exe",
                "e2e_env": {
                    "GAGENT_E2E_DEPS": "",
                    "GAGENT_RUN_OPENAI_E2E": "",
                    "GAGENT_RUN_BROWSER_AGENT_E2E": "",
                },
                "source_git": {
                    "available": True,
                    "head": "abcdef1234567890",
                    "branch": "main",
                    "dirty": dirty,
                },
                "input_reports": {
                    name: {
                        "exists": True,
                        "bytes": 1,
                        "modified_at_utc": "2026-01-01T00:00:00Z",
                    }
                    for name in SCORE_INPUT_REPORTS
                },
            },
        }
    )


if __name__ == "__main__":
    raise SystemExit(main())
