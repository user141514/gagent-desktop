const { app, BrowserWindow, dialog, Menu, net, protocol, shell } = require("electron");
const { spawn } = require("node:child_process");
const fs = require("node:fs");
const http = require("node:http");
const nodeNet = require("node:net");
const path = require("node:path");
const { pathToFileURL } = require("node:url");
const {
  createTextEditingMenuTemplate,
  shouldShowTextEditingMenu,
} = require("./text-context-menu.cjs");

const DEV_URL = process.env.GA_REACT_DESKTOP_URL || "";
const API_HOST = process.env.GA_REACT_API_HOST || "127.0.0.1";
const API_PORT = Number(process.env.GA_REACT_API_PORT || 8765);
const API_URL = `http://${API_HOST}:${API_PORT}`;
const DIST_DIR = path.resolve(__dirname, "..", "dist");
let backendProcess = null;

protocol.registerSchemesAsPrivileged([
  {
    scheme: "app",
    privileges: {
      standard: true,
      secure: true,
      supportFetchAPI: true,
      corsEnabled: true,
    },
  },
]);

function resolveAppAsset(url) {
  const parsed = new URL(url);
  const rawPath = decodeURIComponent(parsed.pathname || "/");
  const requested = rawPath === "/" ? "/index.html" : rawPath;
  const resolved = path.resolve(DIST_DIR, `.${requested}`);
  if (!resolved.startsWith(DIST_DIR)) {
    return path.join(DIST_DIR, "index.html");
  }
  return resolved;
}

function registerAppProtocol() {
  protocol.handle("app", (request) => {
    const fileUrl = pathToFileURL(resolveAppAsset(request.url)).toString();
    return net.fetch(fileUrl);
  });
}

function createWindow() {
  const win = new BrowserWindow({
    title: "GenericAgent",
    width: 1180,
    height: 820,
    minWidth: 860,
    minHeight: 620,
    backgroundColor: "#fffdfa",
    show: false,
    webPreferences: {
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
    },
  });

  win.once("ready-to-show", () => win.show());
  win.webContents.setWindowOpenHandler(({ url }) => {
    shell.openExternal(url);
    return { action: "deny" };
  });
  win.webContents.on("context-menu", (_event, params) => {
    if (!shouldShowTextEditingMenu(params)) return;
    Menu.buildFromTemplate(createTextEditingMenuTemplate(params)).popup({
      window: win,
    });
  });

  if (DEV_URL) {
    win.loadURL(DEV_URL);
  } else {
    win.loadURL("app://./index.html");
  }
}

async function ensureBackendRunning() {
  if (await isApiHealthy(API_URL)) {
    return;
  }

  const backendRoot = resolveBackendRoot();
  if (!backendRoot) {
    throw new Error("Packaged backend is missing. Reinstall GenericAgent or set GAGENT_HOME.");
  }

  if (await isPortBusy(API_HOST, API_PORT)) {
    throw new Error(`Port ${API_PORT} is occupied, but ${API_URL}/api/status is not healthy.`);
  }

  const python = resolvePythonExecutable();
  backendProcess = spawn(
    python,
    ["-m", "core.api.server", "--host", API_HOST, "--port", String(API_PORT)],
    {
      cwd: backendRoot,
      stdio: "ignore",
      windowsHide: true,
      env: {
        ...process.env,
        GA_REACT_API_HOST: API_HOST,
        GA_REACT_API_PORT: String(API_PORT),
      },
    },
  );

  backendProcess.on("exit", () => {
    backendProcess = null;
  });

  await waitForApi(API_URL, 30_000);
}

function resolveBackendRoot() {
  const candidates = [
    process.env.GAGENT_HOME,
    process.env.GAGENT_PACKAGED_BACKEND,
    path.join(resourceRoot(), "backend"),
    path.resolve(__dirname, "..", "backend"),
  ].filter(Boolean);

  for (const candidate of candidates) {
    const resolved = path.resolve(candidate);
    if (fs.existsSync(path.join(resolved, "core", "api", "server.py"))) {
      return resolved;
    }
  }
  return "";
}

function resolvePythonExecutable() {
  const embedded = path.join(resourceRoot(), "python-runtime", "python.exe");
  const embeddedVenv = path.join(resourceRoot(), "python-runtime", "Scripts", "python.exe");
  const localEmbedded = path.resolve(__dirname, "..", "python-runtime", "python.exe");
  const candidates = [embedded, embeddedVenv, localEmbedded, process.env.GAGENT_PYTHON, "python"].filter(Boolean);
  for (const candidate of candidates) {
    if (candidate === "python" || fs.existsSync(candidate)) {
      return candidate;
    }
  }
  return "python";
}

function resourceRoot() {
  return app.isPackaged ? process.resourcesPath : path.resolve(__dirname, "..");
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
    const server = nodeNet.createServer();
    server.once("error", () => resolve(true));
    server.once("listening", () => {
      server.close(() => resolve(false));
    });
    server.listen(port, host);
  });
}

app.whenReady().then(async () => {
  registerAppProtocol();
  try {
    await ensureBackendRunning();
  } catch (error) {
    dialog.showErrorBox("GenericAgent backend failed to start", error && error.message ? error.message : String(error));
    app.quit();
    return;
  }
  createWindow();
  app.on("activate", () => {
    if (BrowserWindow.getAllWindows().length === 0) {
      createWindow();
    }
  });
});

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") {
    app.quit();
  }
});

app.on("before-quit", () => {
  if (backendProcess) {
    backendProcess.kill();
    backendProcess = null;
  }
});
