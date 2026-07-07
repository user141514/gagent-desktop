#!/usr/bin/env python
from __future__ import annotations

import argparse
import os
import json
import subprocess
import sys
from pathlib import Path


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
    _validate_score_evidence(score)
    return json.dumps(score, indent=2, ensure_ascii=False)


def _is_score_command(command: list[str]) -> bool:
    return len(command) > 1 and command[1].replace("\\", "/").endswith(
        "backend/eval_registry/score_functionality.py"
    )


def _validate_score_evidence(score: dict) -> None:
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
    smoke_command = [str(PYTHON), "backend/eval_registry/tests/smoke_eval_registry.py"]
    assert _is_score_command(score_command)
    assert not _is_score_command(smoke_command)
    assert _commands(full=False)[5] == score_command
    assert _commands(full=True)[5] == [*score_command, "--strict"]
    assert json.loads(_success_output_for(score_command, _score_output_fixture()))["status"] == "needs_work"
    assert _success_output_for(smoke_command, "noisy child output") == ""
    try:
        _success_output_for(score_command, "log before json\n{\"status\":\"needs_work\"}")
    except ValueError as exc:
        assert "not valid JSON" in str(exc)
    else:
        raise AssertionError("noisy score output unexpectedly passed")
    try:
        _success_output_for(score_command, "{\"status\":\"needs_work\"}")
    except ValueError as exc:
        assert "evidence is missing" in str(exc)
    else:
        raise AssertionError("score output without evidence unexpectedly passed")


def _score_output_fixture() -> str:
    return json.dumps(
        {
            "status": "needs_work",
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
                    "dirty": False,
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
