#!/usr/bin/env node
"use strict";

const assert = require("node:assert/strict");
const { spawnSync } = require("node:child_process");

if (process.platform !== "win32") {
  console.log("[test-cli-update-cmd] skipped on non-Windows");
  process.exit(0);
}

function runCmd(command) {
  return spawnSync(process.env.ComSpec || "cmd.exe", ["/d", "/s", "/c", command], {
    cwd: process.cwd(),
    encoding: "utf8",
  });
}

const help = runCmd("node bin\\gagent-desktop.js update --help");
assert.equal(help.status, 0, help.stderr || help.stdout);
assert.match(help.stdout, /Usage: gagent-desktop \[setup\|update\] \[options\]/);
assert.match(help.stdout, /update\s+Check npm for a newer version and self-update/);
assert.match(help.stdout, /--update\s+Check npm for newer version and self-update/);

const simulated = runCmd("node scripts\\test-cli-update.cjs");
assert.equal(simulated.status, 0, simulated.stderr || simulated.stdout);
assert.match(simulated.stdout, /\[test-cli-update\] ok/);

console.log("[test-cli-update-cmd] ok");
