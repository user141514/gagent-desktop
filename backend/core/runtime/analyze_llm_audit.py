"""Analyze local LLM audit records."""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


DEFAULT_RECORDS_PATH = Path("F:/GAgent-Multi/temp/llm_cache/records.jsonl")


def _load_records(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    records: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(item, dict):
            records.append(item)
    return records


def _metadata(record: dict[str, Any]) -> dict[str, Any]:
    data = record.get("metadata")
    return data if isinstance(data, dict) else {}


def _float_field(record: dict[str, Any], key: str) -> float:
    try:
        return float(record.get(key) or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _int_field(record: dict[str, Any], key: str) -> int:
    try:
        return int(record.get(key) or 0)
    except (TypeError, ValueError):
        return 0


def _top_rows(records: list[dict[str, Any]], key: str, limit: int) -> list[dict[str, Any]]:
    return sorted(records, key=lambda row: _float_field(row, key), reverse=True)[:limit]


def _row_summary(record: dict[str, Any], field: str) -> dict[str, Any]:
    md = _metadata(record)
    return {
        "value": record.get(field),
        "duration_ms": record.get("duration_ms"),
        "prompt_hash": record.get("prompt_hash"),
        "model": record.get("model"),
        "run_id": md.get("run_id"),
        "agent_name": md.get("agent_name"),
        "turn": md.get("turn"),
        "call_site": md.get("call_site"),
        "cache_type": md.get("cache_type"),
        "prompt_preview": str(record.get("prompt_preview") or "")[:180],
    }


def analyze(records: list[dict[str, Any]], limit: int = 10) -> dict[str, Any]:
    by_run_id: dict[str, dict[str, Any]] = defaultdict(lambda: {"count": 0, "duration_ms": 0.0, "estimated_prompt_tokens": 0.0})
    by_agent = Counter()
    by_call_site = Counter()
    duplicate_hashes = Counter()

    for record in records:
        md = _metadata(record)
        run_id = str(md.get("run_id") or "unknown")
        agent_name = str(md.get("agent_name") or "unknown")
        call_site = str(md.get("call_site") or "unknown")
        by_run_id[run_id]["count"] += 1
        by_run_id[run_id]["duration_ms"] += _float_field(record, "duration_ms")
        by_run_id[run_id]["estimated_prompt_tokens"] += _float_field(record, "estimated_prompt_tokens")
        by_agent[agent_name] += 1
        by_call_site[call_site] += 1
        duplicate_hashes[str(record.get("prompt_hash") or "")] += 1

    duplicates = {key: count for key, count in duplicate_hashes.items() if key and count > 1}
    run_rows = {
        run_id: {
            "count": bucket["count"],
            "duration_ms": round(bucket["duration_ms"], 3),
            "estimated_prompt_tokens": round(bucket["estimated_prompt_tokens"], 3),
        }
        for run_id, bucket in sorted(by_run_id.items(), key=lambda item: item[0])
    }

    return {
        "total_calls": len(records),
        "by_run_id": run_rows,
        "by_agent_name": dict(by_agent.most_common()),
        "by_call_site": dict(by_call_site.most_common()),
        "slowest_10": [_row_summary(row, "duration_ms") for row in _top_rows(records, "duration_ms", limit)],
        "prompt_chars_top_10": [_row_summary(row, "prompt_chars") for row in _top_rows(records, "prompt_chars", limit)],
        "estimated_prompt_tokens_top_10": [_row_summary(row, "estimated_prompt_tokens") for row in _top_rows(records, "estimated_prompt_tokens", limit)],
        "history_chars_top_10": [_row_summary(row, "history_chars") for row in _top_rows(records, "history_chars", limit)],
        "memory_chars_top_10": [_row_summary(row, "memory_chars") for row in _top_rows(records, "memory_chars", limit)],
        "duplicate_prompt_hashes": duplicates,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--path", default=str(DEFAULT_RECORDS_PATH))
    parser.add_argument("--run-id")
    parser.add_argument("--limit", type=int, default=10)
    args = parser.parse_args()

    path = Path(args.path)
    records = _load_records(path)
    if args.run_id:
        records = [row for row in records if str(_metadata(row).get("run_id") or "") == args.run_id]

    report = analyze(records, limit=max(1, args.limit))
    print(json.dumps({"path": str(path), "run_id_filter": args.run_id or "", **report}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
