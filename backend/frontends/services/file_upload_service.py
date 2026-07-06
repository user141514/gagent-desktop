"""File upload service — decouples upload processing from Streamlit UI.

Receives Streamlit ``UploadedFile`` objects at the boundary, delegates
all parsing / saving / preview / metadata logic to ``file_processor``,
and returns plain ``UploadedFileInfo`` dataclass instances.

Does NOT depend on ``st.session_state``, ``st.spinner``, or any other
Streamlit runtime object beyond the ``UploadedFile`` input type.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from frontends.file_processor import (
    build_upload_id,
    process_uploaded_file,
)


@dataclass
class UploadedFileInfo:
    """Processed result for a single uploaded file.  Streamlit-free."""

    file_id: str
    name: str
    size: int = 0
    size_label: str = ""
    mime_type: str = ""
    kind: str = ""
    suffix: str = ""
    saved_path: str = ""
    status: str = "pending"
    preview_text: str = ""
    distilled_text: str = ""
    raw_text_length: int = 0
    warning: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def is_ready(self) -> bool:
        return self.status == "ready"

    def to_dict(self) -> dict[str, Any]:
        """Convert back to the legacy dict format expected by stapp.py helpers.

        Extra metadata (page_count, toc_count, etc.) is merged in so no
        information from ``file_processor`` is lost.
        """
        d = {
            "id": self.file_id,
            "name": self.name,
            "size": self.size,
            "size_label": self.size_label,
            "mime": self.mime_type,
            "kind": self.kind,
            "stored_path": self.saved_path,
            "status": self.status,
            "preview_text": self.preview_text,
            "distilled_text": self.distilled_text,
            "raw_text_length": self.raw_text_length,
            "warning": self.warning,
        }
        d.update(self.metadata)
        return d


class FileUploadService:
    """Processes uploaded files into ``UploadedFileInfo`` with dedup cache.

    Usage from Streamlit::

        service = FileUploadService(cache=st.session_state.processed_upload_cache)
        results = service.process(uploaded_items, on_progress=lambda name: st.spinner(f"处理中: {name}"))
        st.session_state.uploaded_files = [r.to_dict() for r in results]
    """

    def __init__(self, cache: dict[str, dict[str, Any]] | None = None) -> None:
        self._cache: dict[str, dict[str, Any]] = cache if cache is not None else {}

    # ── public API ──────────────────────────────────────────────────────

    def process(
        self,
        uploaded_items: list[Any],
        *,
        on_progress: Callable[[str], object] | None = None,
    ) -> list[UploadedFileInfo]:
        """Process a batch of Streamlit ``UploadedFile`` objects.

        Returns one ``UploadedFileInfo`` per file.  Already-processed files
        (matched by content hash) are served from the internal cache without
        re-processing.
        """
        results: list[UploadedFileInfo] = []
        for uploaded in uploaded_items or []:
            info = self._process_one(uploaded, on_progress=on_progress)
            results.append(info)
        return results

    def process_one(
        self,
        uploaded_file: Any,
        *,
        on_progress: Callable[[str], object] | None = None,
    ) -> UploadedFileInfo:
        """Process a single Streamlit ``UploadedFile``."""
        return self._process_one(uploaded_file, on_progress=on_progress)

    # ── internal ────────────────────────────────────────────────────────

    def _process_one(
        self,
        uploaded: Any,
        *,
        on_progress: Callable[[str], object] | None = None,
    ) -> UploadedFileInfo:
        name = getattr(uploaded, "name", "upload")
        data = uploaded.getvalue() if hasattr(uploaded, "getvalue") else b""
        file_id = build_upload_id(name, data)

        # Dedup: return cached result when content hash matches
        if file_id in self._cache:
            return self._from_legacy_dict(self._cache[file_id])

        if on_progress is not None:
            on_progress(name)

        raw_meta = process_uploaded_file(uploaded)
        self._cache[file_id] = raw_meta
        return self._from_legacy_dict(raw_meta)

    _KNOWN_KEYS = frozenset({
        "id", "name", "size", "size_label", "mime", "kind",
        "stored_path", "status", "preview_text", "distilled_text",
        "raw_text_length", "warning",
    })

    @classmethod
    def _from_legacy_dict(cls, meta: dict[str, Any]) -> UploadedFileInfo:
        """Convert a ``file_processor`` result dict to ``UploadedFileInfo``."""
        extra = {k: v for k, v in meta.items() if k not in cls._KNOWN_KEYS}
        return UploadedFileInfo(
            file_id=meta.get("id", ""),
            name=meta.get("name", ""),
            size=meta.get("size", 0),
            size_label=meta.get("size_label", ""),
            mime_type=meta.get("mime", ""),
            kind=meta.get("kind", ""),
            saved_path=meta.get("stored_path", ""),
            status=meta.get("status", "pending"),
            preview_text=meta.get("preview_text", ""),
            distilled_text=meta.get("distilled_text", ""),
            raw_text_length=meta.get("raw_text_length", 0),
            warning=meta.get("warning", ""),
            metadata=extra,
        )
