#!/usr/bin/env node
"use strict";

const assert = require("node:assert/strict");
const {
  defaultPythonCommand,
  platformDependencyHint,
  setupPythonCandidates,
} = require("../bin/gagent-desktop.js");

assert.equal(defaultPythonCommand({}, "linux"), "python3");
assert.equal(defaultPythonCommand({}, "darwin"), "python3");
assert.equal(defaultPythonCommand({}, "win32"), "python");
assert.equal(defaultPythonCommand({ GAGENT_PYTHON: "/custom/python" }, "linux"), "/custom/python");
assert.deepEqual(setupPythonCandidates("python3", "linux"), ["python3", "python"]);
assert.ok(platformDependencyHint("linux").includes("Python 3"));
assert.equal(platformDependencyHint("win32"), "");

console.log("[test-linux-fallback] ok");
