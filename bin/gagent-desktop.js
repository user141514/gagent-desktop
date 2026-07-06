#!/usr/bin/env node
"use strict";

const fs = require("node:fs");
const http = require("node:http");
const https = require("node:https");
const net = require("node:net");
const path = require("node:path");
const { spawn, spawnSync } = require("node:child_process");

const PACKAGE_ROOT = path.resolve(__dirname, "..");
const PACKAGED_BACKEND = path.join(PACKAGE_ROOT, "backend");
const PACKAGED_PYTHON_RUNTIME = path.join(PACKAGE_ROOT, "python-runtime");
const DEFAULT_HOST = "127.0.0.1";
const DEFAULT_PORT = 8765;

function defaultPythonCommand(env = process.env, platform = process.platform) {
  if (env.GAGENT_PYTHON) {
    return env.GAGENT_PYTHON;
  }
  return platform === "win32" ? "python" : "python3";
}

function parseArgs(argv) {
  const args = {
    repo: "",
    python: defaultPythonCommand(),
    host: process.env.GA_REACT_API_HOST || DEFAULT_HOST,
    port: Number(process.env.GA_REACT_API_PORT || DEFAULT_PORT),
    dryRun: false,
    json: false,
    noApi: false,
    noSetup: false,
    setup: false,
    help: false,
    version: false,
    update: false,
  };

  const rest = [...argv];
  if (rest[0] === "setup") {
    args.setup = true;
    rest.shift();
  } else if (rest[0] === "update") {
    args.update = true;
    rest.shift();
  }

  for (let index = 0; index < rest.length; index += 1) {
    const item = rest[index];
    if (item === "--repo") args.repo = String(rest[++index] || "");
    else if (item === "--python") args.python = String(rest[++index] || "");
    else if (item === "--host") args.host = String(rest[++index] || DEFAULT_HOST);
    else if (item === "--port") args.port = Number(rest[++index] || DEFAULT_PORT);
    else if (item === "--dry-run") args.dryRun = true;
    else if (item === "--json") args.json = true;
    else if (item === "--no-api") args.noApi = true;
    else if (item === "--no-setup") args.noSetup = true;
    else if (item === "--version" || item === "-v") args.version = true;
    else if (item === "--update" || item === "-U") args.update = true;
    else if (item === "--help" || item === "-h") args.help = true;
    else fail(`Unknown argument: ${item}`);
  }
  return args;
}

function usage() {
  return [
    "Usage: gagent-desktop [setup|update] [options]",
    "",
    "Commands:",
    "  setup             Create/update the bundled backend Python environment and exit.",
    "  update            Check npm for a newer version and self-update.",
    "",
    "Options:",
    "  --repo <path>     Optional external GAgent-Multi checkout. Defaults to packaged backend.",
    "  --python <path>   Python executable for setup. Defaults to GAGENT_PYTHON or python.",
    "  --host <host>     API host. Default: 127.0.0.1.",
    "  --port <port>     API port. Default: 8765.",
    "  --no-api          Do not start backend; require an existing healthy API.",
    "  --no-setup        Do not auto-create the bundled backend Python environment.",
    "  --dry-run         Print planned launch configuration and exit.",
    "  --json            Print dry-run output as JSON.",
    "  -v, --version     Print the installed gagent-desktop version.",
    "  -U, --update      Check npm for newer version and self-update.",
    "  -h, --help        Show this help.",
  ].join("\n");
}

function packageVersion() {
  try {
    const manifest = JSON.parse(fs.readFileSync(path.join(PACKAGE_ROOT, "package.json"), "utf8"));
    return String(manifest.version || "unknown");
  } catch {
    return "unknown";
  }
}

function findRepoRoot(explicitRepo) {
  const candidates = [explicitRepo, process.env.GAGENT_HOME, PACKAGED_BACKEND, process.cwd()].filter(Boolean);

  for (const candidate of candidates) {
    const resolved = path.resolve(candidate);
    if (isGAgentRepo(resolved)) {
      return resolved;
    }
  }
  return "";
}

function isGAgentRepo(repo) {
  return fs.existsSync(path.join(repo, "core", "api", "server.py"));
}

