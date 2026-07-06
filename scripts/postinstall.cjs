#!/usr/bin/env node
"use strict";

const platform = process.platform;
const lines = [
  "",
  "  gagent-desktop installed.",
  "  First run: gagent-desktop setup",
  "  Start app: gagent-desktop",
];

if (platform === "linux") {
  lines.push(
    "",
    "  Linux prerequisites:",
    "  - Node.js 20 or newer",
    "  - Python 3 with venv and pip support",
    "  - Electron desktop runtime libraries such as GTK, NSS, sound, DRM and GBM",
    "  The package prepares its backend environment on first setup or run."
  );
} else if (platform === "win32") {
  lines.push(
    "",
    "  Windows builds prefer the packaged python-runtime when present.",
    "  Use --python to point at a custom Python executable when needed."
  );
} else {
  lines.push(
    "",
    "  This platform requires a local Python 3 with venv and pip support."
  );
}

console.log(lines.join("\n") + "\n");
