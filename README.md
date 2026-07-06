# gagent-desktop

Minimal npm desktop app for GenericAgent.

This package is intentionally small. It does **not** publish the repository root,
runtime logs, local memory files, model responses, `.env` files, or `mykey*`
files. The package contains only:

- a CLI launcher,
- an Electron shell,
- the built React UI in `dist/`,
- a sanitized packaged backend snapshot in `backend/`,
- an embedded Windows Python runtime in `python-runtime/` when prepared for npm release,
- this README,
- `package.json`.

## Backend Strategy

v0.3 includes the frontend, backend code, and a prepared Windows Python runtime
in the npm package. On Windows, the launcher prefers the embedded
`python-runtime/python.exe`, so users can install and open the app without
manually creating a Python environment.

```powershell
npm install -g gagent-desktop
gagent-desktop
```

To update an existing global install later from either PowerShell or `cmd.exe`:

```powershell
gagent-desktop update
# equivalent:
gagent-desktop --update
```

In plain `cmd.exe`, the same commands are:

```cmd
gagent-desktop update
gagent-desktop --update
```

When running from the package directory, the same updater is available through:

```powershell
npm run update
```

If the package was built without `python-runtime/`, the launcher falls back to a
local virtual environment in `~/.gagent-desktop/python-env`. You can prepare that
fallback environment explicitly:

```powershell
gagent-desktop setup
```

For local development, override the backend checkout:

```powershell
gagent-desktop --repo F:\GAgent-Multi --python D:\anaconda0\python.exe
```

The launcher starts:

- FastAPI on `127.0.0.1:8765` unless it is already healthy,
- Electron using the packaged React build.

## Preparing an npm Release With Embedded Python

From the repository root, prepare the React build, sanitized backend, and
embedded runtime before publishing:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File tools\prepare_gagent_desktop_package.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File tools\prepare_gagent_desktop_windows_runtime.ps1

cd packages\gagent-desktop
npm.cmd pack --dry-run
npm.cmd publish --dry-run
npm.cmd publish --access public
```

The runtime script downloads the official embeddable Python zip and installs the
desktop backend requirements into `python-runtime/`. Use `-PipIndexUrl` if you
need a regional Python package mirror.

## First Launch: API Key Configuration

Model credentials are configured with the backend Python config file, not through
a browser form. From the backend directory created by the package, copy the
template and fill in your own key:

```powershell
copy backend\mykey_template.py backend\mykey.py
notepad backend\mykey.py
```

For a normal repository checkout, the equivalent command is:

```powershell
copy mykey_template.py mykey.py
notepad mykey.py
```

The minimum DeepSeek slot is:

```python
key1_native_oai_config = {
    "name": "deepseek-v4-pro",
    "apikey": "sk-your-key-here",
    "apibase": "https://api.deepseek.com",
    "model": "deepseek-v4-pro",
    "stream": True,
}
```

`mykey.py` stays local and must not be committed or published. The package ships
only `mykey_template.py`, with blank key fields.

## Windows `.exe` Build

The repository can also build a Windows desktop package that carries:

- the Electron shell,
- the built React UI,
- the sanitized backend snapshot,
- an embedded Python runtime in `python-runtime/`.

From the repository root:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File tools\build_gagent_desktop_windows.ps1
```

For a fast packaging smoke test without installing Python dependencies into the
embedded runtime:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File tools\build_gagent_desktop_windows.ps1 -SkipDependencyInstall -DirOnly
```

The packaged Electron app starts the backend from its resources directory on
launch. If an API is already healthy at `127.0.0.1:8765`, it reuses it.

The Windows build uses mirror-friendly defaults for Electron downloads:

```powershell
$env:ELECTRON_MIRROR="https://npmmirror.com/mirrors/electron/"
$env:ELECTRON_BUILDER_BINARIES_MIRROR="https://npmmirror.com/mirrors/electron-builder-binaries/"
```

Set these variables yourself to override the defaults.

## Safety Boundary

The packaged backend is sanitized at build time. It excludes local state such as
`temp/`, logs, model responses, `.env*`, `mykey*`, SQLite memory stores, raw
history, and personal memory files. It does **not** publish the repository root.

The npm command now uses the packaged Windows Python runtime when
`python-runtime/python.exe` is present. Non-Windows users, or packages built
without `python-runtime/`, still need a local Python installation or an external
backend passed with `--repo` and `--python`.

## Useful Commands

```powershell
npm run dry-run
npm run update
npm run test:update
npm run test:update:cmd
npm pack --dry-run
npm publish --dry-run
```