function commandExists(command) {
  const result = spawnSync(command, ["--version"], {
    stdio: "ignore",
    shell: false,
  });
  return !result.error && result.status === 0;
}

function setupPythonCandidates(requestedPython, platform = process.platform) {
  const candidates = [requestedPython];
  if (platform === "win32") {
    candidates.push("py", "python");
  } else {
    candidates.push("python3", "python");
  }
  return [...new Set(candidates.filter(Boolean))];
}

function resolveSetupPython(requestedPython, platform = process.platform) {
  for (const candidate of setupPythonCandidates(requestedPython, platform)) {
    if (commandExists(candidate)) {
      return candidate;
    }
  }
  return requestedPython;
}

function buildConfig(args) {
  const repo = findRepoRoot(args.repo);
  const packagedBackend = isGAgentRepo(PACKAGED_BACKEND);
  const usesPackagedBackend = Boolean(repo) && path.resolve(repo) === path.resolve(PACKAGED_BACKEND);
  const venvDir = path.join(getStateDir(), "python-env");
  const venvPython = resolveVenvPython(venvDir);
  const embeddedPython = resolveEmbeddedPython(PACKAGED_PYTHON_RUNTIME);
  const hasEmbeddedPython = fs.existsSync(embeddedPython);
  const hasPythonEnv = fs.existsSync(venvPython);
  const setupPython = resolveSetupPython(args.python);
  const python = usesPackagedBackend && hasEmbeddedPython
    ? embeddedPython
    : usesPackagedBackend && hasPythonEnv
      ? venvPython
      : setupPython;
  const apiUrl = `http://${args.host}:${args.port}`;
  const requirements = repo ? resolveRequirementsFile(repo) : "";
  return {
    packageRoot: PACKAGE_ROOT,
    repo,
    repoSource: args.repo ? "arg" : process.env.GAGENT_HOME ? "env" : usesPackagedBackend ? "packaged" : repo ? "auto" : "missing",
    packagedBackend,
    usesPackagedBackend,
    python,
    setupPython,
    setupPythonCandidates: setupPythonCandidates(args.python),
    embeddedPython,
    hasEmbeddedPython,
    venvDir,
    venvPython,
    requirements,
    apiHost: args.host,
    apiPort: args.port,
    apiUrl,
    noApi: args.noApi,
    noSetup: args.noSetup,
    dist: path.join(PACKAGE_ROOT, "dist"),
    electronMain: path.join(PACKAGE_ROOT, "electron", "main.cjs"),
  };
}

function resolveRequirementsFile(repo) {
  const desktopRequirements = path.join(repo, "requirements-desktop.txt");
  if (fs.existsSync(desktopRequirements)) {
    return desktopRequirements;
  }
  return path.join(repo, "requirements.txt");
}

