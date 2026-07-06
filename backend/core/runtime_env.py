from __future__ import annotations

import json
import os
import subprocess
import sys
from typing import Sequence


def _candidate_conda_commands() -> list[str]:
    candidates: list[str] = []
    for env_name in ("CONDA_EXE",):
        value = os.environ.get(env_name)
        if value:
            candidates.append(value)
    candidates.extend(
        [
            "conda",
            r"E:\Anaconda3\condabin\conda.bat",
            r"E:\Anaconda3\Scripts\conda.exe",
            r"E:\Anaconda3\Library\bin\conda.bat",
        ]
    )
    return list(dict.fromkeys(candidates))


def _run_conda_json(args: Sequence[str]) -> dict | None:
    for conda_cmd in _candidate_conda_commands():
        try:
            output = subprocess.check_output(
                [conda_cmd, *args, "--json"],
                stderr=subprocess.STDOUT,
                text=True,
                shell=False,
            )
            return json.loads(output)
        except Exception:
            continue
    return None


def find_conda_env_python(env_name: str = "rag-env") -> str | None:
    current_prefix = os.environ.get("CONDA_PREFIX", "")
    if current_prefix and os.path.basename(current_prefix).lower() == env_name.lower():
        if os.path.isfile(sys.executable):
            return sys.executable

    info = _run_conda_json(["env", "list"])
    if isinstance(info, dict):
        for prefix in info.get("envs", []):
            if os.path.basename(prefix).lower() != env_name.lower():
                continue
            python_path = os.path.join(prefix, "python.exe" if os.name == "nt" else "bin/python")
            if os.path.isfile(python_path):
                return python_path

    guessed_prefixes = [
        os.path.join(r"E:\Anaconda3\envs", env_name),
        os.path.join(r"D:\anaconda0\envs", env_name),
    ]
    for prefix in guessed_prefixes:
        python_path = os.path.join(prefix, "python.exe" if os.name == "nt" else "bin/python")
        if os.path.isfile(python_path):
            return python_path
    return None


def preferred_python(env_name: str = "rag-env") -> str:
    return find_conda_env_python(env_name) or sys.executable
