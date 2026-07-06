#!/usr/bin/env node
"use strict";

const fs = require("node:fs");
const path = require("node:path");

const ROOT = path.resolve(__dirname, "..");
const TOOL_NAMES = ["web_search", "web_scan", "web_execute_js", "browser_agent"];

function rel(...parts) {
  return path.join(ROOT, ...parts);
}

function read(relativePath) {
  return fs.readFileSync(rel(...relativePath.split("/")), "utf8");
}

function toolName(tool) {
  return String(tool?.function?.name || tool?.name || "").trim();
}

function schemaByName(relativePath) {
  const schema = JSON.parse(read(relativePath));
  return new Map(schema.map((tool) => [toolName(tool), tool]).filter(([name]) => name));
}

function getScalar(text, key) {
  const match = text.match(new RegExp(`^${key}:\\s*(.+)$`, "m"));
  return match ? match[1].trim().replace(/^["']|["']$/g, "") : "";
}

function getList(text, key) {
  const match = text.match(new RegExp(`^${key}:\\s*\\r?\\n((?:  - .+\\r?\\n?)+)`, "m"));
  if (!match) return [];
  return match[1]
    .split(/\r?\n/)
    .map((line) => line.trim().replace(/^- /, "").trim())
    .filter(Boolean);
}

function schemaParams(tool) {
  return Object.keys(tool?.function?.parameters?.properties || {}).sort();
}

function assertSameList(errors, label, actual, expected) {
  const a = [...actual].sort().join(",");
  const e = [...expected].sort().join(",");
  if (a !== e) errors.push(`${label}: expected [${e}], got [${a}]`);
}

function validateToolRegistry(options = {}) {
  const errors = [];
  const enSchema = schemaByName("backend/assets/tools_schema.json");
  const zhSchema = schemaByName("backend/assets/tools_schema_cn.json");
  const ga = read("backend/core/ga.py");
  const browserAgent = read("backend/core/browser_agent.py");
  const sop = read("backend/memory/web_search_tool_sop.md");
  const sysPromptEn = read("backend/assets/sys_prompt_en.txt");
  const sysPromptZh = read("backend/assets/sys_prompt.txt");

  for (const name of TOOL_NAMES) {
    const registryPath = `backend/tool_registry/tools/${name}.yml`;
    if (!fs.existsSync(rel(...registryPath.split("/")))) {
      errors.push(`${registryPath} is missing`);
      continue;
    }

    const registry = read(registryPath);
    const declaredName = getScalar(registry, "name");
    if (declaredName !== name) errors.push(`${registryPath}: name must be ${name}`);

    const params = getList(registry, "parameters");
    if (!params.length) errors.push(`${registryPath}: parameters list is empty`);

    const enTool = enSchema.get(name);
    const zhTool = zhSchema.get(name);
    if (!enTool) errors.push(`English schema missing ${name}`);
    if (!zhTool) errors.push(`Chinese schema missing ${name}`);
    if (enTool && params.length) assertSameList(errors, `${name} English schema params`, schemaParams(enTool), params);
    if (zhTool && params.length) assertSameList(errors, `${name} Chinese schema params`, schemaParams(zhTool), params);
    if (enTool && zhTool) assertSameList(errors, `${name} localized schema params`, schemaParams(zhTool), schemaParams(enTool));

    const handlerName = `do_${name}`;
    if (!ga.includes(`def ${handlerName}(`)) errors.push(`backend/core/ga.py missing handler ${handlerName}`);

    if (name === "browser_agent") {
      if (!browserAgent.includes("def run_browser_agent(")) errors.push("backend/core/browser_agent.py missing run_browser_agent");
    } else if (!ga.includes(`def ${name}(`)) {
      errors.push(`backend/core/ga.py missing implementation ${name}`);
    }

    if (!sop.includes(`\`${name}\``)) errors.push(`web_search_tool_sop.md does not mention ${name}`);
    if (!sysPromptEn.includes(name)) errors.push(`sys_prompt_en.txt does not mention ${name}`);
    if (!sysPromptZh.includes(name)) errors.push(`sys_prompt.txt does not mention ${name}`);
  }

  const webSearchRegistry = fs.existsSync(rel("backend", "tool_registry", "tools", "web_search.yml"))
    ? read("backend/tool_registry/tools/web_search.yml")
    : "";
  const defaultEngine = getScalar(webSearchRegistry, "default_engine");
  const schemaDefault = enSchema.get("web_search")?.function?.parameters?.properties?.engine?.default;
  if (defaultEngine && schemaDefault !== defaultEngine) {
    errors.push(`web_search schema default engine must be ${defaultEngine}, got ${schemaDefault}`);
  }
  if (defaultEngine && !ga.includes(`def web_search(query, engine="${defaultEngine}"`)) {
    errors.push(`web_search implementation default must be ${defaultEngine}`);
  }
  if (defaultEngine && !ga.includes(`args.get("engine", "${defaultEngine}")`)) {
    errors.push(`do_web_search handler default must be ${defaultEngine}`);
  }

  if (!read("backend/memory/architecture_convergence_sop.md").includes("backend/tool_registry/tools/<tool>.yml")) {
    errors.push("architecture_convergence_sop.md must document backend/tool_registry/tools/<tool>.yml");
  }

  if (errors.length) {
    throw new Error(`tool registry validation failed:\n- ${errors.join("\n- ")}`);
  }

  if (!options.quiet) console.log("[validate-tool-registry] ok");
  return { ok: true, tools: TOOL_NAMES };
}

if (require.main === module) {
  try {
    validateToolRegistry();
  } catch (error) {
    console.error(error.message || String(error));
    process.exit(1);
  }
}

module.exports = { validateToolRegistry };