function dryRunOutput(config, json) {
  const payload = {
    ok: Boolean(config.repo) && fs.existsSync(path.join(config.dist, "index.html")),
    packageRoot: config.packageRoot,
    repo: config.repo,
    repoSource: config.repoSource,
    python: config.python,
    setupPython: config.setupPython,
    setupPythonCandidates: config.setupPythonCandidates,
    apiUrl: config.apiUrl,
    noApi: config.noApi,
    dist: config.dist,
    electronMain: config.electronMain,
    hasReactDist: fs.existsSync(path.join(config.dist, "index.html")),
    hasBackend: Boolean(config.repo),
    packagedBackend: config.packagedBackend,
    usesPackagedBackend: config.usesPackagedBackend,
    embeddedPython: config.embeddedPython,
    hasEmbeddedPython: config.hasEmbeddedPython,
    venvDir: config.venvDir,
    venvPython: config.venvPython,
    hasPythonEnv: fs.existsSync(config.venvPython),
    requirements: config.requirements,
  };
  if (json) {
    console.log(JSON.stringify(payload, null, 2));
  } else {
    for (const [key, value] of Object.entries(payload)) {
      console.log(`${key}: ${value}`);
    }
  }
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  if (args.help) {
    console.log(usage());
    return 0;
  }
  if (args.version) {
    console.log(packageVersion());
    return 0;
  }

  if (args.update) {
    return await updateSelf();
  }

  const config = buildConfig(args);
  if (args.dryRun) {
    dryRunOutput(config, args.json);
    return config.repo && fs.existsSync(path.join(config.dist, "index.html")) ? 0 : 1;
  }

  if (!config.repo) {
    fail("Packaged backend is missing. Reinstall gagent-desktop or pass --repo to a GAgent-Multi checkout.");
  }
  if (!fs.existsSync(path.join(config.dist, "index.html"))) {
    fail("Packaged React dist is missing. Prepare the npm package before launching.");
  }

  if (args.setup) {
    await ensurePythonEnvironment(config, { force: true });
    return 0;
  }

  let backendProcess = null;
  const healthy = await isApiHealthy(config.apiUrl);
  if (!healthy) {
    if (args.noApi) {
      fail(`No healthy API at ${config.apiUrl}, and --no-api was set.`);
    }
    await ensurePythonEnvironment(config, { force: false });
    // After venv creation, prefer it only when no embedded runtime is available.
    // The embedded runtime is the npm package's self-contained path; a stale user
    // venv may have been created by Anaconda/system Python and miss dependencies.
    if (!config.hasEmbeddedPython && fs.existsSync(config.venvPython)) {
      config.python = config.venvPython;
    }
    const busy = await isPortBusy(config.host, config.port);
    if (busy) {
      fail(`Port ${config.port} is occupied, but ${config.apiUrl}/api/status is not healthy.`);
    }
    backendProcess = startBackend(config);
    try {
      await waitForApi(config.apiUrl, 30_000);
    } catch (error) {
      backendProcess.kill();
      throw error;
    }
  }

  try {
    return await launchElectron(config);
  } finally {
    if (backendProcess) {
      backendProcess.kill();
    }
  }
}

function compareVersions(a, b) {
  const pa = String(a || "0.0.0").split(".").map(Number);
  const pb = String(b || "0.0.0").split(".").map(Number);
  for (let i = 0; i < 3; i += 1) {
    const diff = (pa[i] || 0) - (pb[i] || 0);
    if (diff !== 0) return diff;
  }
  return 0;
}

async function updateSelf(options = {}) {
  const current = options.currentVersion || packageVersion();
  const npmName = options.packageName || "gagent-desktop";
  const logger = options.logger || console;
  const latestVersionFetcher = options.fetchLatestVersion || fetchLatestVersion;
  const installer = options.runInstall || runInstallCommand;

  logger.log(`gagent-desktop ${current} - checking for updates...`);

  const latest = await latestVersionFetcher(npmName);
  if (!latest) {
    logger.log("Could not reach npm registry. Try again later.");
    return 1;
  }

  if (current === latest) {
    logger.log(`Already up to date (v${current}).`);
    return 0;
  }

  // Don't downgrade if current is newer than npm registry
  if (compareVersions(current, latest) >= 0) {
    logger.log(`Already up to date (v${current}). Remote is v${latest}.`);
    return 0;
  }

  logger.log(`Update available: v${current} -> v${latest}`);
  logger.log(`Running: npm install -g ${npmName}@latest ...`);

  const npmCommand = options.npmCommand || (process.platform === "win32" ? "npm.cmd" : "npm");
  const result = installer(npmCommand, ["install", "-g", `${npmName}@latest`]);

  if (result.status !== 0) {
    logger.error(`Update failed (exit ${result.status}). Try manually: npm install -g ${npmName}@latest`);
    return 1;
  }

  logger.log(`Updated to v${latest}. Restart gagent-desktop to use the new version.`);
  return 0;
}

function quoteWindowsCommandArg(value) {
  return `"${String(value).replace(/"/g, '\\"')}"`;
}

function runInstallCommand(command, args, options = {}) {
  if (process.platform === "win32" && /\.(?:cmd|bat)$/i.test(command)) {
    return spawnSync(command, args, {
      stdio: "inherit",
      shell: true,
      ...options,
    });
  }
  return spawnSync(command, args, {
    stdio: "inherit",
    shell: false,
    ...options,
  });
}

function platformDependencyHint(platform = process.platform) {
  if (platform !== "linux") {
    return "";
  }
  return "Linux setup requires Python 3 with venv/pip plus the standard Electron desktop runtime libraries. See the Linux section in the package README.";
}

