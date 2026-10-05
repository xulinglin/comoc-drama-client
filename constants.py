"""客户端共享常量。拆分自 launcher.py，保持原值与原变量名不变。"""
from __future__ import annotations

import os
import platform
import sys
from pathlib import Path
from urllib.parse import urlparse


def _resolve_root() -> Path:
    """返回应用根目录。

    - 开发态：本文件所在目录（即项目根）。
    - PyInstaller 打包后：可执行文件所在目录，使 data/、output/、runtime/
      等可写或体积较大的资源与 exe 同级，而不是落在临时解包目录里。
    """
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


ROOT = _resolve_root()
BUNDLE_DIR = Path(getattr(sys, "_MEIPASS", ROOT)).resolve()
FRONTEND_DIST = BUNDLE_DIR / "frontend" / "dist" / "index.html"
APP_ICON = ROOT / "assets" / "app-icon.ico"
DATA_DIR = ROOT / "data"
if sys.platform == "darwin":
    APP_ICON = BUNDLE_DIR / "assets" / "app-icon.png"
    if getattr(sys, "frozen", False):
        # .app 内的资源不用于存储可写数据，也避免升级覆盖用户数据。
        user_root = Path.home() / "Library" / "Application Support" / "CDTV"
        DATA_DIR = user_root / "data"
STORAGE_DIR = DATA_DIR / "storage"
# 视频输出并入项目存储目录下，用 output/ 子目录区分，不再单独配置。
OUTPUT_DIR = STORAGE_DIR / "output"


def output_dir_for(settings: dict) -> Path:
    """按运行设置解析视频输出目录：项目存储目录下的 output/ 子目录。"""
    storage_dir = settings.get("storageDir") if isinstance(settings, dict) else None
    base = Path(str(storage_dir)).expanduser() if storage_dir else STORAGE_DIR
    return (base / "output").resolve()
ACCOUNTS_DIR = DATA_DIR / "accounts"
ACCOUNTS_FILE = DATA_DIR / "accounts.json"
SETTINGS_FILE = DATA_DIR / "settings.json"
AUTH_FILE = DATA_DIR / "auth.json"
CREDENTIALS_FILE = DATA_DIR / "credentials.json"
GENERATION_TASKS_FILE = DATA_DIR / "generation_tasks.json"
ORIGINAL_DOUBAO_URL = "https://www.doubao.com/"
BUNDLED_CHROME = ROOT / "runtime" / "chrome-win64" / "chrome.exe"
if sys.platform == "darwin":
    chrome_folder = "chrome-mac-arm64" if platform.machine().lower() in {"arm64", "aarch64"} else "chrome-mac-x64"
    BUNDLED_CHROME = ROOT / "runtime" / chrome_folder / "chrome.app" / "Contents" / "MacOS" / "Google Chrome for Testing"
API_BASE_URL = os.environ.get("COMIC_DRAMA_API_BASE", "http://127.0.0.1:8080").rstrip("/")
STORAGE_API_BASE_URL = os.environ.get("COMIC_DRAMA_STORAGE_API_BASE", "http://127.0.0.1:18081").rstrip("/")
STORAGE_SERVICE_JAR = ROOT / "storage" / "comic-drama-storage.jar"
BUNDLED_JAVA = ROOT / "runtime" / "jre" / "bin" / "javaw.exe"
if sys.platform == "darwin":
    BUNDLED_JAVA = ROOT / "runtime" / "jre" / "bin" / "java"
API_HOST = (urlparse(API_BASE_URL).hostname or "").lower()
API_TRUST_ENV = API_HOST not in {"127.0.0.1", "localhost", "::1"}
