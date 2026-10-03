# Development, Build & Packaging

English | [简体中文](DEVELOPMENT.md)

This document is for developers: running from source, building, frontend development, packaging as an exe, and the directory structure. For user-facing documentation, see the [README](../README.en.md).

---

## Requirements (Running from Source)

- Windows 10 / 11
- Python 3.11+
- Node.js 20.19+ (20.x) or 22.12+; use an LTS release that meets this range
- **WebView2 Runtime** installed (usually bundled with Win10/11)

## Installation

Run these PowerShell commands from the project root. `npm ci` uses the committed lockfile. The Node.js minimum matches the `engines.node` requirements of the current Vite and Vue plugin dependencies.

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
cd frontend
npm ci
npm run build
cd ..
```

## Run the Desktop App

```powershell
.venv\Scripts\python launcher.py
```

On startup the app automatically launches the built-in local storage service and enters with a single local account; no extra service needs to be started.

## Frontend Development Mode

After installing dependencies, you can double-click `启动应用.bat` in the project root. It starts or reuses Vite on port 5173 and launches the desktop client in development mode. It requires the `.venv` environment. For manual startup:

Start Vite first:

```powershell
cd frontend
npm run dev
```

Then open another terminal **at the project root**:

```powershell
.venv\Scripts\python launcher.py --dev
```

---

## Packaging as an EXE

A `launcher.spec` is provided; package it as a Windows executable with PyInstaller (directory mode):

```powershell
# 1. Build the frontend first
cd frontend
npm run build
cd ..

# 2. Install PyInstaller (if not installed)
.venv\Scripts\python -m pip install pyinstaller

# 3. Package
.venv\Scripts\python -m PyInstaller launcher.spec --noconfirm --clean
```

The output is in `dist/CDTV/`. Distribute the entire directory, including PyInstaller dependencies, rather than the exe alone. **When distributing, place `runtime/chrome-win64` next to `CDTV.exe`** so the final path is `dist/CDTV/runtime/chrome-win64/chrome.exe` and OriginalDoubao automation can find the bundled browser. The current worker requires this path and does not automatically download a browser. `data/` and `output/` are created next to the exe on first run.

Notes:

- The target machine needs **WebView2 Runtime**, otherwise pywebview cannot start.
- No Java runtime and no storage jar are required.
- The Playwright driver is bundled into the exe; the browser kernel reuses `runtime/chrome-win64`.

## Troubleshooting

- **Missing frontend build**: run `npm ci` and `npm run build` under `frontend/`, then launch `launcher.py` from the project root.
- **Blank window in development mode**: check that `http://127.0.0.1:5173` opens and Vite is still running. A browser-only page does not provide the `pywebview` desktop API.
- **Missing bundled browser**: verify `runtime/chrome-win64/chrome.exe`; this path is required for OriginalDoubao automation.
- **AI generation configuration error**: image generation, MiniMax voice previews, Seedance tasks, and text forwarding are connected. Check that the selected model is enabled and its API URL, key, and model name are complete. Restart the client after changing the Python service code.
- **Storage directory still points to the previous location**: changes take effect after a restart and do not move existing data. To retain data, close the client and copy the complete current storage directory to the destination.
- **Python changes are not reflected**: fully exit and restart the client. Vite hot-reloads frontend source only; the default non-development launch uses `frontend/dist` and requires rebuilding after frontend changes.

## Directory Structure

```text
comoc-drama-client/
├─ launcher.py            # Desktop entry point
├─ local_storage.py       # Built-in pure-Python local storage service (SQLite + file bucket)
├─ original_doubao_worker.py       # Playwright account worker and conversion flow
├─ original_doubao_nomark.py       # Link type, domain validation, and parsing
├─ media_server.py        # Local media preview server
├─ constants.py           # Shared constants and paths
├─ launcher.spec          # PyInstaller packaging config
├─ SKILL/                 # AI storyboard capability definitions (SKILL.md + references/)
├─ frontend/              # Vue 3 frontend
├─ assets/                # App icons
├─ scripts/               # Utility scripts (icon generation, window debug, shortcut, etc.)
├─ docs/                  # Additional documentation
└─ data/ output/          # Runtime data (gitignored)
```
