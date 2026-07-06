"""Offline analyzer for read_prefetch effectiveness."""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from statistics import mean
from typing import Any


@dataclass
class RunAnalysis:
    run_id: str
    read_prefetch_should_prefetch: bool
    read_prefetch_target_file: str | None
    read_prefetch_reason: str
    read_prefetch_confidence: float
    selected_agent: str | None
    total_duration_ms: float | None
    llm_call_count: int
    classic_executor_call_count: int
    tool_calls: list[str]
    same_file_read: bool
    file_read_turn: int | None
    read_prefetch_potentially_useful: bool
    estimated_saved_turns: int
    analysis_reason: str


def _safe_read_json(path: Path) -> dict[str, Any] | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _safe_read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except Exception:
            continue
    return rows


def _normalize_text(value: Any) -> str:
    return str(value or "").replace("\\/", "/").replace("\\\\", "/")


def _normalize_path(value: Any) -> str:
    raw = str(value or "").strip().replace("\\", "/")
    if not raw:
        return ""
    return raw.lower()


def _collect_profiles(profiles_dir: Path, run_id: str | None = None) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    if not profiles_dir.exists():
        return grouped
    pattern = f"profile_{run_id}_*.json" if run_id else "profile_*.json"
    for path in sorted(profiles_dir.glob(pattern)):
        obj = _safe_read_json(path)
        if not obj:
            continue
        run = obj.get("run") or {}
        rid = str(run.get("run_id") or "").strip()
        if not rid:
            continue
        grouped[rid].append({"path": path, "data": obj})
    return grouped


def _collect_audit_rows(audit_file: Path, run_id: str | None = None) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for obj in _safe_read_jsonl(audit_file):
        md = obj.get("metadata") or {}
        rid = str(md.get("run_id") or "").strip()
        if not rid:
            continue
        if run_id and rid != run_id:
            continue
        grouped[rid].append(obj)
    return grouped


def _first_non_null(values: list[Any]) -> Any:
    for value in values:
        if value is not None:
            return value
    return None


def _route_selected_metadata(profile_entries: list[dict[str, Any]]) -> dict[str, Any]:
    for entry in profile_entries:
        for event in entry["data"].get("events") or []:
            if event.get("name") == "route_selected":
                return event.get("metadata") or {}
    return {}


def _prefetch_event_metadata(profile_entries: list[dict[str, Any]]) -> dict[str, Any]:
    for entry in profile_entries:
        for event in entry["data"].get("events") or []:
            if event.get("name") == "read_prefetch_detected":
                return event.get("metadata") or {}
    return {}


