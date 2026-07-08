from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


REQUIRED_FIELDS = (
    "id",
    "version",
    "type",
    "task",
    "owner_layer",
    "target_tool",
    "input",
    "expected_tools",
    "expected_ledger",
    "expected_result",
    "score",
)


@dataclass(frozen=True)
class EvalCase:
    id: str
    version: int
    type: str
    task: str
    owner_layer: str
    target_tool: str
    input: dict[str, Any]
    expected_tools: dict[str, Any]
    expected_ledger: dict[str, Any]
    expected_result: dict[str, Any]
    score: dict[str, int]
    source_path: str


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def default_cases_dir(project_root: str | Path | None = None) -> Path:
    root = Path(project_root).resolve() if project_root is not None else _project_root()
    return root / "backend" / "eval_registry" / "cases"


def load_eval_case(path: str | Path) -> EvalCase:
    case_path = Path(path)
    try:
        payload = json.loads(case_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON in {case_path}: {exc}") from exc
    except OSError as exc:
        raise ValueError(f"cannot read eval case {case_path}: {exc}") from exc

    if not isinstance(payload, dict):
        raise ValueError(f"{case_path}: eval case must be a JSON object")

    missing = [field for field in REQUIRED_FIELDS if field not in payload]
    if missing:
        raise ValueError(f"{case_path}: missing required fields: {', '.join(missing)}")
    extra = sorted(set(str(field) for field in payload) - set(REQUIRED_FIELDS))
    if extra:
        raise ValueError(f"{case_path}: unknown fields: {', '.join(extra)}")

    for field_name in ("id", "type", "task", "owner_layer", "target_tool"):
        value = payload[field_name]
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{case_path}: {field_name} must be a non-empty string")
    if isinstance(payload["version"], bool) or not isinstance(payload["version"], int):
        raise ValueError(f"{case_path}: version must be an integer")

    case_id = payload["id"].strip()
    if case_id != case_path.stem:
        raise ValueError(f"{case_path}: case id must match filename stem {case_path.stem}")

    for dict_field in ("input", "expected_tools", "expected_ledger", "expected_result", "score"):
        if not isinstance(payload.get(dict_field), dict):
            raise ValueError(f"{case_path}: {dict_field} must be an object")

    score_payload = dict(payload["score"])
    for field_name in ("answer_or_tool_behavior", "ledger"):
        value = score_payload.get(field_name)
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError(f"{case_path}: score.{field_name} must be an integer")

    return EvalCase(
        id=case_id,
        version=payload["version"],
        type=payload["type"],
        task=payload["task"],
        owner_layer=payload["owner_layer"],
        target_tool=payload["target_tool"],
        input=dict(payload["input"]),
        expected_tools=dict(payload["expected_tools"]),
        expected_ledger=dict(payload["expected_ledger"]),
        expected_result=dict(payload["expected_result"]),
        score={str(k): int(v) for k, v in score_payload.items()},
        source_path=str(case_path),
    )


def load_eval_cases(cases_dir: str | Path | None = None) -> list[EvalCase]:
    root = Path(cases_dir) if cases_dir is not None else default_cases_dir()
    if not root.exists():
        raise ValueError(f"eval cases directory does not exist: {root}")
    cases = [load_eval_case(path) for path in sorted(root.glob("*.json"))]
    return cases


def case_to_dict(case: EvalCase) -> dict[str, Any]:
    return asdict(case)
