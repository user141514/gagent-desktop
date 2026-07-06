"""
Legacy Global Memory — shared read-only L1/L2 access for Classic + OpenAI paths.

DEPRECATED: phase=M3, replaced_by=core.context.memory_reader.MemoryReader
This module's read_legacy_l1_l2() and build_legacy_memory_block() are
superseded by the canonical MemoryReader + ContextBuilder pipeline.
Existing callers continue to work; no new callers should be added.

Does NOT write to global_mem.txt, global_mem_insight.txt, or any other file.
Pure read functions extracted from ga.py:get_global_memory() so the OpenAI
path can access the same L1/L2 memory without importing ga.py internals.

Classic path behavior is preserved: get_global_memory() continues to work
identically, now calling build_legacy_memory_block() under the hood.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any


# DEPRECATED: phase=M3, replaced_by=core.context.memory_reader.MemoryReader.read_global_memory()
def read_legacy_l1_l2(project_root: str | Path | None = None) -> dict[str, Any]:
    """DEPRECATED. Read legacy L1 (global_mem_insight.txt) and L2 (global_mem.txt).

    Pure read - no side effects, no writes.

    Returns:
        {
            "l1": str | None,           # L1 insight content (or None if missing)
            "l2": str | None,           # L2 environment facts (or None if missing)
            "l1_path": str,             # absolute path to L1 file
            "l2_path": str,             # absolute path to L2 file
            "l1_chars": int,            # character count of L1
            "l2_chars": int,            # character count of L2
            "total_chars": int,         # L1 + L2 chars
        }
    """
    root = Path(project_root) if project_root else _default_root()

    result: dict[str, Any] = {
        "l1": None,
        "l2": None,
        "l1_path": str(root / "memory" / "global_mem_insight.txt"),
        "l2_path": str(root / "memory" / "global_mem.txt"),
        "l1_chars": 0,
        "l2_chars": 0,
        "total_chars": 0,
    }

    # L1
    l1_path = root / "memory" / "global_mem_insight.txt"
    if l1_path.is_file():
        try:
            content = l1_path.read_text(encoding="utf-8", errors="replace")
            result["l1"] = content
            result["l1_chars"] = len(content)
            result["total_chars"] += len(content)
        except Exception:
            pass

    # L2
    l2_path = root / "memory" / "global_mem.txt"
    if l2_path.is_file():
        try:
            content = l2_path.read_text(encoding="utf-8", errors="replace")
            if content.strip():
                result["l2"] = content
                result["l2_chars"] = len(content)
                result["total_chars"] += len(content)
        except Exception:
            pass

    return result


# DEPRECATED: phase=M3, replaced_by=core.context.context_builder.ContextBuilder.build()
def build_legacy_memory_block(project_root: str | Path | None = None) -> str:
    """DEPRECATED. Build the formatted L1/L2 prompt block matching Classic get_global_memory().

    This reproduces the EXACT output format of ga.py:get_global_memory().

    The block includes:
    - cwd / project_root paths
    - L1 insight content with structure template
    - L2 environment facts (if not empty)

    Returns:
        Formatted prompt string, or "" if L1 file is missing.
    """
    root = Path(project_root) if project_root else _default_root()
    prompt = "\n"

    try:
        suffix = "_en" if os.environ.get("GA_LANG", "") == "en" else ""

        # L1
        insight_path = root / "memory" / "global_mem_insight.txt"
        if not insight_path.is_file():
            return ""
        insight = insight_path.read_text(encoding="utf-8", errors="replace")

        # Structure template
        structure_path = root / "assets" / f"insight_fixed_structure{suffix}.txt"
        structure = ""
        if structure_path.is_file():
            structure = structure_path.read_text(encoding="utf-8")

        prompt += f'cwd = {os.path.join(str(root), "temp")} (./)\n'
        prompt += f'project_root = {root} (../)\n'
        prompt += (
            "Interpret user-facing 'current folder/current project/current repository' "
            "as project_root (../), unless the user explicitly asks for temp/scratch cwd.\n"
        )
        prompt += "\n[Memory] (../memory)\n"
        prompt += structure + "\n../memory/global_mem_insight.txt:\n"
        prompt += insight + "\n"

        # L2
        l2_path = root / "memory" / "global_mem.txt"
        if l2_path.is_file():
            l2_content = l2_path.read_text(encoding="utf-8", errors="replace")
            if l2_content.strip():
                prompt += "\n../memory/global_mem.txt (L2环境事实):\n" + l2_content + "\n"
    except FileNotFoundError:
        pass

    return prompt


def _default_root() -> Path:
    """Default project root — parent of the core/ directory."""
    return Path(__file__).resolve().parent.parent.parent
