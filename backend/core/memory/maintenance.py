"""Autonomous memory maintenance — indexing, dedup, promotion (P3).

Runs during agent idle/autonomous mode. Does NOT use LLM for extraction.
All operations are deterministic: file scan, hash dedup, keyword match, time decay.
"""

from __future__ import annotations

import hashlib
import os
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _hash_line(line: str) -> str:
    return hashlib.sha256(line.strip().encode("utf-8")).hexdigest()[:16]


# ── Dedup helpers ─────────────────────────────────────────────────


def dedup_inbox(inbox_path: str | Path) -> dict:
    """Remove duplicate entries from the memory inbox. Returns {removed, kept, report}."""
    path = Path(inbox_path)
    if not path.is_file():
        return {"removed": 0, "kept": 0, "report": "inbox not found"}

    content = path.read_text(encoding="utf-8", errors="replace")
    entries = re.split(r"\n(?=## )", content)
    if len(entries) <= 1:
        return {"removed": 0, "kept": 1, "report": "single entry or empty"}

    seen: set[str] = set()
    unique: list[str] = []
    removed = 0

    for entry in entries:
        stripped = entry.strip()
        if not stripped:
            continue
        h = _hash_line(stripped[:200])
        if h in seen:
            removed += 1
        else:
            seen.add(h)
            unique.append(stripped)

    if removed > 0:
        path.write_text("\n\n".join(unique) + "\n", encoding="utf-8")

    return {"removed": removed, "kept": len(unique), "report": f"dedup: removed {removed} duplicates"}


# ── Time decay ────────────────────────────────────────────────────


def _entry_age_days(entry_text: str) -> int | None:
    """Extract Saved At date from an inbox entry."""
    m = re.search(r"Saved At:\s*(\d{4}-\d{2}-\d{2})", entry_text)
    if not m:
        return None
    try:
        saved = datetime.strptime(m.group(1), "%Y-%m-%d").replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - saved).days
    except ValueError:
        return None


def score_inbox_entries(inbox_path: str | Path) -> list[dict]:
    """Score all inbox entries by recency + frequency signals. Returns sorted list."""
    path = Path(inbox_path)
    if not path.is_file():
        return []

    content = path.read_text(encoding="utf-8", errors="replace")
    entries = re.split(r"\n(?=## )", content)
    scores: list[dict] = []

    for entry in entries:
        stripped = entry.strip()
        if not stripped or not stripped.startswith("## "):
            continue

        age = _entry_age_days(stripped)
        question_count = len(re.findall(r"^\s*-\s+", stripped, re.MULTILINE))
        file_count = len(re.findall(r"Files Touched:", stripped))

        # Score: recency bonus + content richness
        score = 0.0
        if age is not None:
            score += max(0, 7 - age) * 1.0  # recent entries (≤7 days) get up to 7 points
        score += min(question_count, 5) * 0.5  # up to 2.5 points for questions
        score += min(file_count, 3) * 1.0  # up to 3 points for file touches

        scores.append({
            "title": stripped.split("\n")[0].replace("## ", "").strip()[:60],
            "age_days": age,
            "questions": question_count,
            "files_touched": file_count,
            "score": round(score, 1),
            "hash": _hash_line(stripped[:200]),
        })

    scores.sort(key=lambda s: s["score"], reverse=True)
    return scores


# ── Global memory context builder ──────────────────────────────────