def _tool_spans(profile_entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    spans: list[dict[str, Any]] = []
    for entry in profile_entries:
        for span in entry["data"].get("spans") or []:
            name = str(span.get("name") or "")
            if name.startswith("tool_call:"):
                spans.append(span)
    return spans


def _tool_result_events(profile_entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for entry in profile_entries:
        for event in entry["data"].get("events") or []:
            if event.get("name") == "tool_call_result":
                events.append(event)
    return events


def _total_duration_ms(profile_entries: list[dict[str, Any]]) -> float | None:
    durations: list[float] = []
    for entry in profile_entries:
        summary = entry["data"].get("summary") or {}
        value = summary.get("total_duration_ms")
        if isinstance(value, (int, float)):
            durations.append(float(value))
    return max(durations) if durations else None


def _audit_prefetch_metadata(audit_rows: list[dict[str, Any]]) -> dict[str, Any]:
    for row in audit_rows:
        md = row.get("metadata") or {}
        if "read_prefetch_should_prefetch" in md:
            return md
    return {}


def _llm_call_count(audit_rows: list[dict[str, Any]]) -> int:
    return len(audit_rows)


def _classic_executor_call_count(audit_rows: list[dict[str, Any]]) -> int:
    return sum(1 for row in audit_rows if (row.get("metadata") or {}).get("agent_name") == "classic_executor")


def _infer_same_file_read(
    target_file: str | None,
    tool_spans: list[dict[str, Any]],
    tool_result_events: list[dict[str, Any]],
    audit_rows: list[dict[str, Any]],
) -> tuple[bool, int | None, str]:
    file_read_spans = [span for span in tool_spans if str(span.get("name") or "") == "tool_call:file_read"]
    if not file_read_spans:
        return False, None, "no_file_read_tool_after_prefetch"
    if not target_file:
        turn = _first_non_null([((span.get("metadata") or {}).get("turn")) for span in file_read_spans])
        return False, int(turn) if isinstance(turn, int) else None, "insufficient_tool_metadata"

    target_norm = _normalize_path(target_file)
    target_name = Path(target_norm).name.lower()
    exact_turns: list[int] = []

    def _matches_tool_target(value: Any) -> bool:
        candidate = _normalize_path(value)
        if not candidate:
            return False
        if candidate == target_norm:
            return True
        if candidate.endswith("/" + target_norm):
            return True
        return False

    for span in file_read_spans:
        metadata = span.get("metadata") or {}
        if _matches_tool_target(metadata.get("tool_target_path")):
            turn = metadata.get("turn")
            if isinstance(turn, int):
                exact_turns.append(turn)
    for event in tool_result_events:
        metadata = event.get("metadata") or {}
        if str(metadata.get("tool") or "") != "file_read":
            continue
        if _matches_tool_target(metadata.get("tool_target_path")):
            turn = metadata.get("turn")
            if isinstance(turn, int):
                exact_turns.append(turn)

    if exact_turns:
        return True, min(exact_turns), "exact_tool_target_match"

    turn = _first_non_null([((span.get("metadata") or {}).get("turn")) for span in file_read_spans])
    file_read_turn = int(turn) if isinstance(turn, int) else None

    classic_rows = [row for row in audit_rows if (row.get("metadata") or {}).get("agent_name") == "classic_executor"]
    text_parts: list[str] = []
    for row in classic_rows or audit_rows:
        prompt_preview = _normalize_text(row.get("prompt_preview"))
        response_preview = _normalize_text(row.get("response_preview"))
        text_parts.append(prompt_preview)
        text_parts.append(response_preview)
    combined = "\n".join(text_parts).lower()

    read_markers = ("file_read", "读取", "read ")
    mentions_target = target_norm in combined or target_name in combined
    mentions_read = any(marker in combined for marker in read_markers)
    if mentions_target and mentions_read:
        return True, file_read_turn, "fallback_preview_mentions_target"
    return False, file_read_turn, "insufficient_tool_metadata"


def _analyze_run(run_id: str, profile_entries: list[dict[str, Any]], audit_rows: list[dict[str, Any]]) -> RunAnalysis:
    route_meta = _route_selected_metadata(profile_entries)
    prefetch_event = _prefetch_event_metadata(profile_entries)
    audit_prefetch = _audit_prefetch_metadata(audit_rows)
    prefetch_meta = prefetch_event or audit_prefetch

    should_prefetch = bool(prefetch_meta.get("should_prefetch", audit_prefetch.get("read_prefetch_should_prefetch", False)))
    target_file = (
        prefetch_meta.get("target_file")
        or audit_prefetch.get("read_prefetch_target_file")
    )
    reason = str(
        prefetch_meta.get("reason")
        or audit_prefetch.get("read_prefetch_reason")
        or "no_read_prefetch_metadata"
    )
    confidence = float(
        prefetch_meta.get("confidence")
        or audit_prefetch.get("read_prefetch_confidence")
        or 0.0
    )
    tool_spans = _tool_spans(profile_entries)
    tool_result_events = _tool_result_events(profile_entries)
    tool_calls = [str((span.get("metadata") or {}).get("tool") or span.get("name") or "") for span in tool_spans]
    same_file_read, file_read_turn, inference_reason = _infer_same_file_read(
        target_file,
        tool_spans,
        tool_result_events,
        audit_rows,
    )
    potentially_useful = bool(should_prefetch and same_file_read)
    if not potentially_useful:
        estimated_saved_turns = 0
    elif file_read_turn is not None and file_read_turn >= 2:
        estimated_saved_turns = 1
    else:
        estimated_saved_turns = 0

    return RunAnalysis(
        run_id=run_id,
        read_prefetch_should_prefetch=should_prefetch,
        read_prefetch_target_file=str(target_file) if target_file else None,
        read_prefetch_reason=reason,
        read_prefetch_confidence=confidence,
        selected_agent=str(route_meta.get("selected_agent") or "") or None,
        total_duration_ms=_total_duration_ms(profile_entries),
        llm_call_count=_llm_call_count(audit_rows),
        classic_executor_call_count=_classic_executor_call_count(audit_rows),
        tool_calls=tool_calls,
        same_file_read=same_file_read,
        file_read_turn=file_read_turn,
        read_prefetch_potentially_useful=potentially_useful,
        estimated_saved_turns=estimated_saved_turns,
        analysis_reason=inference_reason,
    )


def _format_ms(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value:.3f}"


def _print_summary(analyses: list[RunAnalysis], limit: int) -> None:
    if not analyses:
        print("No read_prefetch records found.")
        return

    detected_runs = sum(1 for item in analyses if item.read_prefetch_reason != "no_read_prefetch_metadata")
    true_runs = sum(1 for item in analyses if item.read_prefetch_should_prefetch)
    same_file_read_runs = sum(1 for item in analyses if item.same_file_read)
    potentially_useful_runs = sum(1 for item in analyses if item.read_prefetch_potentially_useful)
    avg_duration = mean([item.total_duration_ms for item in analyses if item.total_duration_ms is not None]) if any(
        item.total_duration_ms is not None for item in analyses
    ) else None

    print(f"total_runs: {len(analyses)}")
    print(f"prefetch_detected_runs: {detected_runs}")
    print(f"prefetch_true_runs: {true_runs}")
    print(f"same_file_read_runs: {same_file_read_runs}")
    print(f"potentially_useful_runs: {potentially_useful_runs}")
    print(f"avg_total_duration_ms: {_format_ms(avg_duration)}")
    print("top_candidates:")

    candidates = [
        item for item in analyses
        if item.read_prefetch_should_prefetch
    ]
    candidates.sort(
        key=lambda item: (
            0 if item.read_prefetch_potentially_useful else 1,
            -(item.estimated_saved_turns or 0),
            -(item.total_duration_ms or 0.0),
        )
    )
    for item in candidates[: max(1, limit)]:
        print(
            json.dumps(
                {
                    "run_id": item.run_id,
                    "target_file": item.read_prefetch_target_file,
                    "same_file_read": item.same_file_read,
                    "classic_turn": item.file_read_turn,
                    "estimated_saved_turns": item.estimated_saved_turns,
                    "total_duration_ms": item.total_duration_ms,
                    "analysis_reason": item.analysis_reason,
                },
                ensure_ascii=False,
            )
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="Analyze offline read_prefetch effectiveness from profiles and audit logs.")
    parser.add_argument("--profiles-dir", default="temp/profiles")
    parser.add_argument("--audit-file", default="temp/llm_cache/records.jsonl")
    parser.add_argument("--run-id")
    parser.add_argument("--limit", type=int, default=20)
    args = parser.parse_args()

    profiles_dir = Path(args.profiles_dir)
    audit_file = Path(args.audit_file)
    profile_map = _collect_profiles(profiles_dir, run_id=args.run_id)
    audit_map = _collect_audit_rows(audit_file, run_id=args.run_id)

    run_ids = sorted(set(profile_map.keys()) | set(audit_map.keys()))
    analyses: list[RunAnalysis] = []
    for run_id in run_ids:
        analysis = _analyze_run(run_id, profile_map.get(run_id, []), audit_map.get(run_id, []))
        if analysis.read_prefetch_reason == "no_read_prefetch_metadata" and not analysis.read_prefetch_should_prefetch:
            continue
        analyses.append(analysis)

    _print_summary(analyses, limit=max(1, int(args.limit or 20)))


if __name__ == "__main__":
    main()
