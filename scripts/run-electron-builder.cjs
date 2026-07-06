#!/usr/bin/env node
"use strict";

const fs = require("node:fs");
const path = require("node:path");
const { spawnSync } = require("node:child_process");

const packageRoot = path.resolve(__dirname, "..");
const packageJsonPath = path.join(packageRoot, "package.json");
const builderBin = path.join(
  packageRoot,
  "node_modules",
  ".bin",
  process.platform === "win32" ? "electron-builder.cmd" : "electron-builder",
);

function withBuilderManifest(callback) {
  const originalText = fs.readFileSync(packageJsonPath, "utf8");
  const manifest = JSON.parse(originalText);
  let restored = false;
  const restoreManifest = () => {
    if (restored) {
      return;
    }
    fs.writeFileSync(packageJsonPath, originalText, "utf8");
    restored = true;
  };
  const handleSignal = (signal) => {
    restoreManifest();
    const exitCode = signal === "SIGINT" ? 130 : 143;
    process.exit(exitCode);
  };
  const handleUncaughtException = (error) => {
    restoreManifest();
    throw error;
  };
  process.once("exit", restoreManifest);
  process.once("SIGINT", handleSignal);
  process.once("SIGTERM", handleSignal);
  process.once("uncaughtException", handleUncaughtException);
  manifest.devDependencies = manifest.devDependencies || {};
  if (manifest.dependencies && manifest.dependencies.electron) {
    manifest.devDependencies.electron = manifest.devDependencies.electron || manifest.dependencies.electron;
    delete manifest.dependencies.electron;
    if (Object.keys(manifest.dependencies).length === 0) {
      delete manifest.dependencies;
    }
  }
  fs.writeFileSync(packageJsonPath, `${JSON.stringify(manifest, null, 2)}\n`, "utf8");
  try {
    return callback();
  } finally {
    process.removeListener("exit", restoreManifest);
    process.removeListener("SIGINT", handleSignal);
    process.removeListener("SIGTERM", handleSignal);
    process.removeListener("uncaughtException", handleUncaughtException);
    restoreManifest();
  }
}

if (!fs.existsSync(builderBin)) {
  console.error(`[gagent-desktop] electron-builder is not installed at ${builderBin}`);
  process.exit(1);
}

const status = withBuilderManifest(() => {
  const env = {
    ...process.env,
    ELECTRON_MIRROR: process.env.ELECTRON_MIRROR || "https://npmmirror.com/mirrors/electron/",
    ELECTRON_BUILDER_BINARIES_MIRROR:
      process.env.ELECTRON_BUILDER_BINARIES_MIRROR || "https://npmmirror.com/mirrors/electron-builder-binaries/",
  };
  const result = spawnSync(builderBin, process.argv.slice(2), {
    cwd: packageRoot,
    stdio: "inherit",
    shell: process.platform === "win32",
    env,
  });
  if (result.error) {
    console.error(`[gagent-desktop] Failed to run electron-builder: ${result.error.message}`);
    return 1;
  }
  return result.status || 0;
});

process.exit(status);