def build_scoped_memory_context(
    user_query: str,
    max_chars: int = 3000,
) -> dict:
    """Build a scoped memory context block matching the query's keywords.
    Instead of injecting ALL of L1/L2, extract relevant sections by keyword match.
    Returns {context, source_files, matched_keywords, total_chars}.
    """
    project_root = Path(__file__).resolve().parent.parent.parent
    memory_dir = project_root / "memory"

    # Extract keywords from query
    query_lower = user_query.lower()
    keywords: list[str] = []
    # Chinese: split by common delimiters, filter short tokens
    for token in re.split(r"[，。！？、；：\s]+", user_query):
        token = token.strip()
        if len(token) >= 2:
            keywords.append(token)
    # Also keep the full query lowercased
    keywords.append(query_lower)

    context_parts: list[str] = []
    sources: list[str] = []

    for mem_file, label in [("global_mem_insight.txt", "L1"), ("global_mem.txt", "L2")]:
        path = memory_dir / mem_file
        if not path.is_file():
            continue
        content = path.read_text(encoding="utf-8", errors="replace")
        # Match: find paragraphs containing any keyword
        paragraphs = re.split(r"\n\n+", content)
        matched_paras = []
        for para in paragraphs:
            para_lower = para.lower()
            if any(kw.lower() in para_lower for kw in keywords):
                matched_paras.append(para.strip())
        if matched_paras:
            block = "\n\n".join(matched_paras)
            if len(block) > max_chars // 2:
                block = block[: max_chars // 2] + "\n... [truncated]"
            context_parts.append(f"[{label}] {path.name}:\n{block}")
            sources.append(str(path))

    context = "\n\n".join(context_parts)
    return {
        "context": context[:max_chars],
        "source_files": sources,
        "matched_keywords": [kw for kw in keywords if kw.lower() in context.lower()],
        "total_chars": len(context),
    }


# ── Maintenance orchestrator ──────────────────────────────────────


def run_memory_maintenance(project_root: str | Path | None = None) -> dict:
    """Run all deterministic memory maintenance tasks. Returns a report.
    Safe to call during autonomous idle mode — reads files, dedups inbox, builds scores.
    """
    root = Path(project_root) if project_root else Path(__file__).resolve().parent.parent.parent
    memory_dir = root / "memory"
    inbox_path = memory_dir / "history_memory_inbox.md"

    report: dict[str, Any] = {
        "ran_at": _utc_now_iso(),
        "tasks": {},
    }

    # 1. Dedup inbox
    dedup_result = dedup_inbox(inbox_path)
    report["tasks"]["dedup"] = dedup_result

    # 2. Score inbox entries
    scores = score_inbox_entries(inbox_path)
    report["tasks"]["scored_entries"] = len(scores)
    report["tasks"]["top_entries"] = [
        {"title": s["title"], "score": s["score"], "age_days": s["age_days"]}
        for s in scores[:5]
    ]

    # 3. Check structured memory availability
    catalog_path = memory_dir / "catalog.sqlite"
    report["tasks"]["structured_memory_available"] = catalog_path.is_file()

    # 4. Quick stats on memory files
    for fname in ["global_mem_insight.txt", "global_mem.txt", "history_memory_inbox.md"]:
        fpath = memory_dir / fname
        if fpath.is_file():
            report["tasks"][f"size_{fname}"] = fpath.stat().st_size

    # 5. Archive inbox to structured memory (inbox → catalog.sqlite)
    try:
        archive_result = archive_inbox_to_structured(
            project_root=root,
            dry_run=False,
            backup_first=True,
            truncate_after_write=False,
        )
        report["tasks"]["archive"] = archive_result
    except Exception as e:
        report["tasks"]["archive"] = {"error": str(e)}

    return report


# ── Inbox archive ──────────────────────────────────────────────────


def archive_inbox_to_structured(
    project_root: str | Path | None = None,
    *,
    dry_run: bool = True,
    backup_first: bool = True,
    truncate_after_write: bool = False,
) -> dict[str, Any]:
    """Archive history_memory_inbox.md entries to structured memory tables.

    Reads the inbox, chunks entries, SHA256-deduplicates against existing
    evidence_chunks, and (if dry_run=False) inserts into memory_candidates
    and evidence_chunks.

    dry_run=True (default):
        Preview only. Returns a report of what WOULD be written.
        Does NOT modify the database or inbox.

    dry_run=False:
        Writes to memory_candidates + evidence_chunks.
        If backup_first=True, copies inbox to a .bak file first.

    truncate_after_write=True (P2b):
        After verified write, truncate only the archived entries from inbox.
        Requires backup_first=True (backup is mandatory before truncation).
        Non-archived entries (skipped duplicates) are preserved.

    Returns:
        {
            "dry_run": bool,
            "total_entries": int,
            "new_entries": int,
            "skipped_duplicates": int,
            "written_chunks": int,
            "written_candidates": int,
            "backup_path": str | None,
            "truncated": bool,
            "truncated_entries": int,
            "remaining_entries": int,
            "errors": list[str],
            "preview_entries": [...],
        }
    """
    root = Path(project_root) if project_root else Path(__file__).resolve().parent.parent.parent
    memory_dir = root / "memory"
    inbox_path = memory_dir / "history_memory_inbox.md"
    db_path = memory_dir / "catalog.sqlite"
    report: dict[str, Any] = {
        "dry_run": dry_run,
        "total_entries": 0,
        "new_entries": 0,
        "skipped_duplicates": 0,
        "written_chunks": 0,
        "written_candidates": 0,
        "backup_path": None,
        "truncated": False,
        "truncated_entries": 0,
        "remaining_entries": 0,
        "errors": [],
        "preview_entries": [],
    }

    if not inbox_path.is_file():
        report["errors"].append("inbox not found")
        return report

    # ── Read inbox ──
    content = inbox_path.read_text(encoding="utf-8", errors="replace")
    entries = re.split(r"\n(?=## )", content)
    # Filter out the header line (starts with "# " not "## ")
    entries = [e.strip() for e in entries if e.strip().startswith("## ")]
    report["total_entries"] = len(entries)

    if not entries:
        return report

    # ── Collect existing hashes ──
    existing_hashes: set[str] = set()
    if db_path.is_file():
        try:
            from .store import MemoryStore
            store = MemoryStore(db_path)
            store.init_db()
            with store._connection() as conn:
                rows = conn.execute(
                    "SELECT content_hash FROM evidence_chunks WHERE content_hash IS NOT NULL"
                ).fetchall()
                existing_hashes = {r["content_hash"] for r in rows if r["content_hash"]}
        except Exception as e:
            report["errors"].append(f"failed to read existing hashes: {e}")

    # ── Chunk and dedup ──
    new_entries_data: list[dict[str, Any]] = []
    seen_hashes: set[str] = set()
    for entry in entries:
        entry_hash = hashlib.sha256(entry.encode("utf-8")).hexdigest()
        if entry_hash in existing_hashes or entry_hash in seen_hashes:
            report["skipped_duplicates"] += 1
            continue
        seen_hashes.add(entry_hash)

        # Extract metadata
        title_match = re.search(r"^## (.+)", entry)
        title = title_match.group(1).strip()[:120] if title_match else "Untitled"
        saved_match = re.search(r"Saved At:\s*(.+)", entry)
        saved_at = saved_match.group(1).strip() if saved_match else _utc_now_iso()
        source_match = re.search(r"Source File:\s*(.+)", entry)
        source = source_match.group(1).strip() if source_match else "inbox"
        run_match = re.search(r"Run:\s*(.+)", entry)
        run_id = run_match.group(1).strip() if run_match else ""

        # Chunk: split entry into paragraphs
        paragraphs = re.split(r"\n\n+", entry)
        chunks: list[dict[str, Any]] = []
        for i, para in enumerate(paragraphs):
            para = para.strip()
            if not para:
                continue
            chunk_hash = hashlib.sha256(para.encode("utf-8")).hexdigest()
            chunks.append({
                "index": i,
                "content": para[:4000],
                "content_hash": chunk_hash,
            })

        new_entries_data.append({
            "title": title,
            "source": source,
            "run_id": run_id,
            "saved_at": saved_at,
            "entry_hash": entry_hash,
            "full_content": entry[:8000],
            "chunks": chunks,
        })

    report["new_entries"] = len(new_entries_data)

    # ── Preview (dry_run) ──
    if dry_run:
        report["preview_entries"] = [
            {
                "title": e["title"],
                "source": e["source"],
                "run_id": e["run_id"],
                "saved_at": e["saved_at"],
                "chunks_count": len(e["chunks"]),
                "content_preview": e["full_content"][:300],
            }
            for e in new_entries_data[:5]
        ]
        return report

    # ── Write (not dry_run) ──
    # Backup first
    if backup_first:
        backup_path = inbox_path.with_suffix(".md.bak")
        try:
            import shutil
            shutil.copy2(inbox_path, backup_path)
            report["backup_path"] = str(backup_path)
        except Exception as e:
            report["errors"].append(f"backup failed: {e}")
            return report

    if not db_path.is_file():
        from .store import MemoryStore
        store = MemoryStore(db_path)
        store.init_db()

    try:
        from .store import MemoryStore
        store = MemoryStore(db_path)

        with store._connection() as conn:
            for entry_data in new_entries_data:
                chunk_id = str(uuid4())
                now = _utc_now_iso()

                # Insert evidence_chunks (one per chunk)
                for chunk in entry_data["chunks"]:
                    conn.execute(
                        """INSERT OR IGNORE INTO evidence_chunks
                           (id, source_path, content, content_hash, summary,
                            run_id, created_at)
                           VALUES (?, ?, ?, ?, ?, ?, ?)""",
                        (
                            str(uuid4()),
                            f"inbox:{entry_data['title'][:80]}",
                            chunk["content"],
                            chunk["content_hash"],
                            entry_data["title"][:200],
                            entry_data["run_id"] or "",
                            now,
                        ),
                    )
                    report["written_chunks"] += 1

                # Insert memory_candidate
                conn.execute(
                    """INSERT OR IGNORE INTO memory_candidates
                       (id, source, content, kind, status, created_at, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (
                        chunk_id,
                        entry_data["source"],
                        entry_data["full_content"],
                        "inbox_archive",
                        "pending",
                        now,
                        now,
                    ),
                )
                report["written_candidates"] += 1

    except Exception as e:
        report["errors"].append(f"write failed: {e}")
        return report

    # ── Truncate (P2b): only remove what was archived ──
    if not truncate_after_write:
        return report

    if not report["backup_path"]:
        report["errors"].append("truncation requires backup_first=True")
        return report

    if report["errors"]:
        report["errors"].append("truncation skipped due to write errors")
        return report

    if report["new_entries"] == 0:
        return report  # nothing to truncate

    try:
        # Re-read the inbox
        current_content = inbox_path.read_text(encoding="utf-8", errors="replace")
        current_entries = re.split(r"\n(?=## )", current_content)

        # Separate header from entries
        header_lines: list[str] = []
        entry_lines: list[str] = []
        for part in current_entries:
            part = part.strip()
            if part.startswith("## "):
                entry_lines.append(part)
            elif not entry_lines:  # before first ## entry — this is the header
                header_lines.append(part)

        # Build set of archived hashes
        archived_hashes: set[str] = seen_hashes  # from dedup phase

        # Keep entries NOT in the archived set
        kept_entries: list[str] = []
        truncated_count = 0
        for entry in entry_lines:
            entry_hash = hashlib.sha256(entry.encode("utf-8")).hexdigest()
            if entry_hash in archived_hashes:
                truncated_count += 1
            else:
                kept_entries.append(entry)

        # Write back: header + remaining entries
        new_content = "\n".join(header_lines).strip()
        if kept_entries:
            new_content += "\n\n" + "\n\n".join(kept_entries)
        new_content = new_content.strip() + "\n"

        inbox_path.write_text(new_content, encoding="utf-8")

        report["truncated"] = True
        report["truncated_entries"] = truncated_count
        report["remaining_entries"] = len(kept_entries)

        # Verify: re-read and count
        verify_content = inbox_path.read_text(encoding="utf-8", errors="replace")
        verify_entries = [e for e in re.split(r"\n(?=## )", verify_content) if e.strip().startswith("## ")]
        expected_remaining = report["total_entries"] - truncated_count
        if len(verify_entries) != expected_remaining:
            report["errors"].append(
                f"truncation verify failed: expected {expected_remaining} remaining, "
                f"got {len(verify_entries)}"
            )

    except Exception as e:
        report["errors"].append(f"truncation failed: {e}")

    return report


# ── Standalone CLI ─────────────────────────────────────────────────


if __name__ == "__main__":
    import json
    report = run_memory_maintenance()
    print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
