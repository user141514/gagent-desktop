from __future__ import annotations

import json
from pathlib import Path

from .skill_effects import validate_skill_effects_dict
from .skill_phase import VALID_SKILL_PHASES


_VALID_IMPORT_STATUS = {"imported", "manifest_only", "disabled"}


class SkillManifest:
    def __init__(self, manifest_path: str | Path | None = None) -> None:
        self.manifest_path = Path(manifest_path) if manifest_path is not None else Path(__file__).resolve().parent / "skill_manifest.json"
        self._cache: list[dict] | None = None

    def _repo_root(self) -> Path:
        return self.manifest_path.resolve().parents[2]

    def _resolve_local_file(self, entry: dict) -> Path:
        local_file = str(entry.get("local_file") or "").strip()
        return self._repo_root() / local_file if local_file else self._repo_root()

    def load(self) -> list[dict]:
        if self._cache is not None:
            return [dict(item) for item in self._cache]
        with self.manifest_path.open(encoding="utf-8") as handle:
            data = json.load(handle)
        if not isinstance(data, list):
            raise ValueError("skill_manifest.json must contain a JSON array")
        self._cache = [dict(item) for item in data if isinstance(item, dict)]
        return [dict(item) for item in self._cache]

    def list_all(self) -> list[dict]:
        return self.load()

    def list_enabled(self) -> list[dict]:
        return [item for item in self.load() if bool(item.get("enabled"))]

    def list_imported_enabled(self) -> list[dict]:
        return [
            item
            for item in self.load()
            if bool(item.get("enabled")) and str(item.get("import_status") or "") == "imported"
        ]

    def get(self, name: str) -> dict | None:
        target = str(name or "").strip()
        for item in self.load():
            if str(item.get("name") or "").strip() == target:
                return dict(item)
        return None

    def validate(self) -> list[str]:
        errors: list[str] = []
        for idx, item in enumerate(self.load()):
            prefix = f"entry[{idx}]"
            name = str(item.get("name") or "").strip()
            category = str(item.get("category") or "").strip()
            triggers = item.get("triggers")
            import_status = str(item.get("import_status") or "").strip()
            enabled = item.get("enabled")
            max_chars = item.get("max_chars")
            applies_to = item.get("applies_to")
            effects = item.get("effects")

            if not name:
                errors.append(f"{prefix}: name is required")
            if not category:
                errors.append(f"{prefix}: category is required")
            if not isinstance(triggers, list):
                errors.append(f"{prefix}: triggers must be a list")
            if import_status not in _VALID_IMPORT_STATUS:
                errors.append(f"{prefix}: invalid import_status={import_status!r}")
            if not isinstance(enabled, bool):
                errors.append(f"{prefix}: enabled must be bool")
            if not isinstance(max_chars, int) or max_chars <= 0:
                errors.append(f"{prefix}: max_chars must be a positive integer")
            if not isinstance(applies_to, list) or not applies_to:
                errors.append(f"{prefix}: applies_to must be a non-empty list")
            else:
                invalid_phases = [
                    str(phase)
                    for phase in applies_to
                    if str(phase or "").strip().lower() not in VALID_SKILL_PHASES
                ]
                if invalid_phases:
                    errors.append(f"{prefix}: invalid applies_to phases={invalid_phases!r}")
            for effect_error in validate_skill_effects_dict(effects):
                errors.append(f"{prefix}: {effect_error}")

            if import_status == "imported" and bool(enabled):
                local_file = str(item.get("local_file") or "").strip()
                if not local_file:
                    errors.append(f"{prefix}: imported enabled skill requires local_file")
                elif not self._resolve_local_file(item).exists():
                    errors.append(f"{prefix}: local_file does not exist: {local_file}")
        return errors
