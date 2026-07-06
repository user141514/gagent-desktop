from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ParsedSkill:
    name: str
    description: str
    content: str
    triggers: list[str]
    keywords: list[str]
    inputs: list[str]
    category: str
    applies_to: list[str]
    enabled: bool
    max_chars: int
    source_path: str
    format: str
    has_scripts: bool
    has_references: bool
    has_assets: bool
    has_mcp: bool
    risk_level: str
    import_status: str
    source_url: str = ""


def _coerce_scalar(value: str):
    raw = str(value or "").strip()
    if not raw:
        return ""
    lowered = raw.lower()
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    if lowered.isdigit():
        return int(lowered)
    if (raw.startswith('"') and raw.endswith('"')) or (raw.startswith("'") and raw.endswith("'")):
        return raw[1:-1]
    return raw


def _normalize_list(value) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value).strip()
    return [text] if text else []


def _parse_frontmatter(text: str) -> tuple[dict, str]:
    if not text.startswith("---"):
        return {}, text
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, text

    end_idx = None
    for idx in range(1, len(lines)):
        if lines[idx].strip() == "---":
            end_idx = idx
            break
    if end_idx is None:
        return {}, text

    meta: dict = {}
    current_list_key: str | None = None
    for line in lines[1:end_idx]:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("- ") and current_list_key is not None:
            existing = meta.setdefault(current_list_key, [])
            if isinstance(existing, list):
                existing.append(str(_coerce_scalar(stripped[2:])))
            continue
        if ":" not in stripped:
            current_list_key = None
            continue
        key, raw_value = stripped.split(":", 1)
        key = key.strip()
        value = raw_value.strip()
        if not key:
            current_list_key = None
            continue
        if value == "":
            meta[key] = []
            current_list_key = key
            continue
        meta[key] = _coerce_scalar(value)
        current_list_key = None

    body = "\n".join(lines[end_idx + 1 :]).lstrip("\n")
    return meta, body


def _guess_description(name: str, body: str) -> str:
    heading = ""
    fallback = ""
    for line in body.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if not heading and stripped.startswith("#"):
            heading = stripped.lstrip("#").strip()
            continue
        if stripped.startswith("- ") or stripped.startswith("* "):
            continue
        fallback = stripped
        break
    return fallback or heading or name


def parse_skill_markdown(path: str | Path) -> ParsedSkill:
    skill_path = Path(path)
    text = skill_path.read_text(encoding="utf-8", errors="ignore")
    try:
        meta, body = _parse_frontmatter(text)
    except Exception:
        meta, body = {}, text

    is_agentskills = skill_path.name.lower() == "skill.md"
    skill_root = skill_path.parent if is_agentskills else skill_path.parent
    inferred_name = skill_path.parent.name if is_agentskills else skill_path.stem

    name = str(meta.get("name") or inferred_name).strip() or inferred_name
    description = str(meta.get("description") or _guess_description(name, body)).strip()

    return ParsedSkill(
        name=name,
        description=description,
        content=body,
        triggers=_normalize_list(meta.get("triggers")),
        keywords=_normalize_list(meta.get("keywords")),
        inputs=_normalize_list(meta.get("inputs")),
        category=str(meta.get("category") or "").strip(),
        applies_to=_normalize_list(meta.get("applies_to")) or ["planner"],
        enabled=bool(meta.get("enabled")) if isinstance(meta.get("enabled"), bool) else False,
        max_chars=int(meta.get("max_chars") or 1800),
        source_path=str(skill_path.resolve()),
        format="agentskills" if is_agentskills else "legacy",
        has_scripts=(skill_root / "scripts").is_dir() if is_agentskills else False,
        has_references=(skill_root / "references").is_dir() if is_agentskills else False,
        has_assets=(skill_root / "assets").is_dir() if is_agentskills else False,
        has_mcp=(skill_root / ".mcp.json").is_file() if is_agentskills else False,
        risk_level=str(meta.get("risk_level") or "medium").strip() or "medium",
        import_status=str(meta.get("import_status") or "discovered").strip() or "discovered",
        source_url=str(meta.get("source_url") or "").strip(),
    )
