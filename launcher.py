from __future__ import annotations

import argparse
import base64
import ctypes
from ctypes import wintypes
import json
import mimetypes
import os
import queue
import re
import shutil
import sqlite3
import subprocess
import threading
import time
import uuid
from datetime import date
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlparse

# ===== DPI 感知：必须在创建任何窗口前声明 =====
# 不声明的话 Windows 会用位图拉伸缩放，导致字体和画面模糊
if os.name == "nt":
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


def get_dpi_scale() -> float:
    """获取系统 DPI 缩放比例（1.0=100%, 1.25=125%, 1.5=150%, 2.0=200%）"""
    if os.name != "nt":
        return 1.0
    try:
        dpi = ctypes.windll.user32.GetDpiForSystem()
        return max(1.0, dpi / 96.0)
    except Exception:
        return 1.0


class _MonitorInfo(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("rcMonitor", wintypes.RECT),
        ("rcWork", wintypes.RECT),
        ("dwFlags", wintypes.DWORD),
    ]


class _MinMaxInfo(ctypes.Structure):
    _fields_ = [
        ("ptReserved", wintypes.POINT),
        ("ptMaxSize", wintypes.POINT),
        ("ptMaxPosition", wintypes.POINT),
        ("ptMinTrack", wintypes.POINT),
        ("ptMaxTrack", wintypes.POINT),
    ]


class _WindowPos(ctypes.Structure):
    _fields_ = [
        ("hwnd", wintypes.HWND),
        ("hwndInsertAfter", wintypes.HWND),
        ("x", ctypes.c_int),
        ("y", ctypes.c_int),
        ("cx", ctypes.c_int),
        ("cy", ctypes.c_int),
        ("flags", wintypes.UINT),
    ]


def _compute_initial_window_bounds() -> tuple[int, int, int, int]:
    """返回 (x, y, width, height) DIP，基于光标所在显示器工作区 85% 居中。

    Per-Monitor V2 感知下 GetSystemMetrics(SM_CXSCREEN) 只返回主屏物理像素，
    若用户从副屏启动会得到错误尺寸。这里用光标位置定位显示器，按该屏工作区
    与该屏 DPI 折算，确保任意屏启动都得到 85% 占比 + 居中。
    """
    if os.name != "nt":
        return (120, 120, 1280, 800)

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.GetCursorPos.argtypes = [ctypes.POINTER(wintypes.POINT)]
    user32.GetCursorPos.restype = wintypes.BOOL
    user32.MonitorFromPoint.argtypes = [wintypes.POINT, wintypes.DWORD]
    user32.MonitorFromPoint.restype = wintypes.HMONITOR
    user32.GetMonitorInfoW.argtypes = [wintypes.HMONITOR, ctypes.POINTER(_MonitorInfo)]
    user32.GetMonitorInfoW.restype = wintypes.BOOL

    cursor = wintypes.POINT()
    if not user32.GetCursorPos(ctypes.byref(cursor)):
        cursor.x, cursor.y = 0, 0

    # MONITOR_DEFAULTTONEAREST = 2
    hmon = user32.MonitorFromPoint(cursor, 2)
    info = _MonitorInfo()
    info.cbSize = ctypes.sizeof(info)
    if not hmon or not user32.GetMonitorInfoW(hmon, ctypes.byref(info)):
        # 兜底：主屏
        scale = get_dpi_scale()
        sw = user32.GetSystemMetrics(0)
        sh = user32.GetSystemMetrics(1)
        w = int(sw / scale * 0.85)
        h = int(sh / scale * 0.85)
        x = int(sw / scale * 0.075)
        y = int(sh / scale * 0.075)
        return (x, y, w, h)

    # 该屏 DPI（per-monitor v2 感知下需用 GetDpiForMonitor，不能用 GetDpiForSystem）
    dpi_x = ctypes.c_uint()
    shcore = ctypes.WinDLL("shcore", use_last_error=True)
    shcore.GetDpiForMonitor.argtypes = [
        wintypes.HMONITOR, ctypes.c_int,
        ctypes.POINTER(ctypes.c_uint), ctypes.POINTER(ctypes.c_uint),
    ]
    shcore.GetDpiForMonitor.restype = ctypes.c_long
    try:
        shcore.GetDpiForMonitor(
            wintypes.HMONITOR(hmon), 0,
            ctypes.byref(dpi_x), ctypes.byref(dpi_x),
        )
        scale = max(1.0, dpi_x.value / 96.0)
    except Exception:
        scale = get_dpi_scale()

    work = info.rcWork
    work_w_phys = work.right - work.left
    work_h_phys = work.bottom - work.top
    win_w_phys = int(work_w_phys * 0.85)
    win_h_phys = int(work_h_phys * 0.85)
    win_x_phys = work.left + (work_w_phys - win_w_phys) // 2
    win_y_phys = work.top + (work_h_phys - win_h_phys) // 2

    # 物理 → DIP（pywebview 在 DPI 感知下接收 DIP）
    return (
        int(win_x_phys / scale),
        int(win_y_phys / scale),
        int(win_w_phys / scale),
        int(win_h_phys / scale),
    )


import webview
import httpx

from constants import (
    ACCOUNTS_DIR,
    ACCOUNTS_FILE,
    API_BASE_URL,
    API_TRUST_ENV,
    APP_ICON,
    AUTH_FILE,
    BUNDLED_JAVA,
    CREDENTIALS_FILE,
    DATA_DIR,
    ORIGINAL_DOUBAO_URL,
    FRONTEND_DIST,
    OUTPUT_DIR,
    ROOT,
    SETTINGS_FILE,
    STORAGE_API_BASE_URL,
    STORAGE_DIR,
    STORAGE_SERVICE_JAR,
)
from original_doubao_worker import AccountBrowserWorker
from original_doubao_nomark import is_supported_conversion_url
from media_server import MediaPreviewServer

# 项目文件目录树默认隐藏的构建 / 依赖 / 版本管理目录：
# 这些目录是工具生成的噪音（target 是 Maven 构建产物），默认不出现在目录树里，
# 前端打开"显示构建目录"后才会列出。
PROJECT_TREE_HIDDEN_NAMES = frozenset({
    "target", "build", "dist", "out", "node_modules", "__pycache__",
    ".git", ".idea", ".vscode", ".gradle", ".pytest_cache", ".venv", "venv",
})


def _stringify_id_fields(value: Any) -> Any:
    """把返回给前端的 id 字段统一转成字符串。

    部分历史数据的主键是 19 位数字（超过 JS Number 安全整数上限 2^53），
    若以 JSON 数字传给前端会被四舍五入成另一个值，导致按 id 请求时误报“数据不存在”。
    """
    if isinstance(value, dict):
        return {
            key: (
                str(item)
                if isinstance(item, (int, float)) and not isinstance(item, bool)
                and (key == "id" or key.endswith("Id"))
                else _stringify_id_fields(item)
            )
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_stringify_id_fields(item) for item in value]
    return value


