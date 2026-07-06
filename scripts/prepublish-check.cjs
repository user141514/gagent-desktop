#!/usr/bin/env node
"use strict";

const fs = require("node:fs");
const path = require("node:path");
const { spawnSync } = require("node:child_process");
const { validateToolRegistry } = require("./validate-tool-registry.cjs");

const packageRoot = path.resolve(__dirname, "..");
const manifestPath = path.join(packageRoot, "package.json");
const npmBin = process.platform === "win32" ? "npm.cmd" : "npm";
const nodeBin = process.execPath;

function fail(message) {
  console.error(`[prepublish-check] ${message}`);
  process.exitCode = 1;
}

function readJson(filePath) {
  return JSON.parse(fs.readFileSync(filePath, "utf8"));
}

function exists(relativePath) {
  return fs.existsSync(path.join(packageRoot, relativePath));
}

function run(command, args, options = {}) {
  const result = spawnSync(command, args, {
    cwd: packageRoot,
    encoding: "utf8",
    shell: false,
    maxBuffer: 128 * 1024 * 1024,
    ...options,
  });
  if (result.error) {
    throw result.error;
  }
  return result;
}

function runNpm(args) {
  if (process.platform !== "win32") {
    return run(npmBin, args);
  }
  return run(process.env.ComSpec || "cmd.exe", ["/d", "/s", "/c", [npmBin, ...args].join(" ")]);
}

function checkDistAssets() {
  const indexPath = path.join(packageRoot, "dist", "index.html");
  if (!fs.existsSync(indexPath)) {
    fail("dist/index.html is missing. Run the React build and prepare package before publishing.");
    return;
  }

  const html = fs.readFileSync(indexPath, "utf8");
  const refs = [...html.matchAll(/\b(?:src|href)=["']([^"']+)["']/g)].map((match) => match[1]);
  for (const ref of refs) {
    if (/^(?:https?:|data:|app:)/i.test(ref)) {
      continue;
    }
    const normalized = ref.replace(/^\/+/, "");
    const target = path.join(packageRoot, "dist", normalized);
    if (!fs.existsSync(target)) {
      fail(`dist/index.html references a missing asset: ${ref}`);
    }
  }
}

function checkTmwdExtensionAssets() {
  const required = [
    "backend/assets/tmwd_cdp_bridge/manifest.json",
    "backend/assets/tmwd_cdp_bridge/background.js",
    "backend/assets/tmwd_cdp_bridge/config.js",
    "backend/assets/tmwd_cdp_bridge/content.js",
    "backend/assets/tmwd_cdp_bridge/disable_dialogs.js",
    "backend/assets/tmwd_cdp_bridge/popup.html",
    "backend/assets/tmwd_cdp_bridge/popup.js",
  ];
  for (const relativePath of required) {
    if (!exists(relativePath)) {
      fail(`packaged TMWebDriver extension is missing ${relativePath}.`);
    }
  }
  const manifestPath = path.join(packageRoot, "backend", "assets", "tmwd_cdp_bridge", "manifest.json");
  if (fs.existsSync(manifestPath)) {
    try {
      JSON.parse(fs.readFileSync(manifestPath, "utf8"));
    } catch (error) {
      fail(`packaged TMWebDriver extension manifest is invalid JSON: ${error.message}`);
    }
  }
}

function checkDryRun() {
  const result = run(nodeBin, ["bin/gagent-desktop.js", "--dry-run", "--json"]);
  if (result.status !== 0) {
    fail(`gagent-desktop dry-run failed:\n${result.stderr || result.stdout}`);
    return;
  }
  let payload;
  try {
    payload = JSON.parse(result.stdout);
  } catch {
    fail(`dry-run did not print valid JSON:\n${result.stdout}`);
    return;
  }
  if (!payload.ok) {
    fail("dry-run reported ok=false.");
  }
  if (!payload.hasReactDist) {
    fail("dry-run reports missing React dist.");
  }
  if (!payload.hasBackend) {
    fail("dry-run reports missing backend.");
  }
  if (!payload.hasEmbeddedPython) {
    fail("dry-run reports missing embedded Python runtime.");
  }
  if (!String(payload.python || "").includes(`${path.sep}python-runtime${path.sep}`)) {
    fail(`dry-run did not select embedded Python: ${payload.python}`);
  }
}

function checkPackDryRun() {
  const result = runNpm(["pack", "--dry-run", "--json", "--ignore-scripts"]);
  if (result.status !== 0) {
    fail(`npm pack --dry-run failed:\n${result.stderr || result.stdout}`);
    return;
  }
  let pack;
  try {
    pack = JSON.parse(result.stdout)[0];
  } catch {
    fail(`npm pack --dry-run did not print expected JSON:\n${result.stdout}`);
    return;
  }
  const paths = new Set((pack.files || []).map((file) => file.path));
  for (const required of [
    "bin/gagent-desktop.js",
    "electron/main.cjs",
    "dist/index.html",
    "backend/core/api/server.py",
    "backend/assets/tmwd_cdp_bridge/manifest.json",
    "backend/requirements-desktop.txt",
    "python-runtime/python.exe",
  ]) {
    if (!paths.has(required)) {
      fail(`npm pack output is missing ${required}`);
    }
  }
  for (const forbidden of [
    "backend/.env",
    "backend/mykey.py",
    "backend/mykey.json",
    "backend/memory/global_mem.txt",
    "backend/memory/global_mem_insight.txt",
    "backend/memory/history_memory_inbox.md",
  ]) {
    if (paths.has(forbidden)) {
      fail(`npm pack output includes local runtime data: ${forbidden}`);
    }
  }
}

function checkEmbeddedPythonImports() {
  const pythonExe = path.join(packageRoot, "python-runtime", process.platform === "win32" ? "python.exe" : "bin/python");
  if (!fs.existsSync(pythonExe)) {
    fail(`embedded Python executable is missing: ${pythonExe}`);
    return;
  }
  const result = run(pythonExe, ["-c", "import bottle, simple_websocket_server"]);
  if (result.status !== 0) {
    fail(`embedded Python is missing web_search bridge dependencies:\n${result.stderr || result.stdout}`);
  }
}

const manifest = readJson(manifestPath);
if (!manifest.version || manifest.version === "0.0.1") {
  fail(`Invalid package version: ${manifest.version || "(missing)"}`);
}
if (!manifest.files || !manifest.files.includes("python-runtime/**/*")) {
  fail('package.json files must include "python-runtime/**/*".');
}
if (!exists("backend/core/api/server.py")) {
  fail("packaged backend is missing.");
}
if (!exists("python-runtime/python.exe")) {
  fail("embedded Windows Python runtime is missing.");
}
checkDistAssets();
checkTmwdExtensionAssets();
try {
  validateToolRegistry({ quiet: true });
} catch (error) {
  fail(error.message || String(error));
}
checkDryRun();
checkPackDryRun();
checkEmbeddedPythonImports();

if (process.exitCode) {
  process.exit(process.exitCode);
}
console.log(`[prepublish-check] ok for gagent-desktop@${manifest.version}`);
