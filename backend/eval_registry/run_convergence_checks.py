#!/usr/bin/env python
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PYTHON = ROOT / "python-runtime" / ("python.exe" if os.name == "nt" else "bin/python")


def main() -> int:
    commands = [
        [str(PYTHON), "backend/tool_registry/validate_tool_registry.py"],
        [str(PYTHON), "backend/quality_registry/validate_quality_registry.py"],
        [str(PYTHON), "backend/tool_registry/tests/smoke_web_tools.py"],
        [str(PYTHON), "backend/eval_registry/validate_eval_registry.py"],
        [str(PYTHON), "backend/eval_registry/tests/smoke_eval_registry.py"],
        [str(PYTHON), "backend/eval_registry/score_functionality.py", "--refresh"],
        [str(PYTHON), "backend/runtime_ledger/validate_runtime_ledger.py"],
        [str(PYTHON), "backend/runtime_ledger/tests/smoke_runtime_ledger.py"],
    ]
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
    print("[run_convergence_checks] ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