class DesktopApi:
    def __init__(self) -> None:
        # Keep native pywebview objects private. Public js_api attributes are
        # recursively exposed to JavaScript and a Window contains cyclic .NET
        # objects such as DefaultFont.FontFamily.
        self._window: webview.Window | None = None
        self._tasks: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()
        self._workers: dict[str, AccountBrowserWorker] = {}
        self._account_usage: dict[str, dict[str, Any]] = {}
        # 校验登录得到的"会话已过期"标记（运行时内存态，随客户端重启清空；
        # 不写入 accounts.json，避免被云同步的字段白名单覆盖丢失）。
        self._login_expired: dict[str, bool] = {}
        self._media_server = MediaPreviewServer()
        self._storage_process: subprocess.Popen[Any] | None = None
        self._storage_log_handle: Any = None
        self._local_storage_server: Any = None
        self._local_storage_migration_checked = False
        self._local_storage_migration_last_attempt = 0.0
        self._window_maximized = False
        self._window_restore_bounds: tuple[int, int, int, int] | None = None
        self._session_token = ""
        self._cloud_accounts_synced_token = ""
        self._cloud_accounts_last_attempt = 0.0
        self._write_settings(self.get_settings())
        self._start_storage_service()

    @staticmethod
    def _auth_headers(token: str = "") -> dict[str, str]:
        headers = {"Accept": "application/json"}
        if token:
            headers["satoken"] = token
        return headers

    @staticmethod
    def _read_auth() -> dict[str, Any]:
        if not AUTH_FILE.exists():
            return {}
        try:
            saved = json.loads(AUTH_FILE.read_text(encoding="utf-8"))
            return saved if isinstance(saved, dict) else {}
        except (OSError, json.JSONDecodeError):
            return {}

    @staticmethod
    def _save_auth(token: str, user: dict[str, Any]) -> None:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        AUTH_FILE.write_text(
            json.dumps({"token": token, "user": user}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    @staticmethod
    def _clear_auth() -> None:
        try:
            AUTH_FILE.unlink(missing_ok=True)
        except OSError:
            pass

    @staticmethod
    def get_saved_credentials() -> dict[str, Any]:
        if not CREDENTIALS_FILE.exists():
            return {"username": "", "password": "", "remember": False}
        try:
            saved = json.loads(CREDENTIALS_FILE.read_text(encoding="utf-8"))
            if not isinstance(saved, dict):
                raise ValueError
            return {
                "username": str(saved.get("username") or ""),
                "password": str(saved.get("password") or ""),
                "remember": True,
            }
        except (OSError, ValueError, json.JSONDecodeError):
            return {"username": "", "password": "", "remember": False}

    @staticmethod
    def _save_credentials(username: str, password: str) -> None:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        CREDENTIALS_FILE.write_text(
            json.dumps({"username": username, "password": password}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    @staticmethod
    def _clear_credentials() -> None:
        try:
            CREDENTIALS_FILE.unlink(missing_ok=True)
        except OSError:
            pass

    @staticmethod
    def _parse_api_response(response: httpx.Response) -> dict[str, Any]:
        try:
            body = response.json()
        except ValueError as exc:
            content_type = response.headers.get("content-type", "").split(";", 1)[0]
            response_kind = content_type or ("空响应" if not response.content else "非 JSON 响应")
            raise ValueError(
                f"登录服务请求失败（HTTP {response.status_code}，{response_kind}）"
            ) from exc
        if not isinstance(body, dict):
            raise ValueError("登录服务返回格式不正确")
        if response.status_code >= 400:
            raise ValueError(str(body.get("message") or f"登录服务请求失败（{response.status_code}）"))
        if body.get("code") != 200:
            raise ValueError(str(body.get("message") or "登录失败，请检查账号或密码"))
        return body

    @staticmethod
    def _api_request(method: str, path: str, *, timeout: float, **kwargs: Any) -> httpx.Response:
        # httpx follows HTTP_PROXY by default. Some Windows proxy setups do not
        # exempt 127.0.0.1, which turns a healthy local Boot response into a 502.
        with httpx.Client(
            base_url=f"{API_BASE_URL}/",
            trust_env=API_TRUST_ENV,
            timeout=timeout,
        ) as client:
            return client.request(method, path.lstrip("/"), **kwargs)

    @staticmethod
    def _storage_request(method: str, path: str, *, timeout: float, **kwargs: Any) -> httpx.Response:
        with httpx.Client(base_url=f"{STORAGE_API_BASE_URL}/", trust_env=False, timeout=timeout) as client:
            return client.request(method, path.lstrip("/"), **kwargs)

    def _storage_first_request(self, method: str, path: str, *, timeout: float, **kwargs: Any) -> httpx.Response:
        return self._storage_request(method, path, timeout=timeout, **kwargs)

    @staticmethod
    def _is_local_storage_path(path: str) -> bool:
        return path == "/project" or path.startswith((
            "/project/", "/chapter/", "/asset", "/video-project", "/file", "/api/admin/models", "/ai/",
        ))

    def _file_request(self, method: str, file_id: str, *, timeout: float, **kwargs: Any) -> httpx.Response:
        path = f"/file/{quote(file_id, safe='')}/download"
        return self._storage_request(method, path, timeout=timeout, **kwargs)

    def _storage_available(self) -> bool:
        try:
            response = self._storage_request("GET", "/api/storage/health", timeout=0.8)
            return response.status_code == 200
        except httpx.HTTPError:
            return False

    def _start_local_storage(self) -> None:
        """启动内置的纯 Python 本地存储服务（无需 Java）。"""
        if self._storage_available():
            return
        try:
            from local_storage import LocalStorageServer
        except ImportError:
            return
        try:
            storage_dir = Path(str(self.get_settings().get("storageDir") or STORAGE_DIR)).expanduser().resolve()
            self._local_storage_server = LocalStorageServer(storage_dir, port=int(urlparse(STORAGE_API_BASE_URL).port or 18081))
            self._local_storage_server.start()
        except OSError:
            self._local_storage_server = None

    def _start_storage_service(self) -> None:
        if self._storage_available():
            return
        # 优先使用内置 Python 本地存储，彻底摆脱 Java 运行时依赖。
        self._start_local_storage()
        deadline = time.monotonic() + 12
        while time.monotonic() < deadline:
            if self._storage_available():
                return
            time.sleep(0.2)
        development_jar = STORAGE_SERVICE_JAR.parents[2] / "comic-drama-storage" / "target" / "comic-drama-storage-0.1.0.jar"
        jar = next((candidate for candidate in (STORAGE_SERVICE_JAR, development_jar) if candidate.is_file()), None)
        development_javas = sorted((Path.home() / ".jdks").glob("*/bin/javaw.exe"), reverse=True)
        java = str(BUNDLED_JAVA) if BUNDLED_JAVA.is_file() else (
            shutil.which("javaw") or shutil.which("java") or (str(development_javas[0]) if development_javas else None)
        )
        if jar is None or not java:
            return
        log_dir = DATA_DIR / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        self._storage_log_handle = (log_dir / "storage-service.log").open("a", encoding="utf-8")
        creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        settings_argument = f"--comic.storage.client-settings-file={SETTINGS_FILE.resolve()}"
        print(f'[storage] comic.storage.client-settings-file="{SETTINGS_FILE.resolve()}"')
        self._storage_process = subprocess.Popen(
            [
                java,
                "-jar",
                str(jar),
                settings_argument,
            ],
            cwd=str(jar.parent),
            stdout=self._storage_log_handle,
            stderr=subprocess.STDOUT,
            creationflags=creation_flags,
        )
        deadline = time.monotonic() + 12
        while time.monotonic() < deadline:
            if self._storage_process.poll() is not None or self._storage_available():
                break
            time.sleep(0.2)

    def _ensure_local_storage_migrated(self, token: str) -> None:
        # Storage-only mode never reads from or migrates data out of Boot.
        return
        
        if self._local_storage_migration_checked or not self._storage_available():
            return
        now = time.monotonic()
        if now - self._local_storage_migration_last_attempt < 30:
            return
        self._local_storage_migration_last_attempt = now
        headers = self._auth_headers(token)

        def data_from(response: httpx.Response) -> Any:
            return self._parse_api_response(response).get("data")

        try:
            local_projects = data_from(self._storage_request("GET", "/project/list", headers=headers, timeout=5)) or []
            local_assets = data_from(self._storage_request("GET", "/asset/list", headers=headers, timeout=5)) or []
            local_tasks = data_from(self._storage_request("GET", "/video-project/list", headers=headers, timeout=5)) or []
            local_ids = {
                "projects": {str(item.get("id")) for item in local_projects if isinstance(item, dict)},
                "assets": {str(item.get("id")) for item in local_assets if isinstance(item, dict)},
                "tasks": {str(item.get("id")) for item in local_tasks if isinstance(item, dict)},
            }

            remote_projects = data_from(self._api_request("GET", "/project/list", headers=headers, timeout=12)) or []
            for project in remote_projects:
                if not isinstance(project, dict) or str(project.get("id")) in local_ids["projects"]:
                    continue
                data_from(self._storage_request("POST", "/project", headers=headers, json=project, timeout=8))
            for project in remote_projects:
                project_id = str(project.get("id") or "") if isinstance(project, dict) else ""
                if not project_id:
                    continue
                chapters = data_from(self._api_request(
                    "GET", f"/project/{quote(project_id, safe='')}/chapter/list", headers=headers, timeout=12,
                )) or []
                local_chapters = data_from(self._storage_request(
                    "GET", f"/project/{quote(project_id, safe='')}/chapter/list", headers=headers, timeout=5,
                )) or []
                local_chapter_ids = {str(item.get("id")) for item in local_chapters if isinstance(item, dict)}
                for chapter in chapters:
                    if not isinstance(chapter, dict) or str(chapter.get("id")) in local_chapter_ids:
                        continue
                    data_from(self._storage_request(
                        "POST", f"/project/{quote(project_id, safe='')}/chapter",
                        headers=headers, json=chapter, timeout=8,
                    ))

            remote_assets = data_from(self._api_request("GET", "/asset/list", headers=headers, timeout=12)) or []
            for asset in remote_assets:
                if isinstance(asset, dict) and str(asset.get("id")) not in local_ids["assets"]:
                    data_from(self._storage_request("POST", "/asset", headers=headers, json=asset, timeout=8))

            remote_tasks = data_from(self._api_request("GET", "/video-project/list", headers=headers, timeout=12)) or []
            for summary in remote_tasks:
                task_id = str(summary.get("id") or "") if isinstance(summary, dict) else ""
                if not task_id or task_id in local_ids["tasks"]:
                    continue
                detail = data_from(self._api_request(
                    "GET", f"/video-project/{quote(task_id, safe='')}", headers=headers, timeout=15,
                ))
                if isinstance(detail, dict):
                    data_from(self._storage_request("POST", "/video-project", headers=headers, json=detail, timeout=15))
            self._local_storage_migration_checked = True
        except (httpx.HTTPError, ValueError, OSError):
            # Offline or partial migration is safe: stable IDs make the next attempt idempotent.
            return

    def login(self, username: str, password: str, remember: bool = True) -> dict[str, Any]:
        if self._storage_available():
            return self._local_session()
        clean_username = str(username).strip()
        if not clean_username or not password:
            raise ValueError("请输入用户名和密码")
        try:
            response = self._api_request(
                "POST",
                "/auth/login",
                json={"username": clean_username, "password": str(password)},
                headers=self._auth_headers(),
                timeout=15,
            )
        except httpx.TimeoutException as exc:
            raise ValueError("连接登录服务超时，请稍后重试") from exc
        except httpx.HTTPError as exc:
            raise ValueError("无法连接登录服务，请确认 Boot 服务已启动") from exc

        body = self._parse_api_response(response)
        user = body.get("data")
        if not isinstance(user, dict) or not user.get("token"):
            raise ValueError("登录成功，但服务未返回登录凭证")
        token = str(user["token"])
        self._session_token = token
        self._cloud_accounts_synced_token = ""
        self._cloud_accounts_last_attempt = 0.0
        safe_user = {key: value for key, value in user.items() if key != "token"}
        if remember:
            self._save_auth(token, safe_user)
            self._save_credentials(clean_username, str(password))
        else:
            self._clear_auth()
            self._clear_credentials()
        return {"authenticated": True, "token": token, "user": safe_user}

    def register(self, username: str, password: str, remember: bool = True) -> dict[str, Any]:
        if self._storage_available():
            return self._local_session()
        clean_username = str(username).strip()
        if len(clean_username) < 3:
            raise ValueError("用户名至少需要 3 位")
        if len(str(password)) < 6:
            raise ValueError("密码至少需要 6 位")
        try:
            response = self._api_request(
                "POST",
                "/auth/register",
                json={"username": clean_username, "password": str(password)},
                headers=self._auth_headers(),
                timeout=15,
            )
        except httpx.TimeoutException as exc:
            raise ValueError("连接注册服务超时，请稍后重试") from exc
        except httpx.HTTPError as exc:
            raise ValueError("无法连接注册服务，请确认 Boot 服务已启动") from exc

        body = self._parse_api_response(response)
        user = body.get("data")
        if not isinstance(user, dict) or not user.get("token"):
            raise ValueError("注册成功，但服务未返回登录凭证")
        token = str(user["token"])
        self._session_token = token
        self._cloud_accounts_synced_token = ""
        self._cloud_accounts_last_attempt = 0.0
        safe_user = {key: value for key, value in user.items() if key != "token"}
        if remember:
            self._save_auth(token, safe_user)
            self._save_credentials(clean_username, str(password))
        else:
            self._clear_auth()
            self._clear_credentials()
        return {"authenticated": True, "token": token, "user": safe_user}

    def _local_session(self) -> dict[str, Any]:
        """本地模式下的单机会话，无需连接任何登录服务。"""
        saved = self._read_auth()
        user = saved.get("user") if isinstance(saved.get("user"), dict) else {}
        if not user.get("userId"):
            user = {
                "userId": "local",
                "username": "local",
                "nickname": "本地用户",
                "points": 0,
                "role": "admin",
            }
        token = str(saved.get("token") or "local-token")
        self._session_token = token
        self._save_auth(token, user)
        return {"authenticated": True, "token": token, "user": user}

    def get_auth_session(self) -> dict[str, Any]:
        if self._storage_available():
            return self._local_session()
        saved = self._read_auth()
        token = str(saved.get("token") or "")
        if not token:
            return {"authenticated": False, "user": None}
        try:
            response = self._api_request(
                "GET",
                "/auth/me",
                headers=self._auth_headers(token),
                timeout=10,
            )
            body = self._parse_api_response(response)
        except (httpx.TimeoutException, httpx.HTTPError, ValueError):
            return {
                "authenticated": False,
                "user": None,
                "error": "暂时无法验证登录状态，请重新登录",
            }
        user = body.get("data")
        if not isinstance(user, dict) or not user.get("userId"):
            self._clear_auth()
            return {"authenticated": False, "user": None}
        self._session_token = token
        self._cloud_accounts_synced_token = ""
        self._cloud_accounts_last_attempt = 0.0
        self._save_auth(token, user)
        return {"authenticated": True, "token": token, "user": user}

    def logout(self, token: str = "") -> dict[str, bool]:
        saved_token = str(self._read_auth().get("token") or "")
        active_token = str(token or saved_token)
        if active_token:
            try:
                self._api_request(
                    "POST",
                    "/auth/logout",
                    headers=self._auth_headers(active_token),
                    timeout=8,
                )
            except httpx.HTTPError:
                pass
        self._clear_auth()
        self._session_token = ""
        self._cloud_accounts_synced_token = ""
        self._cloud_accounts_last_attempt = 0.0
        return {"success": True}

    def backend_request(
        self,
        method: str,
        path: str,
        token: str = "",
        body: dict[str, Any] | None = None,
    ) -> Any:
        request_method = str(method).upper()
        if request_method not in {"GET", "POST", "PUT", "DELETE"}:
            raise ValueError("不支持的请求方式")
        request_path = str(path).strip()
        if not request_path.startswith("/") or "://" in request_path:
            raise ValueError("接口路径不正确")
        try:
            kwargs: dict[str, Any] = {"headers": self._auth_headers()}
            if body is not None and request_method in {"POST", "PUT"}:
                kwargs["json"] = body
            response = self._storage_request(
                request_method,
                request_path,
                timeout=330 if request_path.startswith("/ai/") else 30,
                **kwargs,
            )
        except httpx.TimeoutException as exc:
            raise ValueError("请求服务超时，请稍后重试") from exc
        except httpx.HTTPError as exc:
            raise ValueError("无法连接 Storage 服务") from exc
        result = self._parse_api_response(response).get("data")
        return _stringify_id_fields(result)

    def prepare_generation_asset(self, asset: dict[str, Any], token: str = "") -> dict[str, str]:
        """Resolve an asset-library image to a local file accepted by the generator."""
        local_path = Path(str(asset.get("path") or ""))
        if local_path.is_file():
            return {"path": str(local_path.resolve())}

        file_id = str(asset.get("coverId") or asset.get("fileId") or "").strip()
        if not file_id:
            raise ValueError("当前分镜没有可用于生成的图片资产")
        active_token = str(token or self._read_auth().get("token") or "")
        if not active_token:
            raise ValueError("登录状态已失效，请重新登录")
        try:
            response = self._file_request(
                "GET",
                file_id,
                headers=self._auth_headers(active_token),
                timeout=60,
            )
            response.raise_for_status()
        except httpx.TimeoutException as exc:
            raise ValueError("下载分镜参考图超时，请重试") from exc
        except httpx.HTTPError as exc:
            raise ValueError("无法下载分镜参考图") from exc

        content_type = response.headers.get("content-type", "").split(";", 1)[0].strip()
        suffix = mimetypes.guess_extension(content_type) or ".png"
        if suffix == ".jpe":
            suffix = ".jpg"
        cache_dir = DATA_DIR / "generation_inputs"
        cache_dir.mkdir(parents=True, exist_ok=True)
        target = cache_dir / f"asset_{re.sub(r'[^a-zA-Z0-9_-]', '_', file_id)}{suffix}"
        target.write_bytes(response.content)
        return {"path": str(target.resolve())}

    def select_json_data(self) -> dict[str, Any] | None:
        if self._window is None:
            return None
        result = self._window.create_file_dialog(
            webview.FileDialog.OPEN,
            allow_multiple=False,
            file_types=("JSON files (*.json)", "All files (*.*)"),
        )
        if not result:
            return None
        file_path = Path(result[0]).resolve()
        if file_path.stat().st_size > 10 * 1024 * 1024:
            raise ValueError("JSON 文件不能超过 10MB")
        try:
            data = json.loads(file_path.read_text(encoding="utf-8-sig"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"JSON 格式错误：第 {exc.lineno} 行第 {exc.colno} 列") from exc
        return {"name": file_path.name, "data": data}

    @staticmethod
    def _local_reference_media_type(file_path: Path) -> str:
        content_type = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"
        image_suffixes = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}
        audio_suffixes = {".mp3", ".wav", ".m4a", ".aac", ".ogg", ".flac"}
        suffix = file_path.suffix.lower()
        if content_type.startswith("image/") or suffix in image_suffixes:
            return "image"
        if content_type.startswith("audio/") or suffix in audio_suffixes:
            return "audio"
        raise ValueError("本地参考素材只能上传图片或音频")

    def select_local_reference_file(self) -> dict[str, str] | None:
        if self._window is None:
            return None
        result = self._window.create_file_dialog(
            webview.FileDialog.OPEN,
            allow_multiple=False,
            file_types=(
                "Images and audio (*.png;*.jpg;*.jpeg;*.webp;*.gif;*.bmp;*.mp3;*.wav;*.m4a;*.aac;*.ogg;*.flac)",
            ),
        )
        if not result:
            return None
        file_path = Path(result[0]).resolve()
        media_type = self._local_reference_media_type(file_path)
        return {
            "path": str(file_path),
            "preview": self._media_server.register(file_path),
            "mediaType": media_type,
        }

    def upload_local_reference_file(self, token: str, file_path_value: str, payload: dict[str, Any]) -> dict[str, Any]:
        file_path = Path(str(file_path_value or "")).resolve()
        if not file_path.is_file():
            raise ValueError("本地参考素材不存在")
        media_type = self._local_reference_media_type(file_path)
        active_token = str(token or self._read_auth().get("token") or "")
        if not active_token:
            raise ValueError("登录状态已失效，请重新登录")
        content_type = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"
        requested_name = payload.get("audioName") if media_type == "audio" else payload.get("imageName")
        asset_name = str(requested_name or "").strip()
        if not asset_name:
            asset_name = "音1" if media_type == "audio" else "图1"
        data = {
            "name": asset_name,
            "description": str(payload.get("description") or "").strip(),
            "tags": str(payload.get("tags") or "").strip(),
            "type": media_type,
            "boundProjectIds": [
                str(project_id)
                for project_id in (payload.get("boundProjectIds") or [])
                if str(project_id).strip()
            ],
        }
        try:
            with file_path.open("rb") as file_handle:
                response = self._storage_first_request(
                    "POST",
                    "/asset/upload",
                    headers=self._auth_headers(active_token),
                    files={"file": (file_path.name, file_handle, content_type)},
                    data=data,
                    timeout=120,
                )
        except httpx.TimeoutException as exc:
            raise ValueError("上传超时，请稍后重试") from exc
        except (httpx.HTTPError, OSError) as exc:
            raise ValueError("资产上传失败") from exc
        uploaded = self._parse_api_response(response).get("data")
        if not isinstance(uploaded, dict):
            return None
        uploaded["mediaType"] = media_type
        uploaded["name"] = asset_name
        return uploaded

    def select_and_upload_asset(self, token: str, payload: dict[str, Any]) -> dict[str, Any] | None:
        selected = self.select_local_reference_file()
        if not selected:
            return None
        return self.upload_local_reference_file(token, selected["path"], payload)

    def upload_local_file(self, token: str, file_path: str) -> dict[str, Any]:
        path = Path(str(file_path or "")).resolve()
        if not path.is_file():
            raise ValueError("需要入库的媒体文件不存在")
        active_token = str(token or self._read_auth().get("token") or "")
        if not active_token:
            raise ValueError("登录状态已失效，请重新登录")
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        try:
            with path.open("rb") as file_handle:
                response = self._storage_first_request(
                    "POST",
                    "/file/upload",
                    headers=self._auth_headers(active_token),
                    files={"file": (path.name, file_handle, content_type)},
                    timeout=300,
                )
        except httpx.TimeoutException as exc:
            raise ValueError("媒体文件入库超时，请稍后重试") from exc
        except (httpx.HTTPError, OSError) as exc:
            raise ValueError("媒体文件入库失败") from exc
        uploaded = self._parse_api_response(response).get("data")
        if not isinstance(uploaded, dict):
            raise ValueError("媒体文件入库没有返回文件记录")
        return uploaded

    def compatible_video_preview(self, token: str, file_id: str) -> dict[str, Any]:
        """Return a WebView-playable URL for an uploaded video.

        OriginalDoubao's no-watermark rendition can be HEVC/hvc1, which the embedded
        WebView may not decode. Keep the uploaded original untouched and cache
        a local H.264 preview for every player in the desktop client.
        """

        clean_file_id = str(file_id or "").strip()
        if not clean_file_id or not re.fullmatch(r"[A-Za-z0-9_-]{1,160}", clean_file_id):
            raise ValueError("视频文件 ID 无效")
        active_token = str(token or self._read_auth().get("token") or "")
        cache_dir = DATA_DIR / "video_previews"
        cache_dir.mkdir(parents=True, exist_ok=True)
        source = cache_dir / f"{clean_file_id}.mp4"
        if not source.is_file() or source.stat().st_size == 0:
            try:
                response = self._file_request(
                    "GET",
                    clean_file_id,
                    headers=self._auth_headers(active_token) if active_token else {},
                    timeout=300,
                )
                response.raise_for_status()
                partial = cache_dir / f"{clean_file_id}.download.tmp"
                partial.write_bytes(response.content)
                if partial.stat().st_size == 0:
                    raise ValueError("服务器返回的视频文件为空")
                partial.replace(source)
            except httpx.TimeoutException as exc:
                raise ValueError("下载兼容预览视频超时") from exc
            except (httpx.HTTPError, OSError) as exc:
                raise ValueError("无法准备兼容视频预览") from exc
        preview = self._webview_preview_path(str(source))
        return {
            "url": self._media_server.register(preview),
            "converted": preview != source,
        }

    def minimize_window(self) -> None:
        if self._window is not None:
            self._window.minimize()

    def toggle_maximize_window(self) -> bool:
        """切换最大化/还原。

        **不用 SW_MAXIMIZE**——pywebview 嵌入场景下 .NET WinForms 对 SW_MAXIMIZE
        走自己的最大化路径，绕开外部 wndproc 的 WM_GETMINMAXINFO/WM_WINDOWPOSCHANGING/
        WM_NCCALCSIZE handler，窗口矩形被设成整屏（覆盖任务栏）。

        改为手动：保存当前矩形 → 置 WS_MAXIMIZE 状态位 → SetWindowPos 到光标所在
        屏工作区。窗口矩形直接由我们控制 = 工作区，.NET 没机会覆盖。WS_MAXIMIZE
        状态位让任务栏图标显示为最大化态。
        """
        if self._window is None:
            return False
        if os.name == "nt" and self._window.native is not None:
            hwnd = int(self._window.native.Handle.ToInt64())
            user32 = ctypes.WinDLL("user32", use_last_error=True)
            user32.GetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
            user32.GetWindowLongPtrW.restype = ctypes.c_ssize_t
            user32.SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t]
            user32.SetWindowLongPtrW.restype = ctypes.c_ssize_t
            user32.IsZoomed.argtypes = [wintypes.HWND]
            user32.IsZoomed.restype = wintypes.BOOL
            user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
            user32.GetWindowRect.restype = wintypes.BOOL
            user32.SetWindowPos.argtypes = [
                wintypes.HWND, wintypes.HWND,
                ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                wintypes.UINT,
            ]
            user32.SetWindowPos.restype = wintypes.BOOL
            user32.GetCursorPos.argtypes = [ctypes.POINTER(wintypes.POINT)]
            user32.GetCursorPos.restype = wintypes.BOOL
            user32.MonitorFromPoint.argtypes = [wintypes.POINT, wintypes.DWORD]
            user32.MonitorFromPoint.restype = wintypes.HMONITOR
            user32.GetMonitorInfoW.argtypes = [wintypes.HMONITOR, ctypes.POINTER(_MonitorInfo)]
            user32.GetMonitorInfoW.restype = wintypes.BOOL

            hwnd_t = wintypes.HWND(hwnd)
            GWL_STYLE = -16
            WS_MAXIMIZE = 0x01000000
            SWP_NOZORDER = 0x0004
            SWP_NOACTIVATE = 0x0010
            SWP_FRAMECHANGED = 0x0020
            MONITOR_DEFAULTTONEAREST = 2

            if user32.IsZoomed(hwnd_t):
                # 还原：清 WS_MAXIMIZE + SetWindowPos 回保存的矩形
                self._set_window_corner_preference(2)  # ROUND
                style = user32.GetWindowLongPtrW(hwnd_t, GWL_STYLE)
                user32.SetWindowLongPtrW(
                    hwnd_t, GWL_STYLE, ctypes.c_ssize_t(style & ~WS_MAXIMIZE),
                )
                if self._window_restore_bounds:
                    left, top, width, height = self._window_restore_bounds
                    user32.SetWindowPos(
                        hwnd_t, None, left, top, width, height,
                        SWP_NOZORDER | SWP_NOACTIVATE | SWP_FRAMECHANGED,
                    )
                self._window_maximized = False
                return False

            # 最大化：保存当前矩形
            window_rect = wintypes.RECT()
            if not user32.GetWindowRect(hwnd_t, ctypes.byref(window_rect)):
                return self._window_maximized
            self._window_restore_bounds = (
                window_rect.left, window_rect.top,
                window_rect.right - window_rect.left,
                window_rect.bottom - window_rect.top,
            )

            # 用光标位置定位当前屏（用户点最大化按钮时光标在窗口标题栏上）
            cursor = wintypes.POINT()
            user32.GetCursorPos(ctypes.byref(cursor))
            hmon = user32.MonitorFromPoint(cursor, MONITOR_DEFAULTTONEAREST)
            info = _MonitorInfo()
            info.cbSize = ctypes.sizeof(info)
            if not hmon or not user32.GetMonitorInfoW(hmon, ctypes.byref(info)):
                return self._window_maximized
            work = info.rcWork

            # 置 WS_MAXIMIZE + SetWindowPos 到工作区
            self._set_window_corner_preference(1)  # DONOTROUND
            style = user32.GetWindowLongPtrW(hwnd_t, GWL_STYLE)
            user32.SetWindowLongPtrW(
                hwnd_t, GWL_STYLE, ctypes.c_ssize_t(style | WS_MAXIMIZE),
            )
            user32.SetWindowPos(
                hwnd_t, None,
                work.left, work.top,
                work.right - work.left, work.bottom - work.top,
                SWP_NOZORDER | SWP_NOACTIVATE | SWP_FRAMECHANGED,
            )
            self._window_maximized = True
            return True

        # 非 Windows 回退
        if self._window_maximized:
            self._window.restore()
        else:
            self._window.maximize()
        self._window_maximized = not self._window_maximized
        return self._window_maximized

    def _set_window_corner_preference(self, preference: int) -> None:
        """设置 Win11 DWMWA_WINDOW_CORNER_PREFERENCE：1=DONOTROUND（最大化），2=ROUND（还原）。"""
        if self._window is None or self._window.native is None or os.name != "nt":
            return
        hwnd = int(self._window.native.Handle.ToInt64())
        try:
            dwmapi = ctypes.WinDLL("dwmapi", use_last_error=True)
            pref = ctypes.c_int(preference)
            dwmapi.DwmSetWindowAttribute(
                wintypes.HWND(hwnd), ctypes.c_int(33),
                ctypes.byref(pref), ctypes.sizeof(pref),
            )
        except Exception:
            pass

    def _install_native_window_proc(self, *_: Any) -> None:
        """子类化顶层窗口，仅处理 WM_DPICHANGED。

        WM_DPICHANGED：跨屏拖动按新 DPI 缩放物理尺寸。chain 让 WinForms 更新
        DPI 缓存，再用 lparam 建议矩形 SetWindowPos 兜底。

        之前还处理了 WM_NCCALCSIZE / WM_GETMINMAXINFO / WM_WINDOWPOSCHANGING，
        但 debug 实测在 pywebview 嵌入场景下 .NET WinForms 对 SW_MAXIMIZE 走自己的
        路径，绕开外部 wndproc 的这些 handler——所以全删了。最大化改由
        toggle_maximize_window 手动 SetWindowPos 到工作区实现，不依赖 wndproc。
        """
        if self._window is None or self._window.native is None or os.name != "nt":
            return
        hwnd = int(self._window.native.Handle.ToInt64())

        user32 = ctypes.WinDLL("user32", use_last_error=True)
        user32.GetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
        user32.GetWindowLongPtrW.restype = ctypes.c_ssize_t
        user32.SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t]
        user32.SetWindowLongPtrW.restype = ctypes.c_ssize_t
        user32.CallWindowProcW.argtypes = [
            ctypes.c_ssize_t, wintypes.HWND, wintypes.UINT,
            ctypes.c_size_t, ctypes.c_ssize_t,
        ]
        user32.CallWindowProcW.restype = ctypes.c_ssize_t
        user32.SetWindowPos.argtypes = [
            wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
            ctypes.c_int, ctypes.c_int, wintypes.UINT,
        ]
        user32.SetWindowPos.restype = wintypes.BOOL

        self._user32_ref = user32

        GWL_WNDPROC = -4
        WM_DPICHANGED = 0x02E0
        SWP_NOZORDER = 0x0004
        SWP_NOACTIVATE = 0x0010

        WNDPROC = ctypes.WINFUNCTYPE(
            ctypes.c_ssize_t,
            wintypes.HWND, wintypes.UINT,
            ctypes.c_size_t, ctypes.c_ssize_t,
        )
        self._wnd_proc_type = WNDPROC  # 保留类型引用避免 GC

        old_proc = user32.GetWindowLongPtrW(wintypes.HWND(hwnd), GWL_WNDPROC)
        if not old_proc:
            return
        self._old_window_proc = old_proc

        def wndproc(hwnd_val: int, msg: int, wparam: int, lparam: int) -> int:
            if msg == WM_DPICHANGED:
                # 1. chain 给原 wndproc：WinForms 更新 DPI 缓存、触发布局
                result = user32.CallWindowProcW(
                    old_proc, wintypes.HWND(hwnd_val), msg, wparam, lparam,
                )
                # 2. 兜底：用 Windows 建议矩形 SetWindowPos
                try:
                    rect = wintypes.RECT.from_address(lparam)
                    user32.SetWindowPos(
                        wintypes.HWND(hwnd_val), None,
                        rect.left, rect.top,
                        rect.right - rect.left, rect.bottom - rect.top,
                        SWP_NOZORDER | SWP_NOACTIVATE,
                    )
                except Exception:
                    pass
                return result
            return user32.CallWindowProcW(
                old_proc, wintypes.HWND(hwnd_val), msg, wparam, lparam,
            )

        self._wnd_proc_callback = WNDPROC(wndproc)  # 必须持有引用防止 GC
        callback_addr = ctypes.cast(self._wnd_proc_callback, ctypes.c_void_p).value
        user32.SetWindowLongPtrW(
            wintypes.HWND(hwnd), GWL_WNDPROC, ctypes.c_ssize_t(callback_addr or 0),
        )

    def _uninstall_native_window_proc(self, *_: Any) -> None:
        """关闭前还原原 wndproc，避免 Python 回调在 HWND 销毁后被调用导致退出崩溃。"""
        if not getattr(self, "_old_window_proc", 0) or not getattr(self, "_user32_ref", None):
            return
        if self._window is None or self._window.native is None:
            return
        try:
            hwnd = int(self._window.native.Handle.ToInt64())
            self._user32_ref.SetWindowLongPtrW(
                wintypes.HWND(hwnd), -4, ctypes.c_ssize_t(self._old_window_proc),
            )
        except Exception:
            pass

    def close_window(self) -> None:
        if self._window is not None:
            self._window.destroy()

    def apply_window_corners(self, *_: Any) -> None:
        """窗口显示时主动设 Win11 圆角（pywebview frameless 默认可能不带圆角）"""
        if self._window is None or self._window.native is None or os.name != "nt":
            return
        hwnd = int(self._window.native.Handle.ToInt64())
        try:
            dwmapi = ctypes.WinDLL("dwmapi", use_last_error=True)
            # DWMWA_WINDOW_CORNER_PREFERENCE = 33
            # DWMWCP_DEFAULT = 0 / DONOTROUND = 1 / ROUND = 2 / ROUNDSMALL = 3
            corner_pref = ctypes.c_int(2)  # 强制圆角
            dwmapi.DwmSetWindowAttribute(
                wintypes.HWND(hwnd), ctypes.c_int(33),
                ctypes.byref(corner_pref), ctypes.sizeof(corner_pref),
            )
            # DWMWA_BORDER_COLOR = 34; DWMWA_COLOR_NONE = 0xFFFFFFFE。
            # 禁止 Windows 使用系统强调色绘制无边框窗口外沿。
            border_color = ctypes.c_uint(0xFFFFFFFE)
            dwmapi.DwmSetWindowAttribute(
                wintypes.HWND(hwnd), ctypes.c_int(34),
                ctypes.byref(border_color), ctypes.sizeof(border_color),
            )
        except Exception:
            pass

    def start_window_resize(self, edge: str) -> None:
        if self._window is None or self._window.native is None or os.name != "nt":
            return
        hit_tests = {
            "left": 10,
            "right": 11,
            "top": 12,
            "top-left": 13,
            "top-right": 14,
            "bottom": 15,
            "bottom-left": 16,
            "bottom-right": 17,
        }
        hit_test = hit_tests.get(edge)
        if hit_test is None:
            return
        hwnd = int(self._window.native.Handle.ToInt64())
        # Keep the HWND pointer-sized on 64-bit Windows. Without explicit
        # prototypes ctypes treats the integer arguments as 32-bit values,
        # which can truncate the native window handle and silently discard the
        # non-client drag message (most noticeably for the corner handles).
        # Use an isolated DLL handle so these prototypes do not affect the
        # shared user32 functions used internally by pywebview.
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        user32.ReleaseCapture.argtypes = []
        user32.ReleaseCapture.restype = wintypes.BOOL
        user32.GetCursorPos.argtypes = [ctypes.POINTER(wintypes.POINT)]
        user32.GetCursorPos.restype = wintypes.BOOL
        user32.PostMessageW.argtypes = [
            wintypes.HWND,
            wintypes.UINT,
            wintypes.WPARAM,
            wintypes.LPARAM,
        ]
        user32.PostMessageW.restype = wintypes.BOOL
        # 获取当前光标屏幕坐标，打包进 lParam（低 16 位 = x，高 16 位 = y）
        cursor = wintypes.POINT()
        user32.GetCursorPos(ctypes.byref(cursor))
        lparam = ctypes.c_ssize_t((cursor.x & 0xFFFF) | ((cursor.y & 0xFFFF) << 16))
        # 用 PostMessageW 而非 SendMessageW：
        # pywebview 在工作线程调用，SendMessageW 会同步等待主线程处理，易死锁
        # PostMessageW 异步投递到主线程消息队列，主线程消息泵空闲时取出处理
        # 鼠标按下状态此时仍在（用户刚 mousedown），DefWindowProc 收到后启动 resize 循环
        user32.ReleaseCapture()
        user32.PostMessageW(hwnd, 0x00A1, hit_test, lparam)

    def select_image(self) -> dict[str, str] | None:
        if self._window is None:
            return None

        result = self._window.create_file_dialog(
            webview.FileDialog.OPEN,
            allow_multiple=False,
            file_types=("Images (*.png;*.jpg;*.jpeg;*.webp;*.bmp)",),
        )
        if not result:
            return None

        path = Path(result[0]).resolve()
        mime = mimetypes.guess_type(path.name)[0] or "image/png"
        preview = base64.b64encode(path.read_bytes()).decode("ascii")
        return {
            "path": str(path),
            "name": path.name,
            "preview": f"data:{mime};base64,{preview}",
        }

    def select_local_video_file(self) -> dict[str, str] | None:
        if self._window is None:
            return None

        result = self._window.create_file_dialog(
            webview.FileDialog.OPEN,
            allow_multiple=False,
            file_types=("Videos (*.mp4;*.mov;*.m4v;*.webm;*.avi;*.mkv)",),
        )
        if not result:
            return None

        path = Path(result[0]).resolve()
        video_suffixes = {".mp4", ".mov", ".m4v", ".webm", ".avi", ".mkv"}
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        if not path.is_file() or (not content_type.startswith("video/") and path.suffix.lower() not in video_suffixes):
            raise ValueError("请选择 MP4、MOV、M4V、WebM、AVI 或 MKV 视频文件")
        return {"path": str(path), "name": path.name}

    def read_local_media_data_url(self, file_path: str) -> dict[str, str]:
        """Encode a prepared reference file for the Seedance API payload."""

        path = Path(str(file_path or "")).resolve()
        if not path.is_file():
            raise ValueError("参考素材文件不存在")
        if path.stat().st_size > 100 * 1024 * 1024:
            raise ValueError(f"参考素材超过 100MB：{path.name}")
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        if not content_type.startswith(("image/", "audio/", "video/")):
            raise ValueError(f"不支持的 Seedance 参考素材：{path.name}")
        encoded = base64.b64encode(path.read_bytes()).decode("ascii")
        return {
            "url": f"data:{content_type};base64,{encoded}",
            "contentType": content_type,
            "name": path.name,
        }

    def copy_files_to_clipboard(self, file_paths: list[str]) -> dict[str, int]:
        """Copy an ordered list of local files to the Windows clipboard."""

        if os.name != "nt":
            raise ValueError("当前系统不支持复制多张参考图")
        paths = [str(Path(str(value)).resolve()) for value in file_paths]
        if not paths:
            raise ValueError("没有可复制的参考图")
        missing = [path for path in paths if not Path(path).is_file()]
        if missing:
            raise ValueError(f"参考图文件不存在：{Path(missing[0]).name}")

        class DropFiles(ctypes.Structure):
            _fields_ = [
                ("pFiles", wintypes.DWORD),
                ("pt", wintypes.POINT),
                ("fNC", wintypes.BOOL),
                ("fWide", wintypes.BOOL),
            ]

        user32 = ctypes.WinDLL("user32", use_last_error=True)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        user32.OpenClipboard.argtypes = [wintypes.HWND]
        user32.OpenClipboard.restype = wintypes.BOOL
        user32.EmptyClipboard.restype = wintypes.BOOL
        user32.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]
        user32.SetClipboardData.restype = wintypes.HANDLE
        kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
        kernel32.GlobalAlloc.restype = wintypes.HGLOBAL
        kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
        kernel32.GlobalLock.restype = ctypes.c_void_p
        kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
        kernel32.GlobalFree.argtypes = [wintypes.HGLOBAL]

        payload = ("\0".join(paths) + "\0\0").encode("utf-16-le")
        header = DropFiles()
        header.pFiles = ctypes.sizeof(DropFiles)
        header.fWide = True
        memory_size = ctypes.sizeof(DropFiles) + len(payload)
        handle = kernel32.GlobalAlloc(0x0002, memory_size)
        if not handle:
            raise ValueError("无法分配剪贴板内存")

        clipboard_open = False
        ownership_transferred = False
        try:
            pointer = kernel32.GlobalLock(handle)
            if not pointer:
                raise ValueError("无法写入剪贴板内存")
            try:
                ctypes.memmove(pointer, ctypes.byref(header), ctypes.sizeof(DropFiles))
                ctypes.memmove(pointer + ctypes.sizeof(DropFiles), payload, len(payload))
            finally:
                kernel32.GlobalUnlock(handle)

            for _ in range(10):
                if user32.OpenClipboard(None):
                    clipboard_open = True
                    break
                time.sleep(0.05)
            if not clipboard_open:
                raise ValueError("剪贴板正被其他程序占用，请稍后重试")
            if not user32.EmptyClipboard():
                raise ValueError("无法清空剪贴板")
            if not user32.SetClipboardData(15, handle):
                raise ValueError("无法复制参考图到剪贴板")
            ownership_transferred = True
            return {"count": len(paths)}
        finally:
            if clipboard_open:
                user32.CloseClipboard()
            if not ownership_transferred:
                kernel32.GlobalFree(handle)

    def start_generation(self, payload: dict[str, Any]) -> dict[str, str]:
        raw_attachments = payload.get("attachments")
        attachments: list[dict[str, Any]] = []
        if isinstance(raw_attachments, list):
            for item in raw_attachments:
                if not isinstance(item, dict) or not str(item.get("path", "")).strip():
                    continue
                attachments.append({
                    "path": Path(str(item["path"])),
                    "type": "audio" if item.get("type") == "audio" else "image",
                })
        if not attachments:
            raw_image_paths = payload.get("imagePaths")
            if not isinstance(raw_image_paths, list):
                raw_image_paths = []
            image_paths = [Path(str(path)) for path in raw_image_paths if str(path).strip()]
            if not image_paths:
                image_paths = [Path(str(payload.get("imagePath", "")))]
            raw_audio_paths = payload.get("audioPaths")
            if not isinstance(raw_audio_paths, list):
                raw_audio_paths = []
            audio_paths = [Path(str(path)) for path in raw_audio_paths if str(path).strip()]
            attachments = [
                *({"path": path, "type": "image"} for path in image_paths),
                *({"path": path, "type": "audio"} for path in audio_paths),
            ]
        prompt = str(payload.get("prompt", "")).strip()
        preferred_account_id = str(payload.get("accountId") or self.get_settings()["defaultAccountId"])
        auto_assign_account = bool(payload.get("autoAssignAccount", True))

        missing_attachment = next((item for item in attachments if not item["path"].is_file()), None)
        if missing_attachment is not None:
            missing_path = missing_attachment["path"]
            label = "音频文件" if missing_attachment["type"] == "audio" else "参考图片"
            raise ValueError(f"{label}不存在：{missing_path.name or missing_path}")
        if not any(item["type"] == "image" for item in attachments):
            raise ValueError("当前分镜至少需要一张参考图片")
        if not prompt:
            raise ValueError("请输入视频描述")
        if not auto_assign_account:
            if not preferred_account_id:
                raise ValueError("请先在设置中选择生成账号")
            account = self._find_account(preferred_account_id)
            if str(account.get("quotaExhaustedOn") or "") == date.today().isoformat():
                raise ValueError("该生成账号今日视频额度已用完，请切换其他账号或明日再试")
            if getattr(self, "_login_expired", {}).get(str(preferred_account_id)):
                raise ValueError("该生成账号登录已过期，请重新登录后再试")

        task_id = uuid.uuid4().hex[:10]
        staging_dir = DATA_DIR / "generation_inputs" / task_id
        staging_dir.mkdir(parents=True, exist_ok=True)
        staged_attachments: list[dict[str, str]] = []
        for index, attachment in enumerate(attachments, start=1):
            source_path: Path = attachment["path"]
            attachment_type = str(attachment["type"])
            prefix = "文件" if attachment_type == "audio" else "图"
            suffix = source_path.suffix or (".mp3" if attachment_type == "audio" else ".png")
            target_path = staging_dir / f"{prefix}{index}{suffix.lower()}"
            shutil.copy2(source_path, target_path)
            staged_attachments.append({"path": str(target_path.resolve()), "type": attachment_type})
        image_paths = [Path(item["path"]) for item in staged_attachments if item["type"] == "image"]
        audio_paths = [Path(item["path"]) for item in staged_attachments if item["type"] == "audio"]
        try:
            if auto_assign_account:
                account = self._acquire_available_generation_account(preferred_account_id, task_id)
                account_id = str(account.get("id") or "")
            else:
                account_id = preferred_account_id
                account = self._find_account(account_id)
                self._acquire_account_usage(account_id, task_id, "generation")
        except Exception:
            shutil.rmtree(staging_dir, ignore_errors=True)
            raise
        with self._lock:
            self._tasks[task_id] = {
                "id": task_id,
                "status": "queued",
                "statusText": "任务已创建",
                "progress": 4,
                "imageName": image_paths[0].name,
                "imageNames": [path.name for path in image_paths],
                "audioNames": [path.name for path in audio_paths],
                "prompt": prompt,
                "ratio": payload.get("ratio", "16:9"),
                "duration": payload.get("duration", 5),
                "model": payload.get("model", "Seedance 2.0 Fast"),
                "accountId": account_id,
                "accountName": str(account.get("name") or account_id),
                "demo": False,
                "requiresManualVerification": False,
                "resultWatermarked": False,
                "conversationId": "",
                "conversationUrl": "",
                "generationSubmittedAt": 0,
            }

        # 豆包风控不认可隐藏窗口，自动化始终使用可见浏览器窗口。
        desired_visible = True
        with self._lock:
            worker = self._workers.get(account_id)
        if worker is not None and worker.visible != desired_visible:
            worker.stop()
            worker.thread.join(timeout=8)
            worker = None
        try:
            worker = worker or self._ensure_worker(account_id, visible=desired_visible)
        except Exception as exc:
            self._update_task(
                task_id,
                status="failed",
                statusText=f"启动 OriginalDoubao 浏览器失败：{exc}",
                progress=0,
            )
            raise
        if not worker.ready.wait(timeout=20):
            self._update_task(task_id, status="failed", statusText="启动 OriginalDoubao 浏览器超时", progress=0)
            return {"taskId": task_id, "accountId": account_id}
        if worker.start_error:
            self._update_task(task_id, status="failed", statusText=f"启动 OriginalDoubao 浏览器失败：{worker.start_error}", progress=0)
            return {"taskId": task_id, "accountId": account_id}
        worker.submit_generation(
            task_id,
            {
                **payload,
                "imagePath": str(image_paths[0]),
                "imagePaths": [str(path) for path in image_paths],
                "audioPaths": [str(path) for path in audio_paths],
                "attachments": staged_attachments,
                "prompt": prompt,
            },
        )
        return {"taskId": task_id, "accountId": account_id}

    def get_task(self, task_id: str) -> dict[str, Any] | None:
        with self._lock:
            task = self._tasks.get(task_id)
            return dict(task) if task else None

    def convert_original_doubao_link(self, link: str, account_id: str = "") -> dict[str, str]:
        clean_link = str(link).strip()
        selected_account_id = str(account_id or self.get_settings()["defaultAccountId"])
        if not clean_link:
            raise ValueError("请粘贴视频分享链接")
        if not is_supported_conversion_url(clean_link):
            raise ValueError("请输入官方视频分享链接或抖音视频直链")
        if not selected_account_id:
            raise ValueError("请先选择生成账号")
        self._find_account(selected_account_id)
        if getattr(self, "_login_expired", {}).get(selected_account_id):
            raise ValueError("该生成账号登录已过期，请重新登录后再试")
        usage_id = f"conversion-{uuid.uuid4().hex[:10]}"
        self._acquire_account_usage(selected_account_id, usage_id, "conversion")

        try:
            desired_visible = True
            with self._lock:
                worker = self._workers.get(selected_account_id)
            if worker is not None and worker.visible != desired_visible:
                worker.stop()
                worker.thread.join(timeout=8)
                worker = None
            worker = worker or self._ensure_worker(selected_account_id, visible=desired_visible)
            if not worker.ready.wait(timeout=20):
                raise RuntimeError("启动转换服务超时")
            if worker.start_error:
                raise RuntimeError(f"启动转换服务失败：{worker.start_error}")

            reply: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=1)
            worker.submit_link_conversion(clean_link, reply)
            try:
                result = reply.get(timeout=900)
            except queue.Empty as exc:
                raise TimeoutError("链接转换超时，请稍后重试") from exc
            if not result.get("success"):
                raise ValueError(str(result.get("error") or "链接转换失败"))
            return dict(result["data"])
        finally:
            self._release_account_usage(selected_account_id, usage_id)

    def get_app_info(self) -> dict[str, Any]:
        profile_dir = DATA_DIR / "doubao_profile"
        profile_dir.mkdir(parents=True, exist_ok=True)
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        return {
            "mode": "browser",
            "apiBase": STORAGE_API_BASE_URL,
            "storageBase": STORAGE_API_BASE_URL,
            "storageReady": self._storage_available(),
            "profileDir": str(profile_dir),
            "outputDir": str(OUTPUT_DIR),
        }

    def list_accounts(self, token: str = "") -> list[dict[str, Any]]:
        self._ensure_cloud_accounts_synced(token)
        self._pull_cloud_account_quota(token)
        accounts = self._read_accounts()
        with self._lock:
            workers = dict(self._workers)
            usage = {key: dict(value) for key, value in self._account_usage.items()}
            login_expired = dict(self._login_expired)
        result = []
        login_history_changed = False
        today = date.today().isoformat()
        for stored_account in accounts:
            account = dict(stored_account)
            account_id = str(account.get("id") or "")
            daily_quota = self._account_daily_quota(account)
            generated_today = (
                self._non_negative_int(account.get("generatedToday"), 0)
                if str(account.get("quotaUsageDate") or "") == today
                else 0
            )
            worker = workers.get(account_id)
            authenticated = worker.authenticated if worker is not None else None
            if authenticated is None:
                authenticated = self._has_saved_original_doubao_session(account_id)
            account["authenticated"] = bool(authenticated)
            account["loginExpired"] = bool(login_expired.get(account_id))
            account["dailyQuota"] = daily_quota
            account["generatedToday"] = min(generated_today, daily_quota)
            account["quotaRemainingToday"] = max(0, daily_quota - generated_today)
            account["quotaExhaustedToday"] = (
                str(account.get("quotaExhaustedOn") or "") == today
                or generated_today >= daily_quota
            )
            if account["quotaExhaustedToday"]:
                account["quotaRemainingToday"] = 0
            account_usage = usage.get(account_id)
            account["inUse"] = account_usage is not None
            account["usageType"] = str((account_usage or {}).get("type") or "")
            if authenticated:
                if not stored_account.get("hasLoggedIn"):
                    stored_account["hasLoggedIn"] = True
                    login_history_changed = True
                account["hasLoggedIn"] = True
            if account["inUse"]:
                account["status"] = "运行中 · 账号已锁定"
            elif account["quotaExhaustedToday"]:
                account["status"] = "今日额度已用完 · 明日自动恢复"
            elif login_expired.get(account_id):
                account["status"] = "登录已过期 · 请重新登录"
            elif authenticated:
                account["status"] = "已登录 · 状态已保存"
            elif worker is not None:
                account["status"] = "登录窗口已打开 · 等待登录"
            elif account.get("hasLoggedIn"):
                account["status"] = "已登录过 · 当前设备需登录"
            else:
                account["status"] = "未登录"
            result.append(account)
        if login_history_changed:
            self._write_accounts(accounts)
            self._push_cloud_account_state(token)
        return result

    def reorder_accounts(self, account_ids: list[str], token: str = "") -> dict[str, Any]:
        self._ensure_cloud_accounts_synced(token)
        if not isinstance(account_ids, list):
            raise ValueError("账号顺序格式不正确")
        ordered_ids = [str(account_id or "").strip() for account_id in account_ids]
        accounts = self._read_accounts()
        stored_ids = [str(account.get("id") or "") for account in accounts]
        if (
            len(ordered_ids) != len(stored_ids)
            or len(set(ordered_ids)) != len(ordered_ids)
            or set(ordered_ids) != set(stored_ids)
        ):
            raise ValueError("账号列表已发生变化，请刷新后重试")
        accounts_by_id = {str(account.get("id") or ""): account for account in accounts}
        ordered_accounts = []
        for sort_order, account_id in enumerate(ordered_ids):
            account = accounts_by_id[account_id]
            account["sortOrder"] = sort_order
            ordered_accounts.append(account)
        self._write_accounts(ordered_accounts)
        cloud_synced = self._push_cloud_account_state(token)
        return {"accountIds": ordered_ids, "cloudSynced": cloud_synced}

    def _has_saved_original_doubao_session(self, account_id: str) -> bool:
        cookie_db = ACCOUNTS_DIR / account_id / "profile" / "Default" / "Network" / "Cookies"
        if not cookie_db.is_file():
            return False
        try:
            connection = sqlite3.connect(
                f"file:{cookie_db.resolve().as_posix()}?mode=ro&immutable=1",
                uri=True,
                timeout=1,
            )
            try:
                # 只认 sessionid / sessionid_ss：sid_guard 等辅助 cookie 有效期长达一年，
                # 单独存在不能证明已登录，否则 sessionid 已过期的账号会被误判为「已登录」。
                # expires_utc 为 Chrome 时间（1601-01-01 起微秒），0 表示 session cookie。
                now_chrome = int((time.time() + 11644473600) * 1_000_000)
                row = connection.execute(
                    """
                    SELECT 1 FROM cookies
                    WHERE host_key LIKE '%doubao.com%'
                      AND name IN ('sessionid', 'sessionid_ss')
                      AND (length(value) > 0 OR length(encrypted_value) > 0)
                      AND (expires_utc = 0 OR expires_utc > ?)
                    LIMIT 1
                    """,
                    (now_chrome,),
                ).fetchone()
                return row is not None
            finally:
                connection.close()
        except sqlite3.Error:
            return False

    # ===== HTTP 探活：缓存 cookie + 直接请求 OriginalDoubao，避免每次校验都开浏览器 =====
    # Chrome 132+ 的 cookie 用 app-bound encryption 加密，DPAPI+AES-GCM 解不开。
    # 改为让 worker 启动时把 context.cookies() 序列化到 JSON，后续校验直接 HTTP 探活。
    # 工作流：
    #   1. 优先 HTTP 校验（不开浏览器）
    #   2. 缓存不存在或 HTTP 判定 cookie 失效 → fallback 浏览器校验，成功后刷新缓存
    #   3. 浏览器校验也失败 → 抛错给前端
    _ORIGINAL_DOUBAO_HTTP_USER_AGENT = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36"
    )

    @staticmethod
    def _account_cookie_cache_path(account_id: str) -> Path:
        return ACCOUNTS_DIR / account_id / "profile" / "http_cookies.json"

    def _save_account_cookies_cache(self, account_id: str, cookies: list[dict[str, Any]]) -> None:
        """worker 把 context.cookies([ORIGINAL_DOUBAO_URL]) 序列化到 JSON 供后续 HTTP 校验复用。"""
        cache_path = self._account_cookie_cache_path(account_id)
        try:
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "savedAt": int(time.time()),
                "cookies": [
                    {
                        "name": str(c.get("name") or ""),
                        "value": str(c.get("value") or ""),
                        "domain": str(c.get("domain") or ""),
                        "path": str(c.get("path") or "/"),
                        "expires": int(c.get("expires") or 0),
                        "httpOnly": bool(c.get("httpOnly")),
                        "secure": bool(c.get("secure")),
                    }
                    for c in cookies
                    if c.get("name") and c.get("value")
                ],
            }
            cache_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        except OSError:
            pass

    # 真正的登录凭证只有 sessionid / sessionid_ss；sid_guard、uid_tt 等只是辅助
    # cookie（有效期可长达一年），单独存在不能证明已登录，否则过期的账号会被误判为正常。
    _LOGIN_SESSION_COOKIE_NAMES = ("sessionid", "sessionid_ss")

    def _load_account_cookies_cache(self, account_id: str) -> dict[str, str] | None:
        """读 cookie 缓存为 {name: value} 字典。无缓存或空返回 None。

        已过期的 cookie 会被剔除；若 sessionid / sessionid_ss 因过期而全部被剔除，
        结果里就不会再有登录凭证，调用方据此判定为「登录已过期」。
        """
        cache_path = self._account_cookie_cache_path(account_id)
        if not cache_path.is_file():
            return None
        try:
            payload = json.loads(cache_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        cookies = payload.get("cookies") if isinstance(payload, dict) else None
        if not isinstance(cookies, list) or not cookies:
            return None
        result: dict[str, str] = {}
        now = int(time.time())
        for cookie in cookies:
            if not isinstance(cookie, dict):
                continue
            name = str(cookie.get("name") or "")
            value = str(cookie.get("value") or "")
            if not name or not value:
                continue
            expires = int(cookie.get("expires") or 0)
            # expires=0 / -1 视为 session cookie（不过期）；其他过期时间已过则跳过
            if expires > 0 and expires < now:
                continue
            result[name] = value
        return result or None

    def _http_check_login(self, account_id: str) -> dict[str, Any] | None:
        """带真实 UA + Referer + Cookie 请求 OriginalDoubao 首页，根据 SSR 数据判断登录态。

        返回 None 表示 HTTP 校验不可用（无缓存 cookie / 网络错 / 无法判定）；
        返回 dict 表示判定完成，调用方据 loggedIn 字段决定是否还要 fallback 浏览器。
        """
        cookies = self._load_account_cookies_cache(account_id)
        if not cookies:
            # 无缓存：worker 从未启动过，fallback 浏览器首次写入缓存
            return None
        # 只有 sessionid / sessionid_ss 才能证明已登录。sid_guard 等辅助 cookie 有效期
        # 长达一年，若把它们也算作登录凭证，sessionid 已过期的账号会被误判为「正常」。
        if not any(name in self._LOGIN_SESSION_COOKIE_NAMES for name in cookies):
            # 缓存里没有有效的会话凭证：要么从未登录，要么 sessionid 已过期被剔除。
            # 客户端这边已无可用的登录态，直接判未登录，不开浏览器。
            # 用户看到后可主动点「重新登录」开浏览器复测并刷新缓存。
            return {
                "loggedIn": False,
                "hasSessionCookie": False,
                "url": ORIGINAL_DOUBAO_URL,
                "reason": "no_session_cookie_in_cache",
            }
        headers = {
            "User-Agent": self._ORIGINAL_DOUBAO_HTTP_USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9",
            "Referer": "https://www.doubao.com/",
            "Sec-Fetch-Site": "same-origin",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-User": "?1",
            "Upgrade-Insecure-Requests": "1",
        }
        try:
            response = httpx.get(
                ORIGINAL_DOUBAO_URL,
                headers=headers,
                cookies=cookies,
                follow_redirects=False,
                timeout=15,
            )
        except (httpx.HTTPError, OSError):
            return None
        # 302 重定向到 login → 未登录
        if response.status_code in (301, 302, 303, 307, 308):
            location = response.headers.get("location", "").lower()
            # 只有跳转到 login / passport 才判未登录；跳到站内其它页面（如 /chat）
            # 说明 sessionid 被服务端接受，视为已登录。
            return {
                "loggedIn": "login" not in location and "passport" not in location,
                "hasSessionCookie": True,
                "url": response.headers.get("location", ORIGINAL_DOUBAO_URL),
                "reason": "redirect",
            }
        if response.status_code != 200:
            return None
        text = response.text or ""
        # 优先抓 SSR 数据里的登录态标记
        m_state = re.search(r'"loginStatus"\s*:\s*(true|false|1|0)', text) \
            or re.search(r'"isLogin"\s*:\s*(true|false|1|0)', text)
        if m_state:
            logged_in = m_state.group(1) in ("true", "1")
            return {"loggedIn": logged_in, "hasSessionCookie": True, "url": ORIGINAL_DOUBAO_URL, "reason": "ssr_login_status"}
        m_user = re.search(r'"userInfo"\s*:\s*(null|\{)', text)
        if m_user:
            logged_in = m_user.group(1) == "{"
            return {"loggedIn": logged_in, "hasSessionCookie": True, "url": ORIGINAL_DOUBAO_URL, "reason": "ssr_user_info"}
        # 兜底：抓不到 SSR 登录态字段时不能凭「HTML 是否含登录入口」判定，
        # OriginalDoubao 首页即便已登录也可能含 passport/login 链接。返回 None 让浏览器兜底。
        return None

    def get_settings(self) -> dict[str, Any]:
        defaults = {
            "defaultAccountId": "",
            "outputDir": str(OUTPUT_DIR.resolve()),
            "storageDir": str(STORAGE_DIR.resolve()),
            "autoDownload": True,
            "accountCloudMigrated": False,
            "accountLocalMigrated": False,
            "dailyVideoQuota": 3,
        }
        if not SETTINGS_FILE.exists():
            return defaults
        try:
            saved = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
            if isinstance(saved, dict):
                defaults.update({key: saved[key] for key in defaults if key in saved})
        except (OSError, json.JSONDecodeError):
            pass
        return defaults

    def save_settings(self, settings: dict[str, Any], token: str = "") -> dict[str, Any]:
        current = self.get_settings()
        previous_storage_dir = Path(str(current["storageDir"])).expanduser().resolve()
        current["defaultAccountId"] = str(settings.get("defaultAccountId", ""))
        output_dir = Path(str(settings.get("outputDir", current["outputDir"]))).expanduser().resolve()
        output_dir.mkdir(parents=True, exist_ok=True)
        current["outputDir"] = str(output_dir)
        storage_dir = Path(str(settings.get("storageDir", current["storageDir"]))).expanduser().resolve()
        storage_dir.mkdir(parents=True, exist_ok=True)
        current["storageDir"] = str(storage_dir)
        current["autoDownload"] = bool(settings.get("autoDownload", True))
        current["dailyVideoQuota"] = max(
            1,
            min(self._non_negative_int(settings.get("dailyVideoQuota"), current.get("dailyVideoQuota", 3)), 99),
        )
        current["accountCloudMigrated"] = bool(
            settings.get("accountCloudMigrated", current.get("accountCloudMigrated", False))
        )
        current["accountLocalMigrated"] = bool(
            settings.get("accountLocalMigrated", current.get("accountLocalMigrated", False))
        )
        self._write_settings(current)
        self._push_cloud_account_state(token)
        active_storage = getattr(self, "_local_storage_server", None)
        active_root = active_storage.storage.root if active_storage is not None else previous_storage_dir
        return {**current, "storageRestartRequired": storage_dir != active_root}

    def select_account(self, account_id: str, token: str = "") -> dict[str, Any]:
        self._ensure_cloud_accounts_synced(token)
        selected_id = str(account_id or "").strip()
        if selected_id and not any(item.get("id") == selected_id for item in self._read_accounts()):
            raise ValueError("账号不存在，请刷新账号列表")
        settings = self.get_settings()
        settings["defaultAccountId"] = selected_id
        self._write_settings(settings)
        self._push_cloud_account_state(token)
        return settings

    def mark_account_login_expired(self, account_id: str) -> None:
        with self._lock:
            self._login_expired[account_id] = True

    def mark_account_quota_exhausted(
        self,
        account_id: str,
        token: str = "",
        reason: str = "",
    ) -> bool:
        clean_account_id = str(account_id or "").strip()
        today = date.today().isoformat()
        accounts = self._read_accounts()
        account = next((item for item in accounts if item.get("id") == clean_account_id), None)
        if account is None:
            return False
        if (
            account.get("quotaExhaustedOn") != today
            or account.get("quotaUsageDate") != today
            or self._non_negative_int(account.get("generatedToday"), 0) < self._account_daily_quota(account)
        ):
            account["quotaExhaustedOn"] = today
            account["quotaUsageDate"] = today
            account["generatedToday"] = self._account_daily_quota(account)
            self._write_accounts(accounts)
            self._push_cloud_account_state(token)
        self._set_cloud_account_quota_status(account, today, True, reason, token)
        return True

    def set_account_quota(self, account_id: str, exhausted: bool, token: str = "") -> dict[str, Any]:
        clean_account_id = str(account_id or "").strip()
        accounts = self._read_accounts()
        account = next((item for item in accounts if item.get("id") == clean_account_id), None)
        if account is None:
            raise ValueError("账号不存在，请刷新账号列表")
        today = date.today().isoformat()
        is_exhausted = bool(exhausted)
        reason = (
            "用户在设置中心手动标记今日额度已用完"
            if is_exhausted
            else "用户在设置中心手动恢复今日额度"
        )
        if not self._set_cloud_account_quota_status(
            account,
            today,
            is_exhausted,
            reason,
            token,
        ):
            raise ValueError("云端额度状态同步失败，请检查网络或登录状态后重试")
        account["quotaExhaustedOn"] = today if is_exhausted else ""
        account["quotaUsageDate"] = today
        account["generatedToday"] = self._account_daily_quota(account) if is_exhausted else 0
        self._write_accounts(accounts)
        self._push_cloud_account_state(token)
        return {"id": clean_account_id, "quotaExhaustedToday": is_exhausted}

    def set_account_daily_quota(self, account_id: str, daily_quota: int, token: str = "") -> dict[str, Any]:
        clean_account_id = str(account_id or "").strip()
        accounts = self._read_accounts()
        account = next((item for item in accounts if item.get("id") == clean_account_id), None)
        if account is None:
            raise ValueError("账号不存在，请刷新账号列表")
        limit = max(1, min(self._non_negative_int(daily_quota, 3), 99))
        today = date.today().isoformat()
        settings = self.get_settings()
        settings["dailyVideoQuota"] = limit
        self._write_settings(settings)
        for item in accounts:
            generated = (
                min(self._non_negative_int(item.get("generatedToday"), 0), limit)
                if str(item.get("quotaUsageDate") or "") == today
                else 0
            )
            item["dailyQuota"] = limit
            item["quotaUsageDate"] = today
            item["generatedToday"] = generated
            item["quotaExhaustedOn"] = today if generated >= limit else ""
        self._write_accounts(accounts)
        generated = self._non_negative_int(account.get("generatedToday"), 0)
        exhausted = generated >= limit
        return {
            "id": clean_account_id,
            "dailyQuota": limit,
            "generatedToday": generated,
            "quotaRemainingToday": 0 if exhausted else max(0, limit - generated),
            "quotaExhaustedToday": exhausted,
        }

    def release_account(self, account_id: str) -> dict[str, Any]:
        clean_account_id = str(account_id or "").strip()
        self._find_account(clean_account_id)
        with self._lock:
            released = self._account_usage.pop(clean_account_id, None)
            owner_id = str((released or {}).get("ownerId") or "")
            task = self._tasks.get(owner_id)
            if task is not None and task.get("status") not in {"succeeded", "failed"}:
                task.update({
                    "status": "failed",
                    "statusText": "账号已在设置中心手动释放；远端已提交的任务可能仍会继续运行",
                    "progress": 0,
                    "manuallyReleased": True,
                })
        return {"id": clean_account_id, "released": released is not None}

    def is_account_quota_exhausted_today(self, account_id: str) -> bool:
        account = next(
            (item for item in self._read_accounts() if item.get("id") == str(account_id or "").strip()),
            None,
        )
        if not account:
            return False
        today = date.today().isoformat()
        generated = self._non_negative_int(account.get("generatedToday"), 0) if account.get("quotaUsageDate") == today else 0
        return bool(account.get("quotaExhaustedOn") == today or generated >= self._account_daily_quota(account))

    def select_output_directory(self) -> str | None:
        if self._window is None:
            return None
        result = self._window.create_file_dialog(webview.FileDialog.FOLDER)
        return str(Path(result[0]).resolve()) if result else None

    def select_storage_directory(self) -> str | None:
        if self._window is None:
            return None
        result = self._window.create_file_dialog(webview.FileDialog.FOLDER)
        return str(Path(result[0]).resolve()) if result else None

    def open_output_directory(self) -> bool:
        output_dir = Path(self.get_settings()["outputDir"]).resolve()
        output_dir.mkdir(parents=True, exist_ok=True)
        os.startfile(output_dir)
        return True

    def open_storage_directory(self) -> bool:
        storage_dir = Path(self.get_settings()["storageDir"]).resolve()
        storage_dir.mkdir(parents=True, exist_ok=True)
        os.startfile(storage_dir)
        return True

    def open_path(self, target: str) -> bool:
        """在系统资源管理器中打开任意本地路径（文件或目录）。"""
        path = Path(str(target or "")).expanduser().resolve()
        if not path.exists():
            raise ValueError("路径不存在")
        os.startfile(path)
        return True

    @staticmethod
    def _project_tree_root() -> Path:
        """项目文件目录树的默认根目录。

        源码开发态（客户端与 comic-drama-storage 等模块同级）取仓库根；
        安装态回退到客户端数据目录，保证目录树永远有合理的浏览起点。
        """
        candidate = ROOT.parent
        if (candidate / "comic-drama-storage").is_dir() or (candidate / "comic-drama-boot").is_dir():
            return candidate
        return DATA_DIR

    def project_tree_root(self) -> dict[str, Any]:
        """返回目录树默认根目录，供前端初始化展示。"""
        return {"path": str(self._project_tree_root().resolve())}

    def list_directory(self, target: str = "", show_build: bool = False) -> dict[str, Any]:
        """列出目录内容，供项目文件目录树懒加载展开。

        默认隐藏构建 / 依赖目录（target、node_modules 等）与点前缀隐藏项；
        ``show_build=True`` 时全部显示（例如需要取 target 下的 jar 时）。
        目录排在文件前面，各自按名称排序。
        """
        root = self._project_tree_root().resolve()
        raw = Path(str(target or "")).expanduser()
        path = root if not str(target or "").strip() else raw.resolve()
        if not path.is_dir():
            raise ValueError("目录不存在")
        try:
            children = list(path.iterdir())
        except OSError as error:
            raise ValueError(f"无法读取目录：{error}") from error
        entries: list[dict[str, Any]] = []
        for child in sorted(children, key=lambda item: (not item.is_dir(), item.name.lower())):
            name = child.name
            if not show_build and (name in PROJECT_TREE_HIDDEN_NAMES or name.startswith(".")):
                continue
            try:
                stat = child.stat()
                is_dir = child.is_dir()
            except OSError:
                continue
            entries.append({
                "name": name,
                "path": str(child),
                "isDir": is_dir,
                "size": 0 if is_dir else stat.st_size,
                "modifiedAt": int(stat.st_mtime * 1000),
            })
        return {
            "path": str(path),
            "name": path.name or str(path),
            "parent": "" if path == root else str(path.parent),
            "atRoot": path == root,
            "entries": entries,
        }

    def reveal_path(self, target: str) -> bool:
        """在资源管理器中打开所在文件夹并选中该文件/目录（点击直接跳转）。"""
        path = Path(str(target or "")).expanduser().resolve()
        if not path.exists():
            raise ValueError("路径不存在")
        if os.name == "nt":
            subprocess.run(["explorer", f"/select,{path}"], check=False)
            return True
        os.startfile(path.parent if path.is_file() else path)
        return True

    def select_tree_directory(self) -> str | None:
        """为项目文件目录树选择一个新的根目录。"""
        if self._window is None:
            return None
        result = self._window.create_file_dialog(webview.FileDialog.FOLDER)
        return str(Path(result[0]).resolve()) if result else None

    def package_project_videos(
        self,
        project_name: str,
        videos: list[dict[str, Any]],
        token: str = "",
    ) -> dict[str, Any]:
        """按分镜顺序把项目成片打包到视频输出目录下的项目子文件夹。

        目录结构：<outputDir>/<项目名>/<可选前缀>01.mp4、<可选前缀>02.mp4、...
        """
        if not isinstance(videos, list) or not videos:
            raise ValueError("当前项目没有可打包的成片")

        # 1. 读取运行设置中的视频输出目录
        output_dir = Path(self.get_settings()["outputDir"]).expanduser().resolve()
        output_dir.mkdir(parents=True, exist_ok=True)

        # 2. 项目名做安全处理，去掉 Windows 不允许的字符
        raw_name = str(project_name or "未命名项目").strip() or "未命名项目"
        safe_name = re.sub(r'[\\/:*?"<>|\r\n\t]+', "_", raw_name).strip().strip(".") or "未命名项目"
        project_dir = output_dir / safe_name
        # 若已存在同名目录，追加 (2)、(3) 后缀避免覆盖之前的打包结果
        if project_dir.exists():
            suffix = 2
            while (output_dir / f"{safe_name} ({suffix})").exists():
                suffix += 1
            project_dir = output_dir / f"{safe_name} ({suffix})"
        project_dir.mkdir(parents=True, exist_ok=True)

        # 3. 鉴权 token
        active_token = str(token or self._read_auth().get("token") or "")
        if not active_token:
            raise ValueError("登录状态已失效，请重新登录")

        clean_sequence_prefix = str(videos[0].get("sequencePrefix") or "").strip()
        if clean_sequence_prefix and not clean_sequence_prefix.isdigit():
            raise ValueError("视频序号前缀只能包含数字")
        clean_sequence_prefix = clean_sequence_prefix[:8]

        saved: list[dict[str, Any]] = []
        skipped: list[dict[str, Any]] = []
        total = len(videos)
        for index, item in enumerate(videos, start=1):
            file_id = str(item.get("fileId") or "").strip()
            title = str(item.get("title") or f"成片 {index}").strip()
            if not file_id:
                skipped.append({"index": index, "title": title, "reason": "缺少文件 ID"})
                continue
            try:
                response = self._file_request(
                    "GET",
                    file_id,
                    headers=self._auth_headers(active_token),
                    timeout=300,
                )
                response.raise_for_status()
            except httpx.TimeoutException as exc:
                skipped.append({"index": index, "title": title, "reason": "下载超时"})
                continue
            except httpx.HTTPError as exc:
                skipped.append({"index": index, "title": title, "reason": f"下载失败：{exc}"})
                continue

            content_type = response.headers.get("content-type", "").split(";", 1)[0].strip()
            suffix = mimetypes.guess_extension(content_type) or ".mp4"
            if suffix == ".jpe":
                suffix = ".jpg"
            # 视频常见扩展名兜底
            if suffix.lower() not in {".mp4", ".mov", ".m4v", ".webm", ".avi", ".mkv"}:
                suffix = ".mp4"

            target_name = f"{clean_sequence_prefix}{index:02d}{suffix}"
            target_path = project_dir / target_name
            try:
                target_path.write_bytes(response.content)
            except OSError as exc:
                skipped.append({"index": index, "title": title, "reason": f"写入失败：{exc}"})
                continue
            saved.append({"index": index, "title": title, "path": str(target_path), "name": target_name})

        return {
            "success": True,
            "projectDir": str(project_dir),
            "total": total,
            "saved": saved,
            "skipped": skipped,
        }

    def save_video_as(self, source_path: str, suggested_name: str = "") -> dict[str, Any] | None:
        """Copy a generated local video through the native Save As dialog."""

        if self._window is None:
            raise RuntimeError("桌面窗口尚未就绪")

        source = Path(str(source_path or "")).resolve()
        video_suffixes = {".mp4", ".mov", ".m4v", ".webm", ".avi", ".mkv"}
        if not source.is_file() or source.suffix.lower() not in video_suffixes:
            raise ValueError("转换结果文件不存在或不是受支持的视频")

        safe_name = Path(str(suggested_name or source.name)).name.strip() or source.name
        safe_name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", safe_name).strip(" .") or source.name
        # The operation copies bytes without transcoding, so keep the real media
        # extension even if a stale UI result supplied a different filename.
        if Path(safe_name).suffix.lower() != source.suffix.lower():
            safe_name = f"{Path(safe_name).stem or source.stem}{source.suffix}"

        # The converted video already exists in source.parent. Reusing its name
        # makes the native dialog immediately ask for overwrite confirmation,
        # which feels like a second Save As dialog. Suggest a free copy name
        # while still letting the user choose any destination or filename.
        dialog_name = safe_name
        if (source.parent / dialog_name).exists():
            stem = Path(safe_name).stem or source.stem
            dialog_name = f"{stem}_副本{source.suffix}"
            copy_index = 2
            while (source.parent / dialog_name).exists():
                dialog_name = f"{stem}_副本 ({copy_index}){source.suffix}"
                copy_index += 1

        result = self._window.create_file_dialog(
            webview.FileDialog.SAVE,
            directory=str(source.parent),
            save_filename=dialog_name,
            file_types=(
                f"Video files (*{source.suffix.lower()})",
                "All files (*.*)",
            ),
        )
        if not result:
            return None

        target = Path(result[0]).resolve()
        if target.suffix.lower() != source.suffix.lower():
            target = target.with_suffix(source.suffix)
        if target == source:
            return {"saved": True, "path": str(source), "name": source.name}

        try:
            shutil.copy2(source, target)
        except OSError as exc:
            raise ValueError(f"视频另存失败：{exc}") from exc
        return {"saved": True, "path": str(target), "name": target.name}

    def save_server_video_as(
        self,
        token: str,
        file_id: str,
        suggested_name: str = "",
    ) -> dict[str, Any] | None:
        """Download a stored project video and open the native Save As dialog."""

        clean_file_id = str(file_id or "").strip()
        if not clean_file_id or not re.fullmatch(r"[A-Za-z0-9_-]+", clean_file_id):
            raise ValueError("视频文件 ID 无效")
        active_token = str(token or self._read_auth().get("token") or "")
        if not active_token:
            raise ValueError("登录状态已失效，请重新登录")
        if request_path.startswith(("/project", "/chapter", "/asset", "/video-project")):
            self._ensure_local_storage_migrated(active_token)

        download_dir = (DATA_DIR / "download_cache").resolve()
        download_dir.mkdir(parents=True, exist_ok=True)
        temp_path: Path | None = None
        try:
            response = self._file_request(
                "GET",
                clean_file_id,
                headers=self._auth_headers(active_token),
                timeout=180,
            )
            response.raise_for_status()
            content_type = response.headers.get("content-type", "").split(";", 1)[0].strip()
            suffix = mimetypes.guess_extension(content_type) or Path(str(suggested_name)).suffix or ".mp4"
            if suffix.lower() not in {".mp4", ".mov", ".m4v", ".webm", ".avi", ".mkv"}:
                suffix = ".mp4"
            temp_path = download_dir / f"{uuid.uuid4().hex}{suffix.lower()}"
            temp_path.write_bytes(response.content)
            safe_name = Path(str(suggested_name or f"视频{suffix}")).name
            return self.save_video_as(str(temp_path), safe_name)
        except httpx.TimeoutException as exc:
            raise ValueError("视频下载超时，请重试") from exc
        except httpx.HTTPError as exc:
            raise ValueError(f"视频下载失败：{exc}") from exc
        except OSError as exc:
            raise ValueError(f"视频临时文件保存失败：{exc}") from exc
        finally:
            if temp_path is not None:
                try:
                    temp_path.unlink(missing_ok=True)
                except OSError:
                    pass

    def create_account(self, name: str, token: str = "") -> dict[str, Any]:
        self._ensure_cloud_accounts_synced(token)
        clean_name = str(name).strip()
        if not clean_name:
            raise ValueError("请输入账号名称")
        accounts = self._read_accounts()
        account = {
            "id": uuid.uuid4().hex[:10],
            "name": clean_name[:30],
            "sortOrder": len(accounts),
            "hasLoggedIn": False,
            "quotaExhaustedOn": "",
            "dailyQuota": self.get_settings().get("dailyVideoQuota", 3),
            "quotaUsageDate": "",
            "generatedToday": 0,
            "status": "未登录或待确认",
        }
        accounts.append(account)
        self._write_accounts(accounts)
        (ACCOUNTS_DIR / account["id"] / "profile").mkdir(parents=True, exist_ok=True)
        self._push_cloud_account_state(token)
        return account

    def rename_account(self, account_id: str, name: str, token: str = "") -> dict[str, Any]:
        self._ensure_cloud_accounts_synced(token)
        clean_name = str(name).strip()
        if not clean_name:
            raise ValueError("账号名称不能为空")
        accounts = self._read_accounts()
        account = next((item for item in accounts if item.get("id") == account_id), None)
        if account is None:
            raise ValueError("账号不存在")
        account["name"] = clean_name[:30]
        self._write_accounts(accounts)
        self._push_cloud_account_state(token)
        return account

    def delete_account(self, account_id: str, token: str = "") -> dict[str, str]:
        self._ensure_cloud_accounts_synced(token)
        clean_account_id = str(account_id).strip()
        accounts = self._read_accounts()
        account = next((item for item in accounts if item.get("id") == clean_account_id), None)
        if account is None:
            raise ValueError("账号不存在")
        if self._account_is_in_use(clean_account_id):
            raise ValueError("账号正在运行中，请等待任务结束或先手动释放")

        with self._lock:
            worker = self._workers.get(clean_account_id)
        if worker is not None:
            worker.stop()
            worker.thread.join(timeout=15)
            if worker.thread.is_alive():
                raise RuntimeError("账号浏览器正在关闭，请稍后重试")

        accounts_root = ACCOUNTS_DIR.resolve()
        account_dir = (accounts_root / clean_account_id).resolve()
        if account_dir.parent != accounts_root:
            raise ValueError("账号目录无效")
        if account_dir.exists():
            shutil.rmtree(account_dir)

        remaining_accounts = [item for item in accounts if item.get("id") != clean_account_id]
        for sort_order, item in enumerate(remaining_accounts):
            item["sortOrder"] = sort_order
        self._write_accounts(remaining_accounts)
        settings = self.get_settings()
        if settings.get("defaultAccountId") == clean_account_id:
            settings["defaultAccountId"] = ""
            self._write_settings(settings)
        self._push_cloud_account_state(token)
        return {"id": clean_account_id, "name": str(account.get("name") or "")}

    def _bring_main_window_to_foreground(self) -> None:
        """把客户端主窗口拉回前台焦点，避免被刚启动的 Chrome 抢焦点。

        SetForegroundWindow 有反偷焦限制：只有当前前台窗口的进程能成功调用。
        绕过办法是先模拟一次 Alt 键按下/释放，Windows 会认为这是用户操作，
        临时放开反偷焦锁，紧跟着调 SetForegroundWindow 即可生效。
        """
        if os.name != "nt" or self._window is None or self._window.native is None:
            return
        try:
            hwnd = int(self._window.native.Handle.ToInt64())
            user32 = ctypes.WinDLL("user32", use_last_error=True)
            # 模拟 Alt 按下再释放，绕过 SetForegroundWindow 反偷焦限制
            user32.keybd_event(0x12, 0, 0, 0)        # VK_MENU down
            user32.keybd_event(0x12, 0, 0x02, 0)     # VK_MENU up (KEYEVENTF_KEYUP)
            user32.SetForegroundWindow.argtypes = [wintypes.HWND]
            user32.SetForegroundWindow.restype = wintypes.BOOL
            if not user32.SetForegroundWindow(hwnd):
                # 退一步：先 restore + show 再抢一次焦点
                user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
                user32.ShowWindow.restype = wintypes.BOOL
                user32.ShowWindow(hwnd, 9)   # SW_RESTORE
                user32.ShowWindow(hwnd, 5)   # SW_SHOW
                user32.SetForegroundWindow(hwnd)
        except Exception:
            pass

    def _watch_and_refocus(self, worker: "AccountBrowserWorker") -> None:
        """新启动登录浏览器后，等 worker ready + Chrome 完成初始化，再拉回主窗口焦点。

        Chrome 启动后约 1~3 秒会完成窗口创建并抢焦点，此时主窗口需要重新被拉回。
        worker.ready.set() 表示 Chrome 进程已就绪，但抢焦点可能略晚，所以额外等 1.5s。
        """
        if worker is None:
            return
        try:
            worker.ready.wait(timeout=40)
            time.sleep(1.5)
            self._bring_main_window_to_foreground()
        except Exception:
            pass

    def open_account_login(self, account_id: str) -> dict[str, str]:
        account = self._find_account(account_id)
        if self._account_is_in_use(account_id):
            raise ValueError("账号正在运行中，请等待任务结束或先手动释放")
        with self._lock:
            current = self._workers.get(account_id)
        if current is not None:
            if current.visible:
                with self._lock:
                    self._login_expired.pop(account_id, None)
                # 浏览器已开着，但用户切到设置中心点登录——主窗口可能已失焦，拉回一次
                self._bring_main_window_to_foreground()
                return {"status": "running", "message": f'{account["name"]} 的登录浏览器已经打开'}
            current.stop()
            current.thread.join(timeout=8)
        with self._lock:
            self._login_expired.pop(account_id, None)
        worker = self._ensure_worker(account_id, visible=True)
        # 新启动 Chrome 会抢焦点，watcher 在 worker ready 后把主窗口拉回前台
        threading.Thread(
            target=self._watch_and_refocus,
            args=(worker,),
            daemon=True,
        ).start()
        return {"status": "opening", "message": f'正在打开 {account["name"]} 的 OriginalDoubao 登录窗口'}

    def check_account_login(self, account_id: str, token: str = "") -> dict[str, Any]:
        """校验账号是否仍处于登录状态。

        优先走 HTTP 探活（不开浏览器，带真实 UA + Referer + 缓存 cookie）；
        仅当 cookie 缓存不存在或 HTTP 判定 cookie 失效时，才 fallback 到浏览器校验：
        打开 OriginalDoubao 页面、等待页面渲染后检查登录入口是否出现。
        浏览器校验成功后会刷新 cookie 缓存，下次即可继续走 HTTP。
        """
        self._ensure_cloud_accounts_synced(token)
        account = self._find_account(account_id)
        if self._account_is_in_use(account_id):
            raise ValueError("账号正在运行中，请等待任务结束或先手动释放")
        account_name = str(account.get("name") or "该账号")
        has_logged_in = bool(account.get("hasLoggedIn"))

        # 步骤 1：HTTP 探活。返回 None 表示无法判定，需要 fallback 浏览器。
        http_result = self._http_check_login(account_id)
        if http_result is not None:
            logged_in = bool(http_result.get("loggedIn"))
            with self._lock:
                if logged_in or not has_logged_in:
                    self._login_expired.pop(account_id, None)
                else:
                    self._login_expired[account_id] = True
            if logged_in:
                message = f"{account_name} 登录状态正常（HTTP 校验）"
            elif has_logged_in:
                message = f"{account_name} 登录已过期，请打开 OriginalDoubao 重新登录"
            else:
                message = f"{account_name} 尚未登录"
            return {
                "accountId": account_id,
                "name": account_name,
                "loggedIn": logged_in,
                "hasLoginText": not logged_in and has_logged_in,
                "hasSessionCookie": bool(http_result.get("hasSessionCookie")),
                "url": str(http_result.get("url") or ""),
                "method": "http",
                "message": message,
            }

        # 步骤 2：fallback 浏览器校验（无缓存 cookie 或 HTTP 探活不可用）。
        with self._lock:
            existing = self._workers.get(account_id)
        temporary = existing is None
        worker = existing or self._ensure_worker(account_id, visible=False)
        try:
            if not worker.ready.wait(timeout=40):
                raise RuntimeError(worker.start_error or "启动 OriginalDoubao 浏览器超时")
            if worker.start_error:
                raise RuntimeError(f"启动 OriginalDoubao 浏览器失败：{worker.start_error}")
            reply: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=1)
            worker.submit_check_login(reply)
            try:
                result = reply.get(timeout=90)
            except queue.Empty as exc:
                raise TimeoutError("校验登录超时，请稍后重试") from exc
        finally:
            if temporary:
                worker.stop()
                worker.thread.join(timeout=15)
        if not result.get("success"):
            raise RuntimeError(str(result.get("error") or "校验登录失败"))
        data = dict(result.get("data") or {})
        logged_in = bool(data.get("loggedIn"))
        with self._lock:
            if logged_in or not has_logged_in:
                self._login_expired.pop(account_id, None)
            else:
                self._login_expired[account_id] = True
        if logged_in:
            message = f"{account_name} 登录状态正常"
        elif has_logged_in:
            message = f"{account_name} 登录已过期，请打开 OriginalDoubao 重新登录"
        else:
            message = f"{account_name} 尚未登录"
        return {
            "accountId": account_id,
            "name": account_name,
            "loggedIn": logged_in,
            "hasLoginText": bool(data.get("hasLoginText")),
            "hasSessionCookie": bool(data.get("hasSessionCookie")),
            "url": str(data.get("url") or ""),
            "method": "browser",
            "message": message,
        }


    def _ensure_worker(self, account_id: str, visible: bool) -> AccountBrowserWorker:
        with self._lock:
            worker = self._workers.get(account_id)
            if worker is None:
                worker = AccountBrowserWorker(self, account_id, visible)
                self._workers[account_id] = worker
                worker.start()
            return worker

    def _worker_stopped(self, account_id: str, worker: AccountBrowserWorker) -> None:
        # worker 线程退出（含异常崩溃）时，除了从注册表摘除外，必须把它持有的
        # 账号使用锁一并释放，否则任务还没走到 succeeded/failed，账号会被永久锁住，
        # 前端只能靠"手动释放"才能解。
        with self._lock:
            # A completed worker may already have retired itself so the next
            # task can create a fresh browser. Never let that old worker clean
            # up the replacement worker's account usage when its thread exits.
            if self._workers.get(account_id) is not worker:
                return
            self._workers.pop(account_id, None)
            usage = self._account_usage.get(account_id)
            if usage is None:
                return
            owner_id = str(usage.get("ownerId") or "")
            task = self._tasks.get(owner_id)
            if task is not None and task.get("status") not in {"succeeded", "failed"}:
                if task.get("manuallyReleased"):
                    # 用户已手动释放，仅清理 usage 即可，不要再覆盖任务状态。
                    self._account_usage.pop(account_id, None)
                    return
                task.update({
                    "status": "failed",
                    "statusText": "OriginalDoubao 浏览器异常退出，账号已自动释放；请重试或切换其他账号",
                    "progress": 0,
                })
            self._account_usage.pop(account_id, None)

    def _retire_worker(self, account_id: str, worker: AccountBrowserWorker) -> None:
        """Detach a deliberately closed worker before releasing its account."""

        with self._lock:
            if self._workers.get(account_id) is worker:
                self._workers.pop(account_id, None)

    def shutdown(self, *_: Any) -> None:
        with self._lock:
            workers = list(self._workers.values())
        for worker in workers:
            worker.stop()
        self._media_server.shutdown()
        if self._local_storage_server is not None:
            try:
                self._local_storage_server.stop()
            except Exception:
                pass
        if self._storage_process is not None and self._storage_process.poll() is None:
            self._storage_process.terminate()
            try:
                self._storage_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._storage_process.kill()
        if self._storage_log_handle is not None:
            self._storage_log_handle.close()

    def _media_url_for(self, result_path: str) -> str:
        return self._media_server.register(self._webview_preview_path(result_path))

    def _webview_preview_path(self, result_path: str) -> Path:
        """Create an H.264 preview when WebView cannot decode the source codec."""

        source = Path(result_path).resolve()
        ffprobe = shutil.which("ffprobe")
        ffmpeg = shutil.which("ffmpeg")
        if not source.is_file() or not ffprobe or not ffmpeg:
            return source
        creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        try:
            probe = subprocess.run(
                [
                    ffprobe,
                    "-v",
                    "error",
                    "-select_streams",
                    "v:0",
                    "-show_entries",
                    "stream=codec_name",
                    "-of",
                    "default=noprint_wrappers=1:nokey=1",
                    str(source),
                ],
                check=True,
                capture_output=True,
                text=True,
                timeout=30,
                creationflags=creation_flags,
            )
            codec = probe.stdout.strip().lower()
            if codec not in {"hevc", "h265"}:
                return source

            preview = source.with_name(f"{source.stem}_preview.mp4")
            if preview.is_file() and preview.stat().st_mtime >= source.stat().st_mtime:
                return preview
            partial = source.with_name(f"{source.stem}_preview.tmp.mp4")
            subprocess.run(
                [
                    ffmpeg,
                    "-y",
                    "-i",
                    str(source),
                    "-map",
                    "0:v:0",
                    "-map",
                    "0:a?",
                    "-c:v",
                    "libx264",
                    "-preset",
                    "veryfast",
                    "-crf",
                    "20",
                    "-pix_fmt",
                    "yuv420p",
                    "-c:a",
                    "copy",
                    "-movflags",
                    "+faststart",
                    str(partial),
                ],
                check=True,
                capture_output=True,
                timeout=600,
                creationflags=creation_flags,
            )
            if not partial.is_file() or partial.stat().st_size == 0:
                raise RuntimeError("兼容预览文件为空")
            partial.replace(preview)
            return preview
        except Exception:
            try:
                source.with_name(f"{source.stem}_preview.tmp.mp4").unlink(missing_ok=True)
            except OSError:
                pass
            return source

    def _read_accounts(self) -> list[dict[str, Any]]:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        cached_accounts: list[dict[str, Any]] = []
        try:
            if ACCOUNTS_FILE.exists():
                data = json.loads(ACCOUNTS_FILE.read_text(encoding="utf-8"))
                cached_accounts = data if isinstance(data, list) else []
        except (OSError, json.JSONDecodeError):
            cached_accounts = []

        if not self._storage_available():
            return cached_accounts
        try:
            response = self._storage_request("GET", "/api/storage/data/account", timeout=3)
            response.raise_for_status()
            documents = response.json()
            local_accounts = [
                dict(item["data"])
                for item in documents
                if isinstance(item, dict) and isinstance(item.get("data"), dict)
            ] if isinstance(documents, list) else []
            if local_accounts:
                local_accounts.sort(key=lambda item: self._non_negative_int(item.get("sortOrder"), 0))
                ACCOUNTS_FILE.write_text(
                    json.dumps(local_accounts, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
                return local_accounts
            if cached_accounts:
                self._write_accounts(cached_accounts)
            return cached_accounts
        except (httpx.HTTPError, ValueError, OSError, json.JSONDecodeError):
            return cached_accounts

    def _write_accounts(self, accounts: list[dict[str, Any]]) -> None:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        ACCOUNTS_FILE.write_text(
            json.dumps(accounts, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        if self._storage_available():
            try:
                response = self._storage_request("GET", "/api/storage/data/account", timeout=3)
                response.raise_for_status()
                documents = response.json()
                existing = {
                    str(item.get("id") or ""): self._non_negative_int(item.get("revision"), 0)
                    for item in documents
                    if isinstance(item, dict) and item.get("id")
                } if isinstance(documents, list) else {}
                saved_ids: set[str] = set()
                for index, item in enumerate(accounts):
                    account = dict(item)
                    account_id = str(account.get("id") or "").strip()
                    if not account_id:
                        continue
                    account["sortOrder"] = index
                    account.pop("revision", None)
                    save_response = self._storage_request(
                        "PUT",
                        f"/api/storage/data/account/{quote(account_id, safe='')}",
                        json={"data": account, "expectedRevision": existing.get(account_id, 0)},
                        timeout=5,
                    )
                    save_response.raise_for_status()
                    saved_ids.add(account_id)
                for account_id, revision in existing.items():
                    if account_id in saved_ids:
                        continue
                    delete_response = self._storage_request(
                        "DELETE",
                        f"/api/storage/data/account/{quote(account_id, safe='')}?expectedRevision={revision}",
                        timeout=5,
                    )
                    delete_response.raise_for_status()
                settings = self.get_settings()
                if not settings.get("accountLocalMigrated"):
                    settings["accountLocalMigrated"] = True
                    self._write_settings(settings)
            except (httpx.HTTPError, ValueError, OSError):
                # accounts.json remains a rollback cache if the local service is unavailable.
                pass

    @staticmethod
    def _write_settings(settings: dict[str, Any]) -> None:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        SETTINGS_FILE.write_text(
            json.dumps(settings, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _active_account_token(self, token: str = "") -> str:
        return str(token or self._session_token or self._read_auth().get("token") or "")

    def _ensure_cloud_accounts_synced(self, token: str = "") -> None:
        # Account metadata remains local in Storage-only mode.
        return
        
        active_token = self._active_account_token(token)
        if self._storage_available() and self.get_settings().get("accountLocalMigrated"):
            self._cloud_accounts_synced_token = active_token
            return
        if not active_token or self._cloud_accounts_synced_token == active_token:
            return
        now = time.monotonic()
        if now - self._cloud_accounts_last_attempt < 30:
            return
        self._cloud_accounts_last_attempt = now
        local_accounts = self._read_accounts()
        try:
            response = self._api_request(
                "GET",
                "/desktop/account-state",
                headers=self._auth_headers(active_token),
                timeout=8,
            )
            body = self._parse_api_response(response)
            state = body.get("data")
            if not isinstance(state, dict):
                return
            if not state.get("initialized"):
                if self._push_cloud_account_state(active_token):
                    settings = self.get_settings()
                    settings["accountCloudMigrated"] = True
                    settings["accountLocalMigrated"] = True
                    self._write_settings(settings)
                    self._cloud_accounts_synced_token = active_token
                return

            raw_accounts = state.get("accounts")
            cloud_accounts: list[dict[str, Any]] = []
            if isinstance(raw_accounts, list):
                for index, item in enumerate(raw_accounts):
                    if not isinstance(item, dict):
                        continue
                    account_id = str(item.get("id") or "").strip()
                    name = str(item.get("name") or "").strip()
                    if account_id and name:
                        cloud_accounts.append({
                            "id": account_id,
                            "name": name[:30],
                            "sortOrder": int(item.get("sortOrder", index)) if str(item.get("sortOrder", index)).isdigit() else index,
                            "hasLoggedIn": bool(item.get("hasLoggedIn", False)),
                            "quotaExhaustedOn": str(item.get("quotaExhaustedOn") or ""),
                            "dailyQuota": max(1, min(self._non_negative_int(item.get("dailyQuota"), 3), 99)),
                        })
            settings = self.get_settings()
            needs_legacy_merge = not bool(settings.get("accountCloudMigrated", False))
            if needs_legacy_merge:
                cloud_by_id = {item["id"]: item for item in cloud_accounts}
                for local in local_accounts:
                    local_id = str(local.get("id") or "").strip()
                    local_name = str(local.get("name") or "").strip()
                    if not local_id or not local_name:
                        continue
                    cloud = cloud_by_id.get(local_id)
                    if cloud is None:
                        migrated = {
                            "id": local_id,
                            "name": local_name[:30],
                            "sortOrder": len(cloud_accounts),
                            "hasLoggedIn": bool(local.get("hasLoggedIn", False)),
                            "quotaExhaustedOn": str(local.get("quotaExhaustedOn") or ""),
                            "dailyQuota": self._account_daily_quota(local),
                        }
                        cloud_accounts.append(migrated)
                        cloud_by_id[local_id] = migrated
                    else:
                        cloud["hasLoggedIn"] = bool(
                            cloud.get("hasLoggedIn") or local.get("hasLoggedIn")
                        )
                        cloud["quotaExhaustedOn"] = max(
                            str(cloud.get("quotaExhaustedOn") or ""),
                            str(local.get("quotaExhaustedOn") or ""),
                        )
                        cloud["dailyQuota"] = self._account_daily_quota(local)
            cloud_accounts.sort(key=lambda item: int(item.get("sortOrder", 0)))
            for sort_order, item in enumerate(cloud_accounts):
                item["sortOrder"] = sort_order
            self._write_accounts(cloud_accounts)
            selected_id = str(state.get("selectedAccountId") or "")
            if selected_id not in {item["id"] for item in cloud_accounts}:
                local_selected_id = str(settings.get("defaultAccountId") or "")
                selected_id = (
                    local_selected_id
                    if local_selected_id in {item["id"] for item in cloud_accounts}
                    else ""
                )
            settings["defaultAccountId"] = selected_id
            settings["accountCloudMigrated"] = True
            settings["accountLocalMigrated"] = True
            self._write_settings(settings)
            if needs_legacy_merge:
                self._push_cloud_account_state(active_token)
            self._cloud_accounts_synced_token = active_token
        except (httpx.HTTPError, ValueError, OSError):
            # Offline startup keeps the local account metadata and selection usable.
            return

    def _push_cloud_account_state(self, token: str = "") -> bool:
        if self._storage_available():
            return True
        active_token = self._active_account_token(token)
        if not active_token:
            return False
        accounts = [
            {
                "id": str(item.get("id") or ""),
                "name": str(item.get("name") or ""),
                "sortOrder": index,
                "hasLoggedIn": bool(item.get("hasLoggedIn", False)),
                "quotaExhaustedOn": str(item.get("quotaExhaustedOn") or ""),
                "dailyQuota": self._account_daily_quota(item),
            }
            for index, item in enumerate(self._read_accounts())
            if item.get("id") and item.get("name")
        ]
        try:
            response = self._api_request(
                "PUT",
                "/desktop/account-state",
                headers=self._auth_headers(active_token),
                json={
                    "accounts": accounts,
                    "selectedAccountId": str(self.get_settings().get("defaultAccountId") or ""),
                },
                timeout=8,
            )
            self._parse_api_response(response)
            self._cloud_accounts_synced_token = active_token
            return True
        except (httpx.HTTPError, ValueError):
            return False

    def _set_cloud_account_quota_status(
        self,
        account: dict[str, Any],
        quota_date: str,
        exhausted: bool,
        reason: str,
        token: str = "",
    ) -> bool:
        if self._storage_available():
            return True
        active_token = self._active_account_token(token)
        if not active_token:
            return False
        try:
            response = self._api_request(
                "POST",
                "/desktop/account-quota/status",
                headers=self._auth_headers(active_token),
                json={
                    "accountId": str(account.get("id") or ""),
                    "accountName": str(account.get("name") or ""),
                    "quotaDate": quota_date,
                    "exhausted": bool(exhausted),
                    "reason": str(reason or ""),
                    "dailyLimit": self._account_daily_quota(account),
                },
                timeout=8,
            )
            self._parse_api_response(response)
            return True
        except (httpx.HTTPError, ValueError):
            return False

    def _pull_cloud_account_quota(self, token: str = "") -> bool:
        if self._storage_available():
            return True
        active_token = self._active_account_token(token)
        if not active_token:
            return False
        today = date.today().isoformat()
        try:
            response = self._api_request(
                "GET",
                f"/desktop/account-quota/today-usage?date={today}",
                headers=self._auth_headers(active_token),
                timeout=8,
            )
            body = self._parse_api_response(response)
            records = body.get("data")
            if not isinstance(records, list):
                return False
            records_by_id = {
                str(item.get("accountId") or "").strip(): item
                for item in records
                if isinstance(item, dict) and item.get("accountId")
            }
            accounts = self._read_accounts()
            changed = False
            for account in accounts:
                account_id = str(account.get("id") or "")
                current = str(account.get("quotaExhaustedOn") or "")
                record = records_by_id.get(account_id)
                if record is not None:
                    daily_quota = max(1, min(self._non_negative_int(record.get("dailyLimit"), self._account_daily_quota(account)), 99))
                    generated = min(self._non_negative_int(record.get("generatedCount"), 0), daily_quota)
                    exhausted = bool(record.get("exhausted")) or generated >= daily_quota
                    if account.get("dailyQuota") != daily_quota or account.get("quotaUsageDate") != today or account.get("generatedToday") != generated:
                        account["dailyQuota"] = daily_quota
                        account["quotaUsageDate"] = today
                        account["generatedToday"] = generated
                        changed = True
                else:
                    exhausted = False
                    if account.get("quotaUsageDate") == today:
                        exhausted = self._non_negative_int(account.get("generatedToday"), 0) >= self._account_daily_quota(account)
                if exhausted and current != today:
                    account["quotaExhaustedOn"] = today
                    changed = True
                elif not exhausted and current == today:
                    account["quotaExhaustedOn"] = ""
                    changed = True
            if changed:
                self._write_accounts(accounts)
                self._push_cloud_account_state(active_token)
            return True
        except (httpx.HTTPError, ValueError, OSError):
            return False

    def _find_account(self, account_id: str) -> dict[str, Any]:
        account = next((item for item in self._read_accounts() if item.get("id") == account_id), None)
        if account is None:
            raise ValueError("账号不存在，请刷新账号列表")
        return account

    @staticmethod
    def _non_negative_int(value: Any, fallback: int = 0) -> int:
        try:
            return max(0, int(value))
        except (TypeError, ValueError):
            return fallback

    def _account_daily_quota(self, account: dict[str, Any]) -> int:
        return max(1, min(self._non_negative_int(self.get_settings().get("dailyVideoQuota"), 3), 99))

    def _record_account_generation_success(self, account_id: str, token: str = "") -> None:
        clean_account_id = str(account_id or "").strip()
        accounts = self._read_accounts()
        account = next((item for item in accounts if item.get("id") == clean_account_id), None)
        if account is None:
            return
        today = date.today().isoformat()
        limit = self._account_daily_quota(account)
        generated = (
            self._non_negative_int(account.get("generatedToday"), 0)
            if account.get("quotaUsageDate") == today
            else 0
        )
        active_token = self._active_account_token(token)
        if active_token and not self._storage_available():
            try:
                response = self._api_request(
                    "POST",
                    "/desktop/account-quota/consume",
                    headers=self._auth_headers(active_token),
                    json={
                        "accountId": clean_account_id,
                        "accountName": str(account.get("name") or ""),
                        "quotaDate": today,
                        "dailyLimit": limit,
                    },
                    timeout=8,
                )
                body = self._parse_api_response(response)
                record = body.get("data") if isinstance(body.get("data"), dict) else {}
                generated = self._non_negative_int(record.get("generatedCount"), generated + 1)
                limit = max(1, min(self._non_negative_int(record.get("dailyLimit"), limit), 99))
            except (httpx.HTTPError, ValueError):
                generated += 1
        else:
            generated += 1
        account["dailyQuota"] = limit
        account["quotaUsageDate"] = today
        account["generatedToday"] = min(generated, limit)
        account["quotaExhaustedOn"] = today if generated >= limit else ""
        self._write_accounts(accounts)

    def _account_is_in_use(self, account_id: str) -> bool:
        with self._lock:
            return str(account_id or "") in self._account_usage

    def _acquire_account_usage(self, account_id: str, owner_id: str, usage_type: str) -> None:
        clean_account_id = str(account_id or "").strip()
        with self._lock:
            existing = self._account_usage.get(clean_account_id)
            if existing is not None:
                raise ValueError("该账号正在运行中，请等待释放或在设置中心手动释放")
            self._account_usage[clean_account_id] = {
                "ownerId": str(owner_id),
                "type": str(usage_type),
                "startedAt": time.time(),
            }

    def _acquire_available_generation_account(
        self,
        preferred_account_id: str,
        owner_id: str,
    ) -> dict[str, Any]:
        today = date.today().isoformat()
        login_expired = getattr(self, "_login_expired", {})
        accounts = [
            account
            for account in self._read_accounts()
            if str(account.get("id") or "").strip()
            and str(account.get("quotaExhaustedOn") or "") != today
            and not login_expired.get(str(account.get("id") or "").strip())
        ]
        preferred_id = str(preferred_account_id or "").strip()
        accounts.sort(key=lambda account: (
            0 if str(account.get("id") or "") == preferred_id else 1,
            int(account.get("sortOrder") or 0),
        ))
        if not accounts:
            raise ValueError("没有可用的生成账号，请检查账号登录态或今日额度")

        with self._lock:
            account = next(
                (
                    item
                    for item in accounts
                    if str(item.get("id") or "").strip() not in self._account_usage
                ),
                None,
            )
            if account is None:
                raise ValueError("所有可用生成账号都在运行中，请等待任一任务完成")
            account_id = str(account.get("id") or "").strip()
            self._account_usage[account_id] = {
                "ownerId": str(owner_id),
                "type": "generation",
                "startedAt": time.time(),
            }
            return dict(account)

    def _release_account_usage(self, account_id: str, owner_id: str) -> bool:
        clean_account_id = str(account_id or "").strip()
        with self._lock:
            existing = self._account_usage.get(clean_account_id)
            if existing is None or existing.get("ownerId") != str(owner_id):
                return False
            self._account_usage.pop(clean_account_id, None)
            return True

    def _update_task(self, task_id: str, **values: Any) -> None:
        account_id = ""
        should_release = values.get("status") in {"succeeded", "failed"}
        should_consume_quota = False
        with self._lock:
            if task_id in self._tasks:
                if self._tasks[task_id].get("manuallyReleased"):
                    return
                previous_status = self._tasks[task_id].get("status")
                self._tasks[task_id].update(values)
                if should_release:
                    account_id = str(self._tasks[task_id].get("accountId") or "")
                should_consume_quota = values.get("status") == "succeeded" and previous_status != "succeeded"
        if should_consume_quota and account_id:
            self._record_account_generation_success(account_id)
        if should_release and account_id:
            self._release_account_usage(account_id, task_id)

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="AI video desktop demo")
    parser.add_argument(
        "--dev",
        action="store_true",
        help="Load the Vue development server at http://127.0.0.1:5173",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    # WebView2 的右键“另存为”最终会进入 pywebview 的下载事件。
    # 默认关闭下载会导致菜单可见但点击后没有任何结果；开启后由
    # pywebview 弹出 Windows 原生保存窗口并写入用户选择的位置。
    webview.settings["ALLOW_DOWNLOADS"] = True
    if args.dev:
        url = "http://127.0.0.1:5173"
    else:
        if not FRONTEND_DIST.exists():
            raise SystemExit(
                "未找到 frontend/dist/index.html，请先执行："
                "cd frontend && npm install && npm run build"
            )
        url = str(FRONTEND_DIST)

    api = DesktopApi()
    # 按光标所在显示器工作区 85% 算 DIP 尺寸并居中
    # Per-Monitor V2 感知下从副屏启动也能正确得到该屏工作区尺寸
    win_x, win_y, win_w, win_h = _compute_initial_window_bounds()
    min_w = int(win_w * 0.5 / 0.85)
    min_h = int(win_h * 0.5 / 0.85)
    window = webview.create_window(
        "CDTV",
        url=url,
        js_api=api,
        x=win_x,
        y=win_y,
        width=win_w,
        height=win_h,
        min_size=(min_w, min_h),
        resizable=True,
        background_color="#090d18",
        frameless=True,
        easy_drag=False,
        shadow=False,
    )
    api._window = window
    window.events.closed += api.shutdown
    # 窗口显示后主动设圆角（pywebview frameless 默认可能不带圆角）
    window.events.shown += api.apply_window_corners
    # 子类化顶层 HWND：处理 WM_DPICHANGED（跨屏拖动时物理尺寸按新 DPI 缩放）
    window.events.shown += api._install_native_window_proc
    # 关闭前还原 wndproc，避免退出崩溃
    window.events.closing += api._uninstall_native_window_proc
    webview.start(debug=args.dev, icon=str(APP_ICON) if APP_ICON.exists() else None)


if __name__ == "__main__":
    main()
