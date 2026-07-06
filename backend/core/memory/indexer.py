"""Raw history file indexer for the structured memory ledger."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

from .store import MemoryStore

SUPPORTED_EXTENSIONS = {".txt", ".md", ".log", ".jsonl", ".json"}


def chunk_text(text: str, chunk_size: int = 1200, chunk_overlap: int = 150) -> list[str]:
    """Split plain text into stable overlapping chunks, preferring paragraph breaks."""
    text = (text or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if not text:
        return []
    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive")
    if chunk_overlap < 0:
        raise ValueError("chunk_overlap must be non-negative")
    if chunk_overlap >= chunk_size:
        raise ValueError("chunk_overlap must be smaller than chunk_size")

    chunks: list[str] = []
    start = 0
    min_cut = max(1, int(chunk_size * 0.6))
    text_len = len(text)

    while start < text_len:
        target = min(start + chunk_size, text_len)
        end = target
        if target < text_len:
            window = text[start + min_cut : target]
            paragraph_break = window.rfind("\n\n")
            line_break = window.rfind("\n")
            if paragraph_break >= 0:
                end = start + min_cut + paragraph_break + 2
            elif line_break >= 0:
                end = start + min_cut + line_break + 1
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= text_len:
            break
        next_start = max(end - chunk_overlap, start + 1)
        while next_start < text_len and text[next_start].isspace():
            next_start += 1
        start = next_start
    return chunks


class MemoryIndexer:
    def __init__(self, store: MemoryStore):
        self.store = store

    def index_file(
        self,
        path: str | Path,
        source_type: str | None = None,
        project_id: str | None = None,
        repo_id: str | None = None,
        session_id: str | None = None,
        run_id: str | None = None,
        chunk_size: int = 1200,
        chunk_overlap: int = 150,
    ) -> list[str]:
        file_path = Path(path).expanduser().resolve()
        if not file_path.is_file():
            return []
        if file_path.suffix.lower() not in SUPPORTED_EXTENSIONS:
            return []

        text = self._read_text_file(file_path)
        if not text.strip():
            return []

        actual_source_type = source_type or self._infer_source_type(file_path)
        actual_session_id = session_id or file_path.stem
        chunk_ids: list[str] = []

        for idx, chunk in enumerate(chunk_text(text, chunk_size=chunk_size, chunk_overlap=chunk_overlap)):
            chunk_hash = self._hash_text(chunk)
            source_path = str(file_path)
            existing_id = self.store.get_evidence_chunk_id(source_path, chunk_hash)
            if existing_id:
                chunk_ids.append(existing_id)
                continue
            evidence = self.store.add_evidence_chunk(
                source_path=source_path,
                source_type=actual_source_type,
                actor=self._infer_actor(chunk),
                content=chunk,
                content_hash=chunk_hash,
                summary=self._summarize_chunk(chunk),
                project_id=project_id,
                repo_id=repo_id,
                session_id=actual_session_id,
                run_id=run_id,
                turn_index=idx,
            )
            chunk_ids.append(evidence.id)
        return chunk_ids

    def index_directory(
        self,
        directory: str | Path,
        patterns: list[str] | None = None,
        recursive: bool = True,
        source_type: str | None = None,
        project_id: str | None = None,
        repo_id: str | None = None,
        session_id: str | None = None,
        run_id: str | None = None,
    ) -> list[str]:
        base_dir = Path(directory).expanduser().resolve()
        if not base_dir.is_dir():
            return []
        patterns = patterns or ["*.txt", "*.md", "*.log", "*.jsonl", "*.json"]
        matched: dict[str, Path] = {}
        for pattern in patterns:
            iterator = base_dir.rglob(pattern) if recursive else base_dir.glob(pattern)
            for path in iterator:
                if path.is_file():
                    matched[str(path.resolve())] = path.resolve()

        chunk_ids: list[str] = []
        for path in sorted(matched.values()):
            chunk_ids.extend(
                self.index_file(
                    path,
                    source_type=source_type,
                    project_id=project_id,
                    repo_id=repo_id,
                    session_id=session_id,
                    run_id=run_id,
                )
            )
        return chunk_ids

    @staticmethod
    def _read_text_file(path: Path) -> str:
        try:
            return path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            try:
                return path.read_text(encoding="utf-8-sig")
            except UnicodeDecodeError:
                return path.read_text(encoding="utf-8", errors="ignore")

    @staticmethod
    def _infer_source_type(path: Path) -> str:
        path_str = str(path).lower()
        name = path.name.lower()
        if "l4_raw_sessions" in path_str:
            return "raw_session"
        if "model_responses" in name or "model_responses" in path_str:
            return "model_response"
        if path.suffix.lower() == ".log":
            return "log"
        return "text_file"

    @staticmethod
    def _infer_actor(chunk: str) -> str | None:
        head = chunk.lstrip()
        if re.match(r"^(user:|用户:)", head, re.IGNORECASE):
            return "user"
        if re.match(r"^(assistant:|助手:)", head, re.IGNORECASE):
            return "assistant"
        return None

    @staticmethod
    def _hash_text(text: str) -> str:
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    @staticmethod
    def _summarize_chunk(chunk: str, limit: int = 200) -> str:
        first_line = next((line.strip() for line in chunk.splitlines() if line.strip()), "")
        summary = first_line or chunk.strip()
        return summary[:limit]
