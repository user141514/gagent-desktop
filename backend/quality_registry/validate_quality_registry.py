#!/usr/bin/env python
"""Minimal lint for quality gate ownership and defaults."""

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
REGISTRY = ROOT / "backend" / "quality_registry" / "gates.yml"
REQUIRED_FIELDS = {
    "name",
    "default_enabled",
    "env_var",
    "trigger",
    "injected_role",
    "max_chars",
    "owner",
    "enforcement_level",
    "source_files",
    "generated_artifacts",
}
ENFORCEMENT_LEVELS = {
    "advisory_context",
    "audit_scoring",
    "blocking_notice",
    "repair",
    "runtime_guard",
}


def parse_docs(path):
    docs = []
    current = {}
    key = None
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.rstrip()
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped == "---":
            if current:
                docs.append(current)
            current = {}
            key = None
            continue
        if not raw_line.startswith(" ") and ":" in line:
            key, value = line.split(":", 1)
            key = key.strip()
            value = value.strip()
            current[key] = value if value else []
            continue
        if key and stripped.startswith("- "):
            if not isinstance(current.get(key), list):
                current[key] = []
            current[key].append(stripped[2:].strip())
    if current:
        docs.append(current)
    return docs


def as_list(value):
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if value:
        return [str(value).strip()]
    return []


def validate():
    errors = []
    if not REGISTRY.exists():
        return ["backend/quality_registry/gates.yml is missing"]

    seen = set()
    for gate in parse_docs(REGISTRY):
        name = str(gate.get("name") or "").strip()
        if not name:
            errors.append("gate missing name")
            continue
        if name in seen:
            errors.append("%s: duplicate gate name" % name)
        seen.add(name)

        for field in REQUIRED_FIELDS:
            if not as_list(gate.get(field)):
                errors.append("%s: required field %s is empty or missing" % (name, field))
        if str(gate.get("default_enabled")) not in {"true", "false"}:
            errors.append("%s: default_enabled must be true or false" % name)
        if str(gate.get("enforcement_level")) not in ENFORCEMENT_LEVELS:
            errors.append("%s: unknown enforcement_level %s" % (name, gate.get("enforcement_level")))
        if str(gate.get("owner")) != "Layer 4 quality gates":
            errors.append("%s: owner must be Layer 4 quality gates" % name)

        env_var = str(gate.get("env_var") or "").strip()
        default_enabled = str(gate.get("default_enabled"))
        for source in as_list(gate.get("source_files")):
            source_path = ROOT / source
            if not source_path.exists():
                errors.append("%s: source file missing: %s" % (name, source))
                continue
            source_text = source_path.read_text(encoding="utf-8", errors="replace")
            if env_var and env_var not in source_text:
                errors.append("%s: env_var %s not found in %s" % (name, env_var, source))
            if default_enabled == "true" and 'os.environ.get(' in source_text and ', "1"' not in source_text:
                errors.append("%s: default_enabled=true but source does not contain a \"1\" env default" % name)
            if default_enabled == "false" and 'os.environ.get(' in source_text and ', "0"' not in source_text and ', "")' not in source_text:
                errors.append("%s: default_enabled=false but source does not contain an off env default" % name)

    if not seen:
        errors.append("no quality gates registered")
    return errors


def main():
    errors = validate()
    if errors:
        print("[validate_quality_registry] failed", file=sys.stderr)
        for error in errors:
            print("- %s" % error, file=sys.stderr)
        return 1
    print("[validate_quality_registry] ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
