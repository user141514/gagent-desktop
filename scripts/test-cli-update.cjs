#!/usr/bin/env node
"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const { ensureElectronBinary, parseArgs, runInstallCommand, updateSelf } = require("../bin/gagent-desktop.js");

async function testParseUpdateCommand() {
  assert.equal(parseArgs(["update"]).update, true);
  assert.equal(parseArgs(["--update"]).update, true);
  assert.equal(parseArgs(["-U"]).update, true);
}

async function testSkipsWhenCurrentIsLatest() {
  const installs = [];
  const logs = [];
  const code = await updateSelf({
    currentVersion: "1.2.3",
    fetchLatestVersion: async () => "1.2.3",
    runInstall: (command, args) => {
      installs.push([command, args]);
      return { status: 0 };
    },
    logger: { log: (line) => logs.push(line), error: (line) => logs.push(line) },
  });

  assert.equal(code, 0);
  assert.deepEqual(installs, []);
  assert.ok(logs.some((line) => line.includes("Already up to date")));
}

async function testInstallsLatestWhenNewerVersionExists() {
  const installs = [];
  const code = await updateSelf({
    currentVersion: "1.2.3",
    fetchLatestVersion: async () => "1.2.4",
    runInstall: (command, args) => {
      installs.push([command, args]);
      return { status: 0 };
    },
    logger: { log: () => undefined, error: () => undefined },
  });

  assert.equal(code, 0);
  assert.equal(installs.length, 1);
  assert.match(installs[0][0], /^npm(\.cmd)?$/);
  assert.deepEqual(installs[0][1], ["install", "-g", "gagent-desktop@latest"]);
}

async function testDefaultInstallerHandlesExecutablePathsWithSpaces() {
  const result = runInstallCommand(process.execPath, ["-e", "process.exit(0)"], {
    stdio: "pipe",
  });
  assert.equal(result.status, 0, result.stderr ? String(result.stderr) : "");

  if (process.platform === "win32") {
    const cmdResult = runInstallCommand("npm.cmd", ["--version"], {
      stdio: "pipe",
    });
    assert.equal(cmdResult.status, 0, cmdResult.stderr ? String(cmdResult.stderr) : "");
  }
}

async function testEnsuresElectronBinaryWithMirrorFallback() {
  const calls = [];
  const electronDir = fs.mkdtempSync(path.join(os.tmpdir(), "gagent-electron-test-"));
  fs.writeFileSync(path.join(electronDir, "install.js"), "// fake installer\n");
  const oldMirror = process.env.ELECTRON_MIRROR;
  delete process.env.ELECTRON_MIRROR;
  try {
    const ok = ensureElectronBinary({
      electronDir,
      logger: { log: () => undefined },
      runner: (command, args, options) => {
        calls.push({ command, args, mirror: options.env.ELECTRON_MIRROR || "" });
        if (options.env.ELECTRON_MIRROR === "https://npmmirror.com/mirrors/electron/") {
          const dist = path.join(electronDir, "dist");
          fs.mkdirSync(dist, { recursive: true });
          fs.writeFileSync(path.join(dist, process.platform === "win32" ? "electron.exe" : "electron"), "fake");
          return { status: 0 };
        }
        return { status: 1 };
      },
    });
    assert.equal(ok, true);
    assert.ok(calls.some((call) => call.mirror === "https://npmmirror.com/mirrors/electron/"));
  } finally {
    fs.rmSync(electronDir, { recursive: true, force: true });
    if (oldMirror === undefined) delete process.env.ELECTRON_MIRROR;
    else process.env.ELECTRON_MIRROR = oldMirror;
  }
}

async function testReturnsFailureWhenInstallFails() {
  const errors = [];
  const code = await updateSelf({
    currentVersion: "1.2.3",
    fetchLatestVersion: async () => "1.2.4",
    runInstall: () => ({ status: 7 }),
    logger: { log: () => undefined, error: (line) => errors.push(line) },
  });

  assert.equal(code, 1);
  assert.ok(errors.some((line) => line.includes("Update failed")));
}

async function main() {
  await testParseUpdateCommand();
  await testSkipsWhenCurrentIsLatest();
  await testInstallsLatestWhenNewerVersionExists();
  await testDefaultInstallerHandlesExecutablePathsWithSpaces();
  await testEnsuresElectronBinaryWithMirrorFallback();
  await testReturnsFailureWhenInstallFails();
  console.log("[test-cli-update] ok");
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
