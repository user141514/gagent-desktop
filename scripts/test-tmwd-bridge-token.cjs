#!/usr/bin/env node
"use strict";

const fs = require("node:fs");
const path = require("node:path");

const root = path.resolve(__dirname, "..");
const read = (relativePath) => fs.readFileSync(path.join(root, relativePath), "utf8");
const fail = (message) => {
  console.error(`[test-tmwd-bridge-token] ${message}`);
  process.exitCode = 1;
};
const mustContain = (text, needle, label) => {
  if (!text.includes(needle)) fail(`${label} is missing ${needle}`);
};
const mustNotContain = (text, needle, label) => {
  if (text.includes(needle)) fail(`${label} still contains ${needle}`);
};

const manifest = JSON.parse(read("backend/assets/tmwd_cdp_bridge/manifest.json"));
const permissions = new Set(manifest.permissions || []);
if (permissions.has("management")) fail("extension must not request management permission");
if (permissions.has("declarativeNetRequest")) fail("extension must not request declarativeNetRequest permission");

const background = read("backend/assets/tmwd_cdp_bridge/background.js");
mustContain(background, "bridge_token.json", "background.js");
mustContain(background, "token: bridgeToken", "background.js");
mustContain(background, "data.token !== bridgeToken", "background.js");
mustNotContain(background, "updateDynamicRules", "background.js");

const driver = read("backend/core/TMWebDriver.py");
mustContain(driver, "secrets.token_urlsafe", "TMWebDriver.py");
mustContain(driver, "hmac.compare_digest", "TMWebDriver.py");
mustContain(driver, "X-TMWD-Token", "TMWebDriver.py");

const pkg = JSON.parse(read("package.json"));
const files = pkg.files || [];
if (!files.includes("!backend/assets/tmwd_cdp_bridge/bridge_token.json")) {
  fail("package.json must exclude the generated bridge token");
}

if (!process.exitCode) console.log("[test-tmwd-bridge-token] ok");