function fetchLatestVersion(packageName) {
  const url = `https://registry.npmjs.org/${encodeURIComponent(packageName)}/latest`;

  return new Promise((resolve) => {
    const request = https.get(url, { timeout: 10000 }, (response) => {
      if (response.statusCode !== 200) {
        response.resume();
        resolve(null);
        return;
      }
      let body = "";
      response.on("data", (chunk) => { body += chunk; });
      response.on("end", () => {
        try {
          const data = JSON.parse(body);
          resolve(String(data.version || ""));
        } catch {
          resolve(null);
        }
      });
    });
    request.on("timeout", () => { request.destroy(); resolve(null); });
    request.on("error", () => resolve(null));
  });
}

async function ensurePythonEnvironment(config, { force }) {
  if (!config.usesPackagedBackend || config.noSetup) {
    return;
  }
  if (config.hasEmbeddedPython) {
    return;
  }
  if (!force && fs.existsSync(config.venvPython)) {
    return;
  }
  if (!fs.existsSync(config.requirements)) {
    fail(`Bundled backend requirements are missing: ${config.requirements}`);
  }
  if (!commandExists(config.setupPython)) {
    const hint = platformDependencyHint();
    fail(`Python executable is unavailable: ${config.setupPython}${hint ? `\n${hint}` : ""}`);
  }
  fs.mkdirSync(config.venvDir, { recursive: true });
  if (!fs.existsSync(config.venvPython)) {
    try {
      await runCommand(config.setupPython, ["-m", "venv", config.venvDir], {
        cwd: config.repo,
        label: "create Python environment",
      });
    } catch (error) {
      const hint = platformDependencyHint();
      throw new Error(`${error.message}${hint ? `\n${hint}` : ""}`);
    }
  }
  await runCommand(config.venvPython, ["-m", "pip", "install", "--upgrade", "pip"], {
    cwd: config.repo,
    label: "upgrade pip",
  });
  await runCommand(config.venvPython, ["-m", "pip", "install", "-r", config.requirements], {
    cwd: config.repo,
    label: "install backend requirements",
  });
}

function startBackend(config) {
  const child = spawn(
    config.python,
    ["-m", "core.api.server", "--host", config.apiHost, "--port", String(config.apiPort)],
    {
      cwd: config.repo,
      stdio: "inherit",
      env: {
        ...process.env,
        GA_REACT_API_HOST: config.apiHost,
        GA_REACT_API_PORT: String(config.apiPort),
      },
    },
  );
  child.on("error", (error) => {
    fail(`Failed to start backend: ${error.message}`);
  });
  return child;
}

function electronBinaryCandidates(electronDir = path.join(PACKAGE_ROOT, "node_modules", "electron")) {
  if (process.platform === "win32") {
    return [
      path.join(electronDir, "dist", "electron.exe"),
      path.join(electronDir, "dist", "Electron.exe"),
    ];
  }
  if (process.platform === "darwin") {
    return [path.join(electronDir, "dist", "Electron.app", "Contents", "MacOS", "Electron")];
  }
  return [path.join(electronDir, "dist", "electron")];
}

function hasElectronBinary(electronDir = path.join(PACKAGE_ROOT, "node_modules", "electron")) {
  return electronBinaryCandidates(electronDir).some((candidate) => fs.existsSync(candidate));
}

function ensureElectronBinary(options = {}) {
  const electronDir = options.electronDir || path.join(PACKAGE_ROOT, "node_modules", "electron");
  const installScript = path.join(electronDir, "install.js");
  const logger = options.logger || console;
  const runner = options.runner || spawnSync;
  if (hasElectronBinary(electronDir)) {
    return true;
  }
  if (!fs.existsSync(installScript)) {
    throw new Error(`Electron install script is missing: ${installScript}`);
  }

  const mirrors = [];
  if (process.env.ELECTRON_MIRROR) mirrors.push(process.env.ELECTRON_MIRROR);
  mirrors.push("https://npmmirror.com/mirrors/electron/", "");

  for (const mirror of [...new Set(mirrors)]) {
    logger.log(mirror ? `Installing Electron binary via ${mirror} ...` : "Installing Electron binary via default source ...");
    const env = { ...process.env };
    if (mirror) env.ELECTRON_MIRROR = mirror;
    else delete env.ELECTRON_MIRROR;
    const result = runner(process.execPath, [installScript], {
      cwd: electronDir,
      stdio: "inherit",
      shell: false,
      env,
    });
    if (result.status === 0 && hasElectronBinary(electronDir)) {
      return true;
    }
  }
  const hint = platformDependencyHint();
  throw new Error(
    "Electron binary is missing and automatic installation failed. Try manually from the package directory: "
    + "node node_modules/electron/install.js"
    + (hint ? `\n${hint}` : "")
  );
}

