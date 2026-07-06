#!/usr/bin/env node
"use strict";

const fs = require("node:fs");
const path = require("node:path");
const { spawnSync } = require("node:child_process");

const ROOT = path.resolve(__dirname, "..");

function pythonBin() {
  const embedded = process.platform === "win32"
    ? path.join(ROOT, "python-runtime", "python.exe")
    : path.join(ROOT, "python-runtime", "bin", "python");
  return fs.existsSync(embedded) ? embedded : "python";
}

function validateToolRegistry(options = {}) {
  const args = ["backend/tool_registry/validate_tool_registry.py"];
  if (options.quiet) args.push("--quiet");
  const result = spawnSync(pythonBin(), args, {
    cwd: ROOT,
    encoding: "utf8",
    shell: false,
  });
  if (result.status !== 0) {
    throw new Error((result.stderr || result.stdout || "tool registry validation failed").trim());
  }
  if (!options.quiet && result.stdout) process.stdout.write(result.stdout);
  return { ok: true };
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
