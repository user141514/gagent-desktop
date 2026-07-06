#!/usr/bin/env python
"""Minimal registry lint for Layer 1 web tool contracts."""

import argparse
import json
import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
TOOLS_DIR = ROOT / "backend" / "tool_registry" / "tools"
REQUIRED_TOOLS = {"web_search", "web_scan", "web_execute_js", "browser_agent"}
REQUIRED_FIELDS = [
    "name",
    "layer_owner",
    "purpose",
    "does",
    "does_not_do",
    "inputs",
    "outputs",
    "success_contract",
    "failure_contract",
    "fallback_policy",
    "forbidden_behaviors",
    "smoke_tests",
    "source_files",
    "generated_artifacts",
]


def read_text(relative_path):
    return (ROOT / relative_path).read_text(encoding="utf-8")


def read_schema(relative_path):
    return json.loads(read_text(relative_path))


def schema_names(schema):
    return {str(item.get("function", {}).get("name", "")).strip() for item in schema if item.get("function")}


def schema_tool(schema, name):
    for item in schema:
        if item.get("function", {}).get("name") == name:
            return item["function"]
    return {}


def parse_simple_yaml(path):
    data = {}
    current_key = None
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.rstrip()
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if not raw_line.startswith(" ") and ":" in line:
            key, value = line.split(":", 1)
            current_key = key.strip()
            value = value.strip()
            data[current_key] = value.strip("\"'") if value else []
            continue
        if current_key and stripped.startswith("- "):
            if not isinstance(data.get(current_key), list):
                data[current_key] = []
            data[current_key].append(stripped[2:].strip().strip("\"'"))
    return data


def as_list(value):
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if value:
        return [str(value).strip()]
    return []


def engine_meta(schema, name):
    tool = schema_tool(schema, name)
    return tool.get("parameters", {}).get("properties", {}).get("engine", {})


def fallback_points_to_web_scan(item):
    text = item.lower()
    if "web_scan" not in text:
        return False
    if re.search(r"\b(do not|don't|never|forbid|forbidden)\b", text):
        return False
    return True


def validate():
    errors = []
    registries = {}

    for name in REQUIRED_TOOLS:
        path = TOOLS_DIR / ("%s.yml" % name)
        if not path.exists():
            errors.append("%s is missing" % path.relative_to(ROOT))
            continue
        data = parse_simple_yaml(path)
        registries[name] = data
        for field in REQUIRED_FIELDS:
            if not as_list(data.get(field)):
                errors.append("%s: required field %s is empty or missing" % (path.relative_to(ROOT), field))
        if data.get("name") != name:
            errors.append("%s: name must be %s" % (path.relative_to(ROOT), name))
        if not str(data.get("layer_owner", "")).startswith("Layer "):
            errors.append("%s: layer_owner must name an architecture layer" % path.relative_to(ROOT))
        if not as_list(data.get("does_not_do")):
            errors.append("%s: does_not_do must not be empty" % path.relative_to(ROOT))
        if not as_list(data.get("smoke_tests")):
            errors.append("%s: smoke_tests must not be empty" % path.relative_to(ROOT))

    en_schema = read_schema("backend/assets/tools_schema.json")
    cn_schema = read_schema("backend/assets/tools_schema_cn.json")
    en_names = schema_names(en_schema)
    cn_names = schema_names(cn_schema)

    for name in REQUIRED_TOOLS:
        if name not in en_names:
            errors.append("tools_schema.json missing %s" % name)
        if name not in cn_names:
            errors.append("tools_schema_cn.json missing %s" % name)
        if name not in registries:
            errors.append("registry missing schema web tool %s" % name)

    for schema_name in sorted((en_names | cn_names) & REQUIRED_TOOLS):
        if schema_name not in registries:
            errors.append("schema tool %s has no registry file" % schema_name)

    web_search = registries.get("web_search", {})
    web_search_items = []
    for key in ["does_not_do", "forbidden_behaviors", "fallback_policy"]:
        web_search_items.extend(as_list(web_search.get(key)))
    web_search_text = "\n".join(web_search_items).lower()
    if "baidu" not in web_search_text:
        errors.append("web_search registry must explicitly forbid Baidu")
    for item in as_list(web_search.get("fallback_policy")):
        if fallback_points_to_web_scan(item):
            errors.append("web_search fallback_policy must not point to web_scan: %s" % item)

    en_engine = engine_meta(en_schema, "web_search")
    cn_engine = engine_meta(cn_schema, "web_search")
    if en_engine.get("default") != cn_engine.get("default"):
        errors.append("EN/CN web_search default engine differs")
    if set(en_engine.get("enum", [])) != set(cn_engine.get("enum", [])):
        errors.append("EN/CN web_search engine enum differs")
    if en_engine.get("default") not in set(en_engine.get("enum", [])):
        errors.append("EN web_search default engine is not in enum")
    if cn_engine.get("default") not in set(cn_engine.get("enum", [])):
        errors.append("CN web_search default engine is not in enum")

    return errors


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()

    errors = validate()
    if errors:
        print("[validate_tool_registry] failed", file=sys.stderr)
        for error in errors:
            print("- %s" % error, file=sys.stderr)
        return 1
    if not args.quiet:
        print("[validate_tool_registry] ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
