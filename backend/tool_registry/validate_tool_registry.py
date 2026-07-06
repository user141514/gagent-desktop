#!/usr/bin/env python
"""Minimal registry lint for Layer 1 tool contracts."""

import argparse
import json
import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
TOOLS_DIR = ROOT / "backend" / "tool_registry" / "tools"
RUNTIME_FALLBACK_POLICY = ROOT / "backend" / "tool_registry" / "policies" / "runtime_fallback.yml"
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


def input_names(data):
    names = []
    for item in as_list(data.get("inputs")):
        name = item.split(":", 1)[0].strip()
        if name and name != "none":
            names.append(name)
    return sorted(names)


def parameter_names(schema, name):
    tool = schema_tool(schema, name)
    return sorted((tool.get("parameters", {}).get("properties") or {}).keys())


def fallback_points_to_web_scan(item):
    text = item.lower()
    if "web_scan" not in text:
        return False
    if re.search(r"\b(do not|don't|must not|never|forbid|forbidden)\b", text):
        return False
    return True


def validate():
    errors = []
    registries = {}
    en_schema = read_schema("backend/assets/tools_schema.json")
    cn_schema = read_schema("backend/assets/tools_schema_cn.json")
    en_names = schema_names(en_schema)
    cn_names = schema_names(cn_schema)
    required_tools = en_names | cn_names

    if en_names != cn_names:
        errors.append("EN/CN schema tool names differ: EN=%s CN=%s" % (sorted(en_names), sorted(cn_names)))

    for name in sorted(required_tools):
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
        expected_params = parameter_names(en_schema, name)
        actual_inputs = input_names(data)
        if actual_inputs != expected_params:
            errors.append(
                "%s: inputs %s must match schema params %s"
                % (path.relative_to(ROOT), actual_inputs, expected_params)
            )
        if parameter_names(cn_schema, name) != expected_params:
            errors.append("%s: EN/CN schema params differ" % name)
        for source in as_list(data.get("source_files")):
            source_path = ROOT / source.split(":", 1)[0]
            if not source_path.exists():
                errors.append("%s: source file missing: %s" % (name, source))
        for artifact in as_list(data.get("generated_artifacts")):
            artifact_path = ROOT / artifact.split(":", 1)[0]
            if not artifact_path.exists():
                errors.append("%s: generated artifact missing: %s" % (name, artifact))

    for name in required_tools:
        if name not in en_names:
            errors.append("tools_schema.json missing %s" % name)
        if name not in cn_names:
            errors.append("tools_schema_cn.json missing %s" % name)
        if name not in registries:
            errors.append("registry missing schema tool %s" % name)

    for schema_name in sorted(en_names | cn_names):
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

    if not RUNTIME_FALLBACK_POLICY.exists():
        errors.append("backend/tool_registry/policies/runtime_fallback.yml is missing")
    else:
        policy = parse_simple_yaml(RUNTIME_FALLBACK_POLICY)
        rules = as_list(policy.get("rules"))
        policy_text = "\n".join(rules).lower()
        if "web_search" not in policy_text or "web_scan" not in policy_text:
            errors.append("runtime fallback policy must mention web_search/web_scan boundary")
        for rule in rules:
            if "web_search" in rule.lower() and fallback_points_to_web_scan(rule):
                errors.append("runtime fallback policy must not point web_search to web_scan: %s" % rule)

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