function launchElectron(config) {
  ensureElectronBinary();
  const electronPath = require("electron");
  const child = spawn(electronPath, [config.packageRoot], {
    stdio: "inherit",
    env: {
      ...process.env,
      GA_REACT_API_HOST: config.apiHost,
      GA_REACT_API_PORT: String(config.apiPort),
    },
  });
  return new Promise((resolve, reject) => {
    child.on("error", reject);
    child.on("exit", (code) => resolve(code || 0));
  });
}

function runCommand(command, args, { cwd, label }) {
  return new Promise((resolve, reject) => {
    const child = spawn(command, args, { cwd, stdio: "inherit", env: process.env });
    child.on("error", (error) => reject(new Error(`Failed to ${label}: ${error.message}`)));
    child.on("exit", (code) => {
      if (code === 0) resolve();
      else reject(new Error(`Failed to ${label}: exit code ${code}`));
    });
  });
}

function getStateDir() {
  if (process.env.GAGENT_DESKTOP_STATE_DIR) {
    return path.resolve(process.env.GAGENT_DESKTOP_STATE_DIR);
  }
  const home = process.env.USERPROFILE || process.env.HOME || process.cwd();
  return path.join(home, ".gagent-desktop");
}

function resolveVenvPython(venvDir) {
  return process.platform === "win32"
    ? path.join(venvDir, "Scripts", "python.exe")
    : path.join(venvDir, "bin", "python");
}

function resolveEmbeddedPython(runtimeDir) {
  return process.platform === "win32"
    ? path.join(runtimeDir, "python.exe")
    : path.join(runtimeDir, "bin", "python");
}

function isApiHealthy(apiUrl) {
  return Promise.all([
    httpStatusOk(`${apiUrl}/api/status`),
    httpStatusOk(`${apiUrl}/api/llm-config`),
  ]).then(([statusOk, configOk]) => statusOk && configOk);
}

function httpStatusOk(url) {
  return new Promise((resolve) => {
    const request = http.get(url, { timeout: 1500 }, (response) => {
      response.resume();
      resolve(response.statusCode === 200);
    });
    request.on("timeout", () => {
      request.destroy();
      resolve(false);
    });
    request.on("error", () => resolve(false));
  });
}

function waitForApi(apiUrl, timeoutMs) {
  const started = Date.now();
  return new Promise((resolve, reject) => {
    const tick = async () => {
      if (await isApiHealthy(apiUrl)) {
        resolve();
        return;
      }
      if (Date.now() - started > timeoutMs) {
        reject(new Error(`Timed out waiting for ${apiUrl}/api/status`));
        return;
      }
      setTimeout(tick, 500);
    };
    tick();
  });
}

function isPortBusy(host, port) {
  return new Promise((resolve) => {
    const server = net.createServer();
    server.once("error", () => resolve(true));
    server.once("listening", () => {
      server.close(() => resolve(false));
    });
    server.listen(port, host);
  });
}

function fail(message) {
  console.error(`[gagent-desktop] ${message}`);
  process.exit(1);
}

if (require.main === module) {
  main()
    .then((code) => {
      process.exitCode = code;
    })
    .catch((error) => {
      fail(error && error.message ? error.message : String(error));
    });
}

module.exports = {
  compareVersions,
  defaultPythonCommand,
  fetchLatestVersion,
  parseArgs,
  electronBinaryCandidates,
  ensureElectronBinary,
  hasElectronBinary,
  platformDependencyHint,
  resolveSetupPython,
  runInstallCommand,
  setupPythonCandidates,
  updateSelf,
};
