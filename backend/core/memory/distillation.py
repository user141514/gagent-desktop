"""
Distillation — memory distillation trigger and candidate builder.

Extracted from ga.py:do_start_long_term_update() so the OpenAI path can
trigger distillation without importing ga.py internals.

Gated by GA_OPENAI_DISTILLATION:
  "0"       — off, do nothing
  "preview" — generate candidate, log to disk, do NOT write to inbox (default)
  "write"   — generate candidate AND append to history_memory_inbox.md

Classic path behavior is unchanged — ga.py continues to use its own
do_start_long_term_update() pathway.
"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


# ══════════════════════════════════════════════════════════════════════
# Env-var gate
# ══════════════════════════════════════════════════════════════════════

_DISTILLATION_MODE_VAR = "GA_OPENAI_DISTILLATION"
_DEFAULT_MODE = "preview"
_VALID_MODES = {"0", "off", "preview", "write"}


def get_distillation_mode() -> str:
    """Return 'off', 'preview', or 'write'. Default is 'preview'."""
    raw = os.environ.get(_DISTILLATION_MODE_VAR, _DEFAULT_MODE).strip().lower()
    if raw in ("0", "off"):
        return "off"
    if raw == "write":
        return "write"
    return "preview"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _default_root() -> Path:
    return Path(__file__).resolve().parent.parent.parent


# ══════════════════════════════════════════════════════════════════════
# Distillation trigger prompt
# ══════════════════════════════════════════════════════════════════════

def trigger_distillation(project_root: str | Path | None = None) -> str:
    """Generate the distillation instruction prompt.

    This is the prompt that instructs the agent to review recent work,
    extract verified facts, and prepare memory updates.

    Returns empty string when distillation mode is 'off'.
    """
    mode = get_distillation_mode()
    if mode == "off":
        return ""

    root = Path(project_root) if project_root else _default_root()

    prompt = (
        "### [总结提炼经验] 既然你觉得当前任务有重要信息需要记忆，"
        "请提取最近一次任务中【事实验证成功且长期有效】的环境事实、用户偏好、重要步骤，更新记忆。\n"
        "本工具是标记开启结算过程，若已在更新记忆过程或没有值得记忆的点，忽略本次调用。\n"
        "**提取行动验证成功的信息**：\n"
        "- **环境事实**（路径/凭证/配置）→ `file_patch` 更新 L2，同步 L1\n"
        "- **复杂任务经验**（关键坑点/前置条件/重要步骤）→ L3 精简 SOP"
        "（只记你被坑得多次重试的核心要点）\n"
        "**禁止**：临时变量、具体推理过程、未验证信息、通用常识、你可以轻松复现的细节。\n"
        "**操作**：严格遵循提供的L0的记忆更新SOP。先 `file_read` 看现有 → 判断类型 → "
        "最小化更新 → 无新内容跳过，保证对记忆库最小局部修改。\n"
    )

    # Append current L1/L2 memory (same as Classic)
    from .legacy_global import build_legacy_memory_block

    mem_block = build_legacy_memory_block(root)
    if mem_block:
        prompt += mem_block

    return prompt


# ══════════════════════════════════════════════════════════════════════
# Distillation candidate builder
# ══════════════════════════════════════════════════════════════════════

def build_distillation_candidate(
    *,
    summary: str,
    source: str = "openai",
    run_id: str = "",
    task: str = "",
    session: str = "",
    files_touched: list[str] | None = None,
    questions: list[str] | None = None,
    is_proposed: bool = False,
) -> dict[str, Any]:
    """Build a structured distillation candidate.

    This is a PREVIEW candidate — it does NOT write to inbox unless
    the mode is 'write' and write_distillation_candidate() is called.

    Args:
        summary: The distilled summary (agent's extracted memory).
        source: Source path — "openai" or "classic".
        run_id: Profile run ID for traceability.
        task: Task description.
        session: Session identifier.
        files_touched: Files modified during the task.
        questions: Questions the distillation addresses.
        is_proposed: True if this is a proposal (not yet executed).
                     Proposed candidates must NOT be written to inbox.

    Returns:
        Dict with candidate data and metadata.
    """
    now = _utc_now_iso()
    title = (summary.split("\n")[0] if summary else "Untitled")[:80].strip()

    candidate: dict[str, Any] = {
        "title": title,
        "summary": summary,
        "source": source,
        "run_id": run_id,
        "task": task,
        "session": session,
        "is_proposed": is_proposed,
        "files_touched": list(files_touched or []),
        "questions": list(questions or []),
        "generated_at": now,
        "mode": get_distillation_mode(),
    }

    return candidate


# ══════════════════════════════════════════════════════════════════════
# M8: Cross-reference verification
# ══════════════════════════════════════════════════════════════════════

def verify_distillation_candidate(
    candidate: dict[str, Any],
    tool_event_ledger: Any | None = None,
    change_classifier: Any | None = None,
) -> dict[str, Any]:
    """Cross-reference a distillation candidate against tool execution evidence.

    M8: Adds tool_cross_reference metadata to the candidate. This allows
    downstream consumers (preview, write gate) to distinguish between
    evidence-backed claims and unverified assistant output.

    Args:
        candidate: From build_distillation_candidate().
        tool_event_ledger: ToolEventLedger instance (from M7) or None.
        change_classifier: ChangeClassifier instance (from M7) or None.

    Returns:
        The candidate dict with added tool_cross_reference field:
        {
            "verified": bool,
            "matched_events": int,
            "matched_files": list[str],
            "unmatched_files": list[str],
            "ledger_available": bool,
            "classifier_pending": int,
            "classifier_executed": int,
        }
    """
    ref: dict[str, Any] = {
        "verified": False,
        "matched_events": 0,
        "matched_files": [],
        "unmatched_files": [],
        "ledger_available": False,
        "classifier_pending": 0,
        "classifier_executed": 0,
    }

    # ── Cross-reference with tool event ledger ──
    if tool_event_ledger is not None:
        try:
            events = tool_event_ledger.recent_events(50)
            ref["ledger_available"] = True
            ref["matched_events"] = len(events)

            # Check if candidate's files_touched have corresponding tool events
            candidate_files = set(candidate.get("files_touched") or [])
            if candidate_files and events:
                # Extract paths from tool events
                tool_paths: set[str] = set()
                for e in events:
                    if e.target_path:
                        tool_paths.add(e.target_path)
                    # Also check args_summary for path references
                    args = str(e.args_summary or "")
                    import re
                    for m in re.finditer(r'["\']?([^"\',]+\.(?:py|txt|md|json|toml|cfg|yaml|yml|js|ts|html|css))["\']?', args):
                        tool_paths.add(m.group(1))

                matched = candidate_files & tool_paths
                unmatched = candidate_files - tool_paths
                ref["matched_files"] = sorted(matched)
                ref["unmatched_files"] = sorted(unmatched)

                # If a candidate names files, only matching file-level tool
                # evidence can verify it. Unrelated recent tool events are not
                # proof that the claimed file was changed.
                if matched:
                    ref["verified"] = True
            elif events:
                ref["verified"] = True
        except Exception:
            pass

    # ── Cross-reference with change classifier ──
    if change_classifier is not None:
        try:
            pending = change_classifier.get_pending()
            executed = change_classifier.get_executed()
            ref["classifier_pending"] = len(pending)
            ref["classifier_executed"] = len(executed)

            # If there are executed changes, the candidate is more likely verified
            if executed and not ref["verified"]:
                ref["verified"] = True
        except Exception:
            pass

    # ── Attach to candidate ──
    candidate["tool_cross_reference"] = ref
    return candidate


def build_verified_candidate(
    *,
    summary: str,
    source: str = "openai",
    run_id: str = "",
    task: str = "",
    session: str = "",
    files_touched: list[str] | None = None,
    questions: list[str] | None = None,
    is_proposed: bool = False,
    tool_event_ledger: Any | None = None,
    change_classifier: Any | None = None,
) -> dict[str, Any]:
    """Build and verify a distillation candidate in one step.

    M8: Wraps build_distillation_candidate() + verify_distillation_candidate().
    The returned candidate includes tool_cross_reference metadata.
    """
    candidate = build_distillation_candidate(
        summary=summary,
        source=source,
        run_id=run_id,
        task=task,
        session=session,
        files_touched=files_touched,
        questions=questions,
        is_proposed=is_proposed,
    )
    return verify_distillation_candidate(candidate, tool_event_ledger, change_classifier)


def format_inbox_entry(candidate: dict[str, Any]) -> str:
    """Format a distillation candidate as a history_memory_inbox.md entry.

    Matches the Classic path inbox format for compatibility with maintenance
    tools (dedup_inbox, score_inbox_entries):

        ## <title>
        <!-- source: <run_id> -->
        - Saved At: <datetime>
        - Source File: <source>
        - Run: <run_id>
        - Session: <session>
        - Task: <task>
        - Dialogue Rounds: <N>
        - User Questions:
          - q1
          - q2
        - Files Touched:
          - file1
          - file2
        - Key Replies:
          - <summary>

    Returns empty string if candidate is marked as proposed (not executed).
    """
    if candidate.get("is_proposed"):
        return ""  # Never write proposed changes to inbox

    title = candidate.get("title", "Untitled")
    # Strip leading markdown headings to avoid "## ## ..."
    title = title.lstrip("#").strip()[:80]
    saved_at = candidate.get("generated_at", _utc_now_iso())[:19]
    source = candidate.get("source", "unknown")
    run_id = candidate.get("run_id", "")
    session = candidate.get("session", "")
    task = candidate.get("task", "")
    summary = candidate.get("summary", "")
    questions = candidate.get("questions") or []
    files = candidate.get("files_touched") or []

    lines = [
        f"## {title}",
        f"<!-- source: {run_id or source} -->",
        f"- Saved At: {saved_at}",
        f"- Source File: {source}",
    ]
    if run_id:
        lines.append(f"- Run: {run_id}")
    if session:
        lines.append(f"- Session: {session}")
    if task:
        lines.append(f"- Task: {task}")

    # Extract questions from summary if none provided
    if not questions:
        import re
        q_matches = re.findall(r"(?:^|\n)\s*[-*]\s+(.+?)(?:\n|$)", summary or "")
        questions = [q.strip()[:120] for q in q_matches if q.strip()][:10]

    rounds = max(1, len(questions) or 1)
    lines.append(f"- Dialogue Rounds: {rounds}")

    if questions:
        lines.append("- User Questions:")
        for q in questions:
            lines.append(f"  - {q}")

    if files:
        lines.append("- Files Touched:")
        for f in files:
            lines.append(f"  - {f}")

    lines.append("- Key Replies:")
    reply_lines = (summary or "").strip().split("\n")
    for rl in reply_lines[:10]:
        rl = rl.strip()
        if rl:
            lines.append(f"  - {rl}")

    lines.append("")
    return "\n".join(lines)


# ══════════════════════════════════════════════════════════════════════
# Write gate
# ══════════════════════════════════════════════════════════════════════

def write_distillation_candidate(
    candidate: dict[str, Any],
    project_root: str | Path | None = None,
) -> dict[str, Any]:
    """Write a distillation candidate to history_memory_inbox.md.

    ONLY writes when GA_OPENAI_DISTILLATION='write'.
    In 'preview' mode, logs the candidate to temp/distillation_previews/ instead.
    In 'off' mode, does nothing.

    Refuses to write if candidate['is_proposed'] is True.

    Returns a result dict with {written, path, reason, mode}.
    """
    mode = get_distillation_mode()
    root = Path(project_root) if project_root else _default_root()

    result: dict[str, Any] = {
        "written": False,
        "path": "",
        "reason": "",
        "mode": mode,
    }

    if mode == "off":
        result["reason"] = "distillation disabled"
        return result

    if candidate.get("is_proposed"):
        result["reason"] = "refused: candidate is a proposal, not executed fact"
        return result

    entry = format_inbox_entry(candidate)
    if not entry:
        result["reason"] = "empty candidate (or proposed-only)"
        return result

    if mode == "preview":
        # Preview: write candidate JSON to temp/ for inspection
        # M8: Enhanced with tool_cross_reference verification metadata
        preview_dir = root / "temp" / "distillation_previews"
        preview_dir.mkdir(parents=True, exist_ok=True)
        ts = int(time.time())
        run_id = candidate.get("run_id", "") or f"draft_{ts}"
        preview_path = preview_dir / f"{run_id}_{ts}.json"

        # ── M8: Auto-verify if ledger/classifier available ──
        _xref = candidate.get("tool_cross_reference")
        if _xref is None:
            # Try lazy verification if not already done
            try:
                from core.context.tool_event_ledger import ToolEventLedger
                from core.context.change_classifier import ChangeClassifier
                # Can't auto-create instances here — caller must pass them
                pass
            except Exception:
                pass

        try:
            preview_data = {
                "candidate": candidate,
                "formatted_entry": entry,
                "mode": mode,
                "generated_at": candidate.get("generated_at", _utc_now_iso()),
                # M8: Highlight verification status in preview
                "tool_cross_reference": _xref or {
                    "verified": False,
                    "note": "No ToolEventLedger provided to verify_distillation_candidate()",
                },
                "verification_status": (
                    "VERIFIED" if (_xref or {}).get("verified")
                    else "UNVERIFIED" if _xref is not None
                    else "NOT_CHECKED"
                ),
            }
            preview_path.write_text(
                json.dumps(preview_data, ensure_ascii=False, indent=2, default=str),
                encoding="utf-8",
            )
            result["path"] = str(preview_path)
            result["reason"] = f"preview: logged to temp/distillation_previews/ (verification: {preview_data['verification_status']})"
        except Exception as e:
            result["reason"] = f"preview write failed: {e}"
        return result

    # mode == "write"
    inbox_path = root / "memory" / "history_memory_inbox.md"
    try:
        # Ensure memory dir exists
        inbox_path.parent.mkdir(parents=True, exist_ok=True)
        # Append
        existing = ""
        if inbox_path.is_file():
            existing = inbox_path.read_text(encoding="utf-8", errors="replace")
        content = (existing + "\n" + entry).strip() + "\n"
        inbox_path.write_text(content, encoding="utf-8")
        result["written"] = True
        result["path"] = str(inbox_path)
        result["reason"] = "appended to history_memory_inbox.md"
    except Exception as e:
        result["reason"] = f"write failed: {e}"

    return result
