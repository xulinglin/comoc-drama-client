"""OriginalDoubao 视频生成 Worker。拆分自 launcher.py，逻辑保持一致。

每个 OriginalDoubao 账号对应一个 AccountBrowserWorker 线程，持有独立的 Chromium 持久化
profile。主线程通过命令队列向 worker 投递生成 / 链接转换任务，避免在多线程
下直接操作 Playwright 同步 API。
"""
from __future__ import annotations

import asyncio
import json
import queue
import re
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import parse_qs, urlparse

import httpx
from playwright.sync_api import sync_playwright

from constants import ACCOUNTS_DIR, BUNDLED_CHROME, DATA_DIR, ORIGINAL_DOUBAO_URL
from original_doubao_nomark import (
    OriginalDoubaoVideoEvidence,
    original_doubao_fplay_parse,
    original_doubao_video_parse,
    is_douyin_media_url,
    is_supported_conversion_url,
)

if TYPE_CHECKING:
    from launcher import DesktopApi


# OriginalDoubao 最终生成/发送开关；关闭时保留填写好的内容，便于检查流程。
ORIGINAL_DOUBAO_VIDEO_AUTO_SUBMIT_ENABLED = True


class ManualOperationRequired(RuntimeError):
    """Raised when a visible OriginalDoubao surface cannot be dismissed automatically."""


def _secondary_monitor_chrome_args(account_id: str) -> list[str]:
    """Place visible automation Chrome windows on a non-primary Windows display."""

    try:
        import ctypes
        from ctypes import wintypes

        monitors: list[tuple[int, int, int, int, bool]] = []

        class MonitorInfo(ctypes.Structure):
            _fields_ = [
                ("cbSize", wintypes.DWORD),
                ("rcMonitor", wintypes.RECT),
                ("rcWork", wintypes.RECT),
                ("dwFlags", wintypes.DWORD),
            ]

        callback_type = ctypes.WINFUNCTYPE(
            wintypes.BOOL,
            wintypes.HANDLE,
            wintypes.HDC,
            ctypes.POINTER(wintypes.RECT),
            wintypes.LPARAM,
        )

        @callback_type
        def collect_monitor(monitor: Any, _dc: Any, _rect: Any, _data: Any) -> bool:
            info = MonitorInfo()
            info.cbSize = ctypes.sizeof(MonitorInfo)
            if ctypes.windll.user32.GetMonitorInfoW(monitor, ctypes.byref(info)):
                work = info.rcWork
                monitors.append((
                    int(work.left),
                    int(work.top),
                    int(work.right),
                    int(work.bottom),
                    bool(info.dwFlags & 1),
                ))
            return True

        ctypes.windll.user32.EnumDisplayMonitors(None, None, collect_monitor, 0)
        secondary = next((item for item in monitors if not item[4]), None)
        if secondary is None:
            return []
        left, top, right, bottom, _primary = secondary
        available_width = max(640, right - left)
        available_height = max(480, bottom - top)
        width = min(1280, available_width)
        height = min(820, available_height)
        offset = sum(ord(char) for char in str(account_id)) % 5 * 24
        x = min(left + offset, right - width)
        y = min(top + offset, bottom - height)
        return [f"--window-position={x},{y}", f"--window-size={width},{height}"]
    except Exception:
        return []


def save_media_url(media_url: str, task_id: str, settings: dict[str, Any]) -> Path:
    """Download a resolved media URL without requiring a browser worker."""

    output_dir = Path(str(settings["outputDir"])).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"original_doubao_{task_id}.mp4"
    partial_path = output_path.with_suffix(".mp4.part")
    hostname = (httpx.URL(media_url).host or "").lower()
    if hostname == "365yg.com" or hostname.endswith(".365yg.com"):
        headers = {
            "Accept": (
                "text/html,application/xhtml+xml,application/xml;q=0.9,"
                "image/avif,image/webp,image/apng,*/*;q=0.8,"
                "application/signed-exchange;v=b3;q=0.7"
            ),
            "Accept-Language": "zh-CN,zh;q=0.9",
            "Sec-CH-UA": '"Chromium";v="151", "Not=A?Brand";v="99"',
            "Sec-CH-UA-Mobile": "?0",
            "Sec-CH-UA-Platform": '"Windows"',
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "none",
            "Upgrade-Insecure-Requests": "1",
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "HeadlessChrome/151.0.0.0 Safari/537.36"
            ),
        }
    else:
        headers = {"Referer": "https://www.doubao.com/", "User-Agent": "Mozilla/5.0"}
    try:
        with httpx.stream("GET", media_url, headers=headers, follow_redirects=True, timeout=120) as response:
            response.raise_for_status()
            with partial_path.open("wb") as output:
                for chunk in response.iter_bytes(chunk_size=1024 * 1024):
                    output.write(chunk)
        partial_path.replace(output_path)
        return output_path
    except Exception:
        try:
            partial_path.unlink(missing_ok=True)
        except OSError:
            pass
        raise


class AccountBrowserWorker:
    def __init__(self, api: "DesktopApi", account_id: str, visible: bool) -> None:
        self.api = api
        self.account_id = account_id
        self.visible = visible
        self.commands: queue.Queue[dict[str, Any]] = queue.Queue()
        self.ready = threading.Event()
        self.start_error = ""
        self.authenticated: bool | None = None
        self.thread = threading.Thread(target=self._run, daemon=True)

    def start(self) -> None:
        self.thread.start()

    def submit_generation(self, task_id: str, payload: dict[str, Any]) -> None:
        self.commands.put({"type": "generate", "taskId": task_id, "payload": payload})

    def submit_link_conversion(self, link: str, reply: queue.Queue[dict[str, Any]]) -> None:
        self.commands.put({"type": "convert_link", "link": link, "reply": reply})

    def submit_check_login(self, reply: queue.Queue[dict[str, Any]]) -> None:
        self.commands.put({"type": "check_login", "reply": reply})

    def stop(self) -> None:
        self.commands.put({"type": "stop"})

    def _run(self) -> None:
        profile_dir = (ACCOUNTS_DIR / self.account_id / "profile").resolve()
        profile_dir.mkdir(parents=True, exist_ok=True)
        playwright = None
        context = None
        try:
            playwright = sync_playwright().start()
            if not BUNDLED_CHROME.is_file():
                raise RuntimeError(f"内置浏览器不存在：{BUNDLED_CHROME}")
            # OriginalDoubao 风控会识别 headless 浏览器，headless 下登录会话不被认可，
            # 导致后台生成卡在"已提交到 OriginalDoubao"。因此始终使用真实（非 headless）
            # 浏览器：前台放副屏，后台无副屏时把窗口放到屏幕外，不影响用户。
            chrome_args = _secondary_monitor_chrome_args(self.account_id)
            if not self.visible and not chrome_args:
                chrome_args = ["--window-position=-32000,-32000"]
            context = playwright.chromium.launch_persistent_context(
                user_data_dir=str(profile_dir),
                executable_path=str(BUNDLED_CHROME),
                headless=False,
                accept_downloads=True,
                viewport={"width": 1280, "height": 820},
                args=chrome_args,
            )
            page = context.pages[0] if context.pages else context.new_page()
            if not page.url.startswith("https://www.doubao.com"):
                page.goto(ORIGINAL_DOUBAO_URL, wait_until="domcontentloaded", timeout=60_000)
            self._refresh_authentication(context)
            self.ready.set()
            last_auth_check = time.monotonic()

            while context.pages:
                try:
                    command = self.commands.get(timeout=0.5)
                except queue.Empty:
                    page.wait_for_timeout(100)
                    if time.monotonic() - last_auth_check >= 2:
                        self._refresh_authentication(context)
                        last_auth_check = time.monotonic()
                    continue
                if command["type"] == "stop":
                    break
                if command["type"] == "generate":
                    self._generate(page, command["taskId"], command["payload"])
                if command["type"] == "convert_link":
                    try:
                        command["reply"].put({"success": True, "data": self._convert_link(page, command["link"])})
                    except Exception as exc:
                        command["reply"].put({"success": False, "error": str(exc)})
                if command["type"] == "check_login":
                    try:
                        target = context.pages[0] if context.pages else page
                        command["reply"].put({"success": True, "data": self._check_login(context, target)})
                    except Exception as exc:
                        command["reply"].put({"success": False, "error": str(exc)})
        except Exception as exc:
            self.start_error = str(exc)
            self.ready.set()
            print(f"Account browser stopped: {exc}")
        finally:
            if context is not None:
                try:
                    context.close()
                except Exception:
                    pass
            if playwright is not None:
                try:
                    playwright.stop()
                except Exception:
                    pass
            self.api._worker_stopped(self.account_id, self)

    def _refresh_authentication(self, context: Any) -> None:
        try:
            # 只认 sessionid / sessionid_ss：sid_guard 等辅助 cookie 有效期长达一年，
            # 单独存在不能证明已登录，否则 sessionid 已过期的账号会被误判为已认证。
            login_cookie_names = {"sessionid", "sessionid_ss"}
            cookies = context.cookies([ORIGINAL_DOUBAO_URL])
            self.authenticated = any(
                cookie.get("name") in login_cookie_names and str(cookie.get("value") or "").strip()
                for cookie in cookies
            )
            # 同步 cookie 缓存到 JSON，供 launcher 后续 HTTP 探活复用（避免每次校验都开浏览器）
            try:
                self.api._save_account_cookies_cache(self.account_id, cookies)
            except Exception:
                pass
        except Exception:
            self.authenticated = None

    def _detect_login_state(self, page: Any) -> str | None:
        """读取页面当前登录状态：'login'=出现登录入口，'avatar'=右上角已登录头像，None=还没渲染出来。"""
        try:
            return page.evaluate(
                """
                () => {
                  const isVisible = el => {
                    const r = el.getBoundingClientRect();
                    return r.width > 0 && r.height > 0;
                  };
                  // 登录入口：Semi 按钮（OriginalDoubao 用的是 Semi Design，登录按钮含
                  // class="semi-button..."/>），也兼容普通 button/a；短文案且以"登录"开头，
                  // 排除"退出登录""已登录""登录后…"等误匹配。
                  const loginNodes = Array.from(document.querySelectorAll('[class*="semi-button"],button,a,[role="button"]'));
                  const loginFound = loginNodes.some(n => {
                    const t = (n.innerText || n.textContent || '').trim();
                    if (!t || t.length > 12) return false;
                    if (!t.startsWith('登录')) return false;
                    if (t.includes('退出') || t.includes('已登录') || t.includes('登录后')) return false;
                    return isVisible(n);
                  });
                  if (loginFound) return 'login';
                  // 已登录标志：右上角（页面顶部 140px 内）的用户头像，避免匹配到内容区的推荐头像。
                  const avatars = Array.from(document.querySelectorAll('[class*="semi-avatar"],img[class*="avatar"],[class*="avatar"]'));
                  if (avatars.some(el => {
                    const r = el.getBoundingClientRect();
                    return r.width > 0 && r.height > 0 && r.top < 140;
                  })) return 'avatar';
                  return null;
                }
                """
            )
        except Exception:
            return None

    def _check_login(self, context: Any, page: Any) -> dict[str, Any]:
        """打开 OriginalDoubao 首页，等待页面渲染出登录入口或用户头像后判断登录状态。

        页面登录状态是异步渲染的，固定等几秒不可靠：未登录账号的登录按钮可能
        在 2 秒后才出现，若此时就读取会误判成"正常"。因此改为轮询等待，最多
        10 秒，一旦出现登录入口（semi 按钮「登录」）或右上角头像立即判定。
        """
        if not page.url.startswith("https://www.doubao.com"):
            page.goto(ORIGINAL_DOUBAO_URL, wait_until="domcontentloaded", timeout=60_000)
        deadline = time.monotonic() + 10
        state = self._detect_login_state(page)
        while state is None and time.monotonic() < deadline:
            page.wait_for_timeout(400)
            state = self._detect_login_state(page)
        try:
            cookies = context.cookies([ORIGINAL_DOUBAO_URL])
            # 只认 sessionid / sessionid_ss：sid_guard 等辅助 cookie 有效期长达一年，
            # 若把它们也算作凭证，sessionid 已过期的账号会被误判为「正常」。
            has_session = any(
                cookie.get("name") in {"sessionid", "sessionid_ss"}
                and str(cookie.get("value") or "").strip()
                for cookie in cookies
            )
        except Exception:
            has_session = False
        if state == "login":
            logged_in = False
        elif state == "avatar":
            logged_in = True
        else:
            # 页面状态无法确认（如选择器失配 / 渲染超时）。此时不能仅凭「cookie 存在」
            # 就判为正常——过期的 sessionid 仍然存在于浏览器里。只有确认存在会话
            # cookie 且页面未出现登录入口时才保守判为已登录，否则判未登录。
            logged_in = has_session
        self.authenticated = logged_in
        return {
            "loggedIn": logged_in,
            "pageState": state or "unknown",
            "hasLoginText": state == "login",
            "hasSessionCookie": has_session,
            "url": page.url,
        }

    def _generate(self, page: Any, task_id: str, payload: dict[str, Any]) -> None:
        listeners: tuple[Any, Any] | None = None
        try:
            if self.api.is_account_quota_exhausted_today(self.account_id):
                self.api._update_task(
                    task_id,
                    status="failed",
                    statusText="该生成账号今日视频额度已用完，请切换其他账号或明日再试",
                    progress=0,
                )
                self._close_generation_window(page)
                return
            self.api._update_task(task_id, status="opening", statusText="正在打开 OriginalDoubao 创作页面", progress=10)
            if not page.url.startswith("https://www.doubao.com"):
                page.goto(ORIGINAL_DOUBAO_URL, wait_until="domcontentloaded", timeout=60_000)
            page.wait_for_timeout(1500)
            self._dismiss_download_desktop_dialog(page)

            # Never reuse the previous task's conversation. Generation may
            # continue only after OriginalDoubao's empty-conversation welcome text is
            # visible, proving that the new conversation opened successfully.
            self.api._update_task(task_id, status="opening", statusText="正在创建并确认 OriginalDoubao 新对话", progress=12)
            self._open_new_conversation(page)
            self._dismiss_download_desktop_dialog(page)

            self._open_video_creation(page)
            self._dismiss_download_desktop_dialog(page)
            self.api._update_task(task_id, status="configuring", statusText="正在选择 Seedance 2.0 Fast", progress=18)
            model_name = str(payload.get("model", "Seedance 2.0 Fast"))
            model_retry = 0
            while True:
                try:
                    self._select_model(page, model_name)
                    break
                except RuntimeError as exc:
                    if "没有找到模型选项" not in str(exc) or model_retry >= 2:
                        raise
                    model_retry += 1

                self.api._update_task(
                    task_id,
                    status="configuring",
                    statusText=f"没有找到模型，正在新对话中重试（{model_retry}/2）",
                    progress=16,
                )
                self._open_new_conversation(page)
                self._open_video_creation(page)
            ratio = str(payload.get("ratio", "自动"))
            duration = max(4, min(15, int(payload.get("duration", 10))))
            self.api._update_task(task_id, status="configuring", statusText=f"正在设置 {ratio} · {duration}s", progress=21)
            self._configure_video(page, ratio, duration)
            # OriginalDoubao 视频生成当前不支持音频附件，统一过滤掉音频项，仅保留图片
            attachments = [
                item
                for item in payload.get("attachments", [])
                if isinstance(item, dict)
                and str(item.get("path", "")).strip()
                and item.get("type") != "audio"
            ]
            if not attachments:
                image_paths = [str(path) for path in payload.get("imagePaths", []) if str(path).strip()]
                if not image_paths:
                    image_paths = [str(payload["imagePath"])]
                attachments = [{"path": path, "type": "image"} for path in image_paths]
            image_count = len(attachments)
            self.api._update_task(
                task_id,
                status="uploading",
                statusText=f"正在向 OriginalDoubao 上传 {image_count} 张参考图",
                progress=24,
            )
            self._upload_attachments(page, attachments)

            self.api._update_task(task_id, status="submitting", statusText="正在填写视频描述", progress=38)
            self._fill_prompt(page, str(payload["prompt"]))

            if not ORIGINAL_DOUBAO_VIDEO_AUTO_SUBMIT_ENABLED:
                # 使用现有终止状态停止轮询、释放账号；未生成视频，不扣生成次数。
                self.api._update_task(
                    task_id,
                    status="failed",
                    statusText="素材和提示词已准备好，OriginalDoubao 最终生成/发送已临时关闭，请在浏览器中检查内容",
                    progress=38,
                )
                return

            before_videos = page.locator("video").count()
            before_video_fingerprints = self._video_fingerprints(page)
            baseline_evidence = OriginalDoubaoVideoEvidence()
            self._collect_page_video_evidence(page, baseline_evidence)
            conversation_guard: dict[str, str] = {"key": ""}
            evidence, listeners = self._listen_for_video_evidence(page, conversation_guard)
            self._click_generate(page)
            conversation = self._capture_generation_conversation(page, task_id)
            conversation_guard["key"] = str(conversation.get("key") or "")
            self.api._update_task(
                task_id,
                status="generating",
                statusText="已提交到 OriginalDoubao，正在等待生成结果",
                progress=55,
                demo=False,
                conversationId=str(conversation.get("id") or ""),
                conversationUrl=str(conversation.get("url") or ""),
                generationSubmittedAt=int(time.time() * 1000),
            )

            self._monitor_result(
                page,
                task_id,
                before_videos,
                before_video_fingerprints,
                evidence,
                baseline_evidence,
                listeners,
                payload,
                conversation,
            )
            listeners = None
        except Exception as exc:
            if listeners is not None:
                self._stop_video_evidence_listener(page, listeners)
            blocked_reason, requires_manual_verification = self._generation_block_reason(page)
            if blocked_reason:
                if "登录已过期" in blocked_reason or "会话失效" in blocked_reason:
                    self.api.mark_account_login_expired(self.account_id)
                if (
                    "今日视频生成免费次数已用完" in blocked_reason
                    or "视频生成额度不足" in blocked_reason
                ):
                    self.api.mark_account_quota_exhausted(self.account_id, reason=blocked_reason)
                self.api._update_task(
                    task_id,
                    status="failed",
                    statusText=blocked_reason,
                    progress=0,
                    resultPath="",
                    resultUrl="",
                    requiresManualVerification=requires_manual_verification,
                )
                if self._is_quota_exhausted_reason(blocked_reason):
                    self._close_generation_window(page)
                return
            if isinstance(exc, ManualOperationRequired):
                self.api._update_task(
                    task_id,
                    status="failed",
                    statusText=str(exc),
                    progress=0,
                    demo=False,
                    requiresManualVerification=True,
                )
                return
            debug_note = self._save_debug_snapshot(page, task_id)
            self.api._update_task(
                task_id,
                status="failed",
                statusText=f"OriginalDoubao 页面操作失败：{exc}{debug_note}",
                progress=0,
                demo=False,
            )

    def _convert_link(self, page: Any, link: str) -> dict[str, str]:
        clean_link = str(link).strip()
        if not is_supported_conversion_url(clean_link):
            raise ValueError("请输入官方视频分享链接或抖音视频直链")

        if is_douyin_media_url(clean_link):
            video_id = self._video_id_from_media_url(clean_link)
            if not video_id:
                raise ValueError("视频直链中没有读取到 video_id；链接可能已过期，请重新复制")
            evidence = OriginalDoubaoVideoEvidence()
            evidence.add(f'{{"video_id":"{video_id}"}}')
            videos = self._resolve_nomark_in_logged_in_page(page, evidence)
            if not videos:
                cookies = self._browser_cookie_dict(page)
                share_url = f"https://www.doubao.com/video-sharing?video_id={video_id}"
                with ThreadPoolExecutor(max_workers=1, thread_name_prefix="original-doubao-direct-link") as executor:
                    videos = executor.submit(
                        lambda: asyncio.run(original_doubao_video_parse(share_url, cookies=cookies))
                    ).result(timeout=60)
            videos = [video for video in videos if "watermark" not in str(video.get("url") or "").lower()]
            if not videos:
                raise ValueError("未获取到该视频的原始无水印地址，请确认所选生成账号已登录")
            conversion_id = f"link_{time.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
            output_path = self._save_media_url(
                str(videos[0]["url"]),
                conversion_id,
                self.api.get_settings(),
            )
            preview_url = self.api._media_url_for(str(output_path))
            return {
                "path": str(output_path),
                "name": output_path.name,
                "previewUrl": preview_url,
                "message": "抖音视频直链无水印转换完成",
            }

        evidence = OriginalDoubaoVideoEvidence()
        evidence.add(clean_link)
        try:
            page.goto(clean_link, wait_until="domcontentloaded", timeout=60_000)
            page.wait_for_timeout(1500)
            self._collect_page_video_evidence(page, evidence)
        except Exception:
            # 公开解析仍可能成功，不因分享页加载失败提前终止。
            pass

        cookies = self._browser_cookie_dict(page)
        videos: list[dict[str, Any]] = []
        parser_error = "链接中没有找到可转换的视频"

        try:
            videos = self._resolve_nomark_in_logged_in_page(page, evidence)
        except Exception as exc:
            parser_error = f"登录态解析失败：{exc}"

        if not videos:
            parser_urls = [clean_link, page.url, *evidence.parser_urls()]
            for parser_url in dict.fromkeys(url for url in parser_urls if str(url).startswith(("http://", "https://"))):
                try:
                    with ThreadPoolExecutor(max_workers=1, thread_name_prefix="original-doubao-link") as executor:
                        parsed_videos = executor.submit(
                            lambda url=parser_url: asyncio.run(original_doubao_video_parse(url, cookies=cookies))
                        ).result(timeout=60)
                    if parsed_videos:
                        videos = parsed_videos
                        break
                except Exception as exc:
                    parser_error = str(exc)

        videos = [video for video in videos if "watermark" not in str(video.get("url") or "").lower()]
        if not videos:
            raise ValueError(f"去水印转换失败：{parser_error}；请确认链接有效且所选生成账号已登录")

        conversion_id = f"link_{time.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
        output_path = self._save_media_url(str(videos[0]["url"]), conversion_id, self.api.get_settings())
        preview_url = self.api._media_url_for(str(output_path))
        return {
            "path": str(output_path),
            "name": output_path.name,
            "previewUrl": preview_url,
            "message": "无水印视频转换完成",
        }

    def _save_debug_snapshot(self, page: Any, task_id: str) -> str:
        debug_dir = DATA_DIR / "debug"
        debug_dir.mkdir(parents=True, exist_ok=True)
        try:
            controls = page.locator('button:visible, [role="button"]:visible')
            items = []
            for index in range(min(controls.count(), 80)):
                control = controls.nth(index)
                try:
                    items.append({
                        "text": control.inner_text(timeout=800),
                        "ariaLabel": control.get_attribute("aria-label"),
                        "title": control.get_attribute("title"),
                        "enabled": control.is_enabled(),
                    })
                except Exception:
                    continue
            diagnostic = {
                "taskId": task_id,
                "url": page.url,
                "title": page.title(),
                "controls": items,
            }
            (debug_dir / "last_page.json").write_text(
                json.dumps(diagnostic, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            page.screenshot(path=str(debug_dir / "last_page.png"), full_page=True)
            return "；诊断截图已保存到 data/debug"
        except Exception:
            return ""

    def _open_video_creation(self, page: Any) -> None:
        for attempt in range(3):
            exact = page.get_by_text(re.compile(r"^视频生成$"))
            for index in range(min(exact.count(), 12)):
                item = exact.nth(index)
                if item.is_visible():
                    try:
                        item.click(timeout=4000)
                        page.wait_for_timeout(1000)
                        return
                    except Exception:
                        continue

            names = re.compile(r"视频生成|生成视频|AI\s*视频|AI创作|图片生成视频")
            candidates = page.get_by_text(names)
            for index in range(min(candidates.count(), 12)):
                item = candidates.nth(index)
                if item.is_visible():
                    try:
                        item.click(timeout=3000)
                        page.wait_for_timeout(1000)
                        return
                    except Exception:
                        continue

            if attempt < 2:
                page.wait_for_timeout(1000)
        raise RuntimeError("没有找到“视频生成”入口")

    def _new_conversation_ready(self, page: Any) -> bool:
        welcome_pattern = re.compile(r"有什么我能帮你(?:的)?吗[？?]?\s*$")
        welcome_items = page.get_by_text(welcome_pattern)
        for index in range(min(welcome_items.count(), 12)):
            try:
                if welcome_items.nth(index).is_visible():
                    return True
            except Exception:
                continue
        return False

    def _open_new_conversation(self, page: Any) -> None:
        """Open and verify a clean conversation, retrying three times."""
        for attempt in range(3):
            try:
                page.locator("body").press("Escape")
            except Exception:
                pass

            exact_pattern = re.compile(r"^\s*新对话\s*$")
            candidates = (
                page.get_by_role("button", name=exact_pattern),
                page.get_by_text(exact_pattern),
                page.locator('[aria-label*="新对话"], [title*="新对话"]'),
            )
            clicked = False
            for candidate_group in candidates:
                for index in range(min(candidate_group.count(), 12)):
                    candidate = candidate_group.nth(index)
                    try:
                        if not candidate.is_visible():
                            continue
                        candidate.click(timeout=5_000)
                        clicked = True
                        break
                    except Exception:
                        continue
                if clicked:
                    break

            if clicked:
                page.wait_for_timeout(2_000)
                if self._new_conversation_ready(page):
                    return
            elif attempt < 2:
                page.wait_for_timeout(2_000)

        raise RuntimeError("新对话打开失败：已重试 3 轮，仍未识别到“有什么我能帮你的吗”")

    def _select_model(self, page: Any, model_name: str) -> None:
        model_pattern = re.compile(r"Seedance\s*2(?:\.0)?\s*Fast", re.I)

        # Some versions show the model options directly on the creation page.
        direct_options = page.get_by_text(model_pattern)
        visible_options = []
        for index in range(min(direct_options.count(), 12)):
            option = direct_options.nth(index)
            if option.is_visible():
                visible_options.append(option)
        if visible_options:
            try:
                visible_options[-1].click(timeout=4000)
                page.wait_for_timeout(500)
                return
            except Exception:
                pass

        # Otherwise open the model selector first, then choose Fast explicitly.
        selectors = (
            page.get_by_role("button", name=re.compile(r"Seedance|选择模型|模型", re.I)),
            page.locator('[role="combobox"]:visible'),
        )
        for selector in selectors:
            for index in range(selector.count() - 1, -1, -1):
                control = selector.nth(index)
                try:
                    if control.is_visible():
                        control.click(timeout=4000)
                        page.wait_for_timeout(500)
                        options = page.get_by_text(model_pattern)
                        for option_index in range(options.count() - 1, -1, -1):
                            option = options.nth(option_index)
                            if option.is_visible():
                                option.click(timeout=4000)
                                page.wait_for_timeout(500)
                                return
                except Exception:
                    continue
        raise RuntimeError(f"没有找到模型选项：{model_name}")

    def _configure_video(self, page: Any, ratio: str, duration: int) -> None:
        trigger_pattern = re.compile(r"(自动|3:4|4:3|9:16|16:9|1:1|21:9)\s*[·・]\s*\d+\s*s", re.I)
        triggers = page.get_by_text(trigger_pattern)
        opened = False
        for index in range(triggers.count() - 1, -1, -1):
            trigger = triggers.nth(index)
            try:
                if trigger.is_visible():
                    trigger.click(timeout=4000)
                    page.wait_for_timeout(400)
                    opened = True
                    break
            except Exception:
                continue
        if not opened:
            raise RuntimeError("没有找到“比例 · 时长”设置入口")

        ratio_text = "自动" if ratio in ("auto", "自动") else ratio
        ratio_options = page.get_by_text(ratio_text, exact=True)
        ratio_selected = False
        for index in range(ratio_options.count() - 1, -1, -1):
            option = ratio_options.nth(index)
            try:
                if option.is_visible():
                    option.click(timeout=4000)
                    page.wait_for_timeout(300)
                    ratio_selected = True
                    break
            except Exception:
                continue
        if not ratio_selected:
            raise RuntimeError(f"没有找到画面比例选项：{ratio_text}")

        sliders = page.locator('[role="slider"]:visible, input[type="range"]:visible')
        if sliders.count() == 0:
            # Some page versions close the popover after selecting a ratio.
            for index in range(triggers.count() - 1, -1, -1):
                trigger = triggers.nth(index)
                try:
                    if trigger.is_visible():
                        trigger.click(timeout=4000)
                        page.wait_for_timeout(300)
                        break
                except Exception:
                    continue
            sliders = page.locator('[role="slider"]:visible, input[type="range"]:visible')
        if sliders.count() == 0:
            raise RuntimeError("没有找到视频时长滑块")

        slider = sliders.last
        slider.press("Home", timeout=4000)
        for _ in range(duration - 4):
            slider.press("ArrowRight", timeout=2000)
        page.wait_for_timeout(350)
        page.locator("body").press("Escape")

    def _upload_image(self, page: Any, image_path: str) -> None:
        inputs = page.locator('input[type="file"]')
        for index in range(inputs.count() - 1, -1, -1):
            control = inputs.nth(index)
            accept = (control.get_attribute("accept") or "").lower()
            if not accept or "image" in accept or ".png" in accept or ".jpg" in accept:
                try:
                    control.set_input_files(image_path, timeout=5000)
                    page.wait_for_timeout(1200)
                    return
                except Exception:
                    continue

        upload_names = re.compile(r"上传图片|上传参考图|添加图片|选择图片|参考图")
        buttons = page.get_by_text(upload_names)
        for index in range(min(buttons.count(), 10)):
            button = buttons.nth(index)
            if not button.is_visible():
                continue
            try:
                with page.expect_file_chooser(timeout=3000) as chooser_info:
                    button.click(timeout=3000)
                chooser_info.value.set_files(image_path)
                page.wait_for_timeout(1200)
                return
            except Exception:
                continue
        raise RuntimeError("没有找到图片上传控件；请确认当前已进入 OriginalDoubao 的视频生成页面")

    def _upload_images(self, page: Any, image_paths: list[str]) -> None:
        """Upload every storyboard image, using one chooser when the page supports it."""
        if not image_paths:
            raise ValueError("当前分镜没有可上传的图片素材")
        if len(image_paths) == 1:
            self._upload_image(page, image_paths[0])
            return

        inputs = page.locator('input[type="file"]')
        for index in range(inputs.count() - 1, -1, -1):
            control = inputs.nth(index)
            accept = (control.get_attribute("accept") or "").lower()
            if accept and "image" not in accept and ".png" not in accept and ".jpg" not in accept:
                continue
            if control.get_attribute("multiple") is None:
                continue
            try:
                control.set_input_files(image_paths, timeout=8_000)
                page.wait_for_timeout(max(1_500, len(image_paths) * 700))
                return
            except Exception:
                continue

        # Some OriginalDoubao page versions consume and clear a single-file input after
        # each upload. Re-resolve that input for every file so all assets remain.
        for image_path in image_paths:
            self._upload_image(page, image_path)
            page.wait_for_timeout(500)

    def _upload_audio_file(self, page: Any, audio_path: str) -> None:
        """Upload one audio attachment through an audio-specific or generic file input."""
        inputs = page.locator('input[type="file"]')
        candidates: list[tuple[int, Any]] = []
        for index in range(inputs.count() - 1, -1, -1):
            control = inputs.nth(index)
            accept = (control.get_attribute("accept") or "").lower()
            is_audio = "audio" in accept or any(ext in accept for ext in (".mp3", ".wav", ".m4a", ".aac", ".ogg"))
            if is_audio:
                candidates.append((0, control))
            elif not accept or "*/*" in accept:
                candidates.append((1, control))
        for _, control in sorted(candidates, key=lambda item: item[0]):
            try:
                control.set_input_files(audio_path, timeout=5_000)
                page.wait_for_timeout(1_200)
                return
            except Exception:
                continue

        upload_names = re.compile(r"上传音频|添加音频|上传文件|添加文件|选择文件")
        buttons = page.get_by_text(upload_names)
        for index in range(min(buttons.count(), 12)):
            button = buttons.nth(index)
            if not button.is_visible():
                continue
            try:
                with page.expect_file_chooser(timeout=3_000) as chooser_info:
                    button.click(timeout=3_000)
                chooser_info.value.set_files(audio_path)
                page.wait_for_timeout(1_200)
                return
            except Exception:
                continue
        raise RuntimeError("没有找到音频文件上传控件；请确认当前 OriginalDoubao 视频模型支持音频附件")

    def _upload_audio_files(self, page: Any, audio_paths: list[str]) -> None:
        for audio_path in audio_paths:
            self._upload_audio_file(page, audio_path)
            page.wait_for_timeout(500)

    def _upload_attachments(self, page: Any, attachments: list[dict[str, Any]]) -> None:
        """Upload mixed image/audio attachments in their storyboard order."""
        for attachment in attachments:
            path = str(attachment.get("path") or "").strip()
            if not path:
                continue
            if attachment.get("type") == "audio":
                self._upload_audio_file(page, path)
            else:
                self._upload_image(page, path)
            page.wait_for_timeout(500)

    def _fill_prompt(self, page: Any, prompt: str) -> None:
        selectors = (
            'textarea:visible',
            '[contenteditable="true"]:visible',
            'input[placeholder*="描述"]:visible',
            'input[placeholder*="输入"]:visible',
        )
        for selector in selectors:
            controls = page.locator(selector)
            for index in range(controls.count() - 1, -1, -1):
                control = controls.nth(index)
                try:
                    control.fill(prompt, timeout=4000)
                    return
                except Exception:
                    continue
        raise RuntimeError("没有找到提示词输入框")

    def _click_generate(self, page: Any) -> None:
        exact_names = re.compile(r"^(开始生成|立即生成|生成视频|生成|发送)$")
        for _ in range(90):
            send_button = page.locator("#flow-end-msg-send")
            if send_button.count() > 0:
                try:
                    button = send_button.first
                    aria_disabled = (button.get_attribute("aria-disabled") or "false").lower()
                    loading = (button.get_attribute("data-loading") or "false").lower()
                    if button.is_visible() and button.is_enabled() and aria_disabled != "true" and loading != "true":
                        button.click(timeout=5000)
                        return
                except Exception:
                    pass

            candidates = page.get_by_role("button", name=exact_names)
            for index in range(candidates.count() - 1, -1, -1):
                button = candidates.nth(index)
                try:
                    if button.is_visible() and button.is_enabled():
                        button.click(timeout=5000)
                        return
                except Exception:
                    continue

            # Many OriginalDoubao versions use an icon-only button. Match its text,
            # aria-label or title and wait for image processing to enable it.
            controls = page.locator('button:visible, [role="button"]:visible')
            for index in range(controls.count() - 1, -1, -1):
                control = controls.nth(index)
                try:
                    label = " ".join(filter(None, (
                        control.inner_text(timeout=1000),
                        control.get_attribute("aria-label"),
                        control.get_attribute("title"),
                    )))
                    if re.search(r"开始生成|立即生成|生成视频|^生成$|发送", label) and control.is_enabled():
                        control.click(timeout=5000)
                        return
                except Exception:
                    continue
            page.wait_for_timeout(1000)
        raise RuntimeError("等待90秒后仍没有找到可点击的生成或发送按钮")

    def _listen_for_video_evidence(
        self,
        page: Any,
        conversation_guard: dict[str, str] | None = None,
    ) -> tuple[OriginalDoubaoVideoEvidence, tuple[Any, Any]]:
        evidence = OriginalDoubaoVideoEvidence()

        def belongs_to_bound_conversation() -> bool:
            expected_key = str((conversation_guard or {}).get("key") or "")
            if not expected_key:
                return True
            return self._conversation_key_from_url(str(page.url or "")) == expected_key

        def on_request(request: Any) -> None:
            if not belongs_to_bound_conversation():
                return
            if not any(host in request.url for host in ("doubao.com", "douyin.com", "365yg.com")):
                return
            evidence.add(request.url)
            try:
                evidence.add(request.post_data)
            except Exception:
                pass

        def on_response(response: Any) -> None:
            if not belongs_to_bound_conversation():
                return
            url = response.url
            if not any(host in url for host in ("doubao.com", "douyin.com", "365yg.com")):
                return
            evidence.add(url)
            try:
                content_type = response.headers.get("content-type", "")
                resource_type = response.request.resource_type
                content_length = int(response.headers.get("content-length", "0") or 0)
                if (
                    content_length <= 2_000_000
                    and (
                        "json" in content_type
                        or "text" in content_type
                        or resource_type in {"xhr", "fetch"}
                    )
                ):
                    evidence.add(response.text()[:2_000_000])
            except Exception:
                pass

        page.on("request", on_request)
        page.on("response", on_response)
        return evidence, (on_request, on_response)

    def _stop_video_evidence_listener(self, page: Any, listeners: tuple[Any, Any]) -> None:
        request_listener, response_listener = listeners
        try:
            page.remove_listener("request", request_listener)
            page.remove_listener("response", response_listener)
        except Exception:
            pass

    def _monitor_result(
        self,
        page: Any,
        task_id: str,
        before_videos: int,
        before_video_fingerprints: set[str],
        evidence: OriginalDoubaoVideoEvidence,
        baseline_evidence: OriginalDoubaoVideoEvidence,
        listeners: tuple[Any, Any],
        payload: dict[str, Any],
        conversation: dict[str, str],
    ) -> None:
        confirmation_sent = False
        manual_confirmation_waiting = False
        authorized_material_confirmation_rounds = 0
        for tick in range(900):
            page.wait_for_timeout(2000)
            if not page.context.pages:
                raise RuntimeError("OriginalDoubao 浏览器已关闭")
            self._dismiss_download_desktop_dialog(page)
            expected_conversation_key = str(conversation.get("key") or "")
            current_conversation_key = self._conversation_key_from_url(str(page.url or ""))
            if expected_conversation_key and current_conversation_key != expected_conversation_key:
                self.api._update_task(
                    task_id,
                    status="returning_to_conversation",
                    statusText="检测到 OriginalDoubao 已切换会话，正在返回本任务绑定会话",
                    requiresManualVerification=False,
                )
                if not self._return_to_generation_conversation(page, conversation):
                    page.wait_for_timeout(1_000)
                continue
            if self._visible_authorized_material_dialog(page) is not None:
                if authorized_material_confirmation_rounds < 3:
                    authorized_material_confirmation_rounds += 1
                    current_round = authorized_material_confirmation_rounds
                    self.api._update_task(
                        task_id,
                        status="confirming_authorization",
                        statusText=f"检测到安全确认，正在校验并自动确认（{current_round}/3）",
                        progress=54,
                        requiresManualVerification=False,
                    )
                    if self._confirm_authorized_material_dialog(page):
                        manual_confirmation_waiting = False
                        self.api._update_task(
                            task_id,
                            status="generating",
                            statusText=f"安全确认校验已通过（{current_round}/3），正在继续生成视频",
                            progress=55,
                            requiresManualVerification=False,
                        )
                        continue
                if not manual_confirmation_waiting:
                    manual_confirmation_waiting = True
                    self.api._update_task(
                        task_id,
                        status="waiting_confirmation",
                        statusText="安全确认自动校验未通过，请在 OriginalDoubao 浏览器中人工确认",
                        progress=54,
                        requiresManualVerification=True,
                    )
                continue
            if self._has_visible_generation_confirmation_dialog(page):
                if not manual_confirmation_waiting:
                    manual_confirmation_waiting = True
                    self.api._update_task(
                        task_id,
                        status="waiting_confirmation",
                        statusText="OriginalDoubao 弹出生成确认框，请在 OriginalDoubao 浏览器中人工确认",
                        progress=54,
                        requiresManualVerification=True,
                    )
                continue
            if manual_confirmation_waiting:
                manual_confirmation_waiting = False
                self.api._update_task(
                    task_id,
                    status="generating",
                    statusText="人工确认已完成，正在等待生成结果",
                    progress=55,
                    requiresManualVerification=False,
                )
            blocked_reason, requires_manual_verification = self._generation_block_reason(page)
            if blocked_reason:
                if "登录已过期" in blocked_reason or "会话失效" in blocked_reason:
                    self.api.mark_account_login_expired(self.account_id)
                if (
                    "今日视频生成免费次数已用完" in blocked_reason
                    or "视频生成额度不足" in blocked_reason
                ):
                    self.api.mark_account_quota_exhausted(self.account_id, reason=blocked_reason)
                self._stop_video_evidence_listener(page, listeners)
                self.api._update_task(
                    task_id,
                    status="failed",
                    statusText=blocked_reason,
                    progress=0,
                    resultPath="",
                    resultUrl="",
                    requiresManualVerification=requires_manual_verification,
                )
                if self._is_quota_exhausted_reason(blocked_reason):
                    self._close_generation_window(page)
                return
            if not confirmation_sent and self._generation_confirmation_requested(page):
                confirmation_sent = True
                self.api._update_task(
                    task_id,
                    status="submitting",
                    statusText="OriginalDoubao 请求生成确认，正在发送“我确认开始生成视频”",
                    progress=52,
                )
                self._fill_prompt(
                    page,
                    "我确认开始生成视频",
                )
                self._click_generate(page)
                self.api._update_task(
                    task_id,
                    status="generating",
                    statusText="已发送生成确认，正在等待生成结果",
                    progress=55,
                )
                continue
            if tick % 5 == 0:
                waiting_message = self._generation_waiting_message(page)
                if waiting_message:
                    self.api._update_task(
                        task_id,
                        status="generating",
                        statusText=waiting_message,
                    )
            video_count = page.locator("video").count()
            current_video_fingerprints = self._video_fingerprints(page)
            has_new_video_source = bool(current_video_fingerprints - before_video_fingerprints)
            has_new_media_url = any(
                media_url not in baseline_evidence.media_urls
                for media_url in evidence.media_urls
            )
            if (
                video_count > before_videos
                or has_new_video_source
                or has_new_media_url
            ):
                self.api._update_task(
                    task_id,
                    status="sharing",
                    statusText="视频已返回，正在读取视频标识",
                    progress=94,
                )
                page_evidence = OriginalDoubaoVideoEvidence()
                self._collect_page_video_evidence(page, page_evidence)
                evidence.add_new_from(page_evidence, baseline_evidence)
                if not evidence.video_ids:
                    for media_url in reversed(evidence.media_urls):
                        video_id = self._video_id_from_media_url(media_url)
                        if video_id:
                            evidence.add(f'{{"video_id":"{video_id}"}}')
                            break
                # A share URL is optional. The authenticated fplay route only
                # needs the generated video's ID, which normally appears in
                # OriginalDoubao's JSON responses or media URLs. Touch the Share UI
                # only as a last-resort compatibility fallback.
                if not evidence.video_ids:
                    share_url = self._obtain_video_share_url(page, evidence)
                    if share_url:
                        evidence.add(share_url)
                self._stop_video_evidence_listener(page, listeners)
                self.api._update_task(
                    task_id,
                    status="downloading",
                    statusText="视频已生成，正在解析并保存无水印原片",
                    progress=96,
                )
                must_persist_result = bool(payload.get("persistResult"))
                result_path, result_message = self._download_nomark_video(
                    page,
                    evidence,
                    task_id,
                    force=must_persist_result,
                )
                should_download = self.api.get_settings().get("autoDownload", True) or must_persist_result
                result_watermarked = False
                if not result_path and should_download:
                    official_path, official_message = self._download_official_unwatermarked(
                        page,
                        task_id,
                        force=must_persist_result,
                    )
                    result_path = official_path
                    result_message = official_message if official_path else f"{result_message}；{official_message}"
                if not result_path and should_download:
                    self.api._update_task(
                        task_id,
                        status="downloading",
                        statusText="无水印解析失败，正在保存页面有水印视频",
                        progress=97,
                    )
                    watermarked_path, watermarked_message = self._download_watermarked_video(
                        page,
                        evidence,
                        task_id,
                        force=must_persist_result,
                    )
                    result_path = watermarked_path
                    if watermarked_path:
                        result_watermarked = True
                        result_message = watermarked_message
                    else:
                        result_message = f"{result_message}；{watermarked_message}"
                if not result_path and should_download:
                    self.api._update_task(
                        task_id,
                        status="failed",
                        statusText=result_message,
                        progress=100,
                        resultPath="",
                        resultUrl="",
                    )
                    return
                # 统一转成浏览器可播放的 H.264（HEVC 原片会被转码），本地与服务器都用它。
                display_path = self.api._webview_preview_path(result_path) if result_path else ""
                result_file_id = ""
                if result_path and payload.get("persistResult"):
                    upload_error: Exception | None = None
                    for attempt in range(1, 4):
                        self.api._update_task(
                            task_id,
                            status="uploading",
                            statusText=f"视频已生成，正在上传服务器（{attempt}/3）",
                            progress=98,
                        )
                        try:
                            uploaded = self.api.upload_local_file(str(payload.get("token") or ""), str(display_path))
                            result_file_id = str(uploaded.get("id") or "")
                            if not result_file_id:
                                raise ValueError("服务器没有返回视频文件 ID")
                            upload_error = None
                            break
                        except Exception as exc:
                            upload_error = exc
                            if attempt < 3:
                                page.wait_for_timeout(attempt * 1_500)
                    if upload_error is not None:
                        self.api._update_task(
                            task_id,
                            status="failed",
                            statusText=f"视频已生成，但上传服务器失败：{upload_error}",
                            progress=100,
                            resultPath=str(display_path),
                            resultUrl=self.api._media_url_for(str(display_path)),
                            resultFileId="",
                            resultWatermarked=result_watermarked,
                        )
                        return
                window_closed = False
                if result_file_id:
                    self.api._update_task(
                        task_id,
                        status="finalizing",
                        statusText="视频已上传服务器，正在关闭 OriginalDoubao 窗口并释放账号",
                        progress=99,
                    )
                    window_closed = self._close_generation_window(page)
                    if window_closed:
                        # Remove this now-closed worker before the succeeded
                        # update releases its account. Otherwise a generation
                        # started in that tiny interval could be queued onto a
                        # browser context that is already shutting down.
                        self.api._retire_worker(self.account_id, self)
                if result_file_id and result_watermarked:
                    final_message = "无水印解析失败，已上传并显示有水印视频"
                elif result_file_id:
                    final_message = "视频已生成并上传服务器"
                else:
                    final_message = result_message
                if result_file_id and not window_closed:
                    final_message += "；OriginalDoubao 窗口自动关闭失败"
                self.api._update_task(
                    task_id,
                    status="succeeded",
                    statusText=final_message,
                    progress=100,
                    resultPath=str(display_path) if display_path else "",
                    resultUrl=self.api._media_url_for(str(display_path)) if display_path else "",
                    resultFileId=result_file_id,
                    resultWatermarked=result_watermarked,
                    requiresManualVerification=False,
                )
                return
            progress = min(92, 55 + tick // 8)
            self.api._update_task(task_id, progress=progress)
        self._stop_video_evidence_listener(page, listeners)
        raise RuntimeError("等待生成结果超时")

    def _generation_waiting_message(self, page: Any) -> str:
        try:
            text = page.locator("body").inner_text(timeout=2000)
        except Exception:
            return ""
        return self._generation_waiting_message_from_text(text)

    def _generation_waiting_message_from_text(self, text: str) -> str:
        """Normalize OriginalDoubao's submitted/generating copies into one task status."""

        clean_text = re.sub(r"[*_`]+", "", str(text))
        normalized = re.sub(r"\s+", "", clean_text)
        is_generating = bool(
            re.search(r"视频生成(?:已)?提交|视频生成中", normalized)
            or "视频生成好后，我会主动发送给你" in normalized
            or (
                re.search(r"本次使用Seedance[^，。]{0,40}生成", normalized, re.I)
                and "预计等待" in normalized
            )
        )
        if not is_generating:
            return ""
        wait_match = re.search(r"预计等待(?:约)?(\d+)分钟", normalized)
        model_match = re.search(
            r"本次\s*使用\s*(Seedance[^，。\r\n]{0,40}?)\s*生成",
            clean_text,
            re.I,
        )
        model_name = re.sub(r"\s+", " ", model_match.group(1)).strip() if model_match else ""
        if wait_match and model_name:
            return f"已提交到 {model_name}，OriginalDoubao 预计等待 {wait_match.group(1)} 分钟，正在生成中"
        if wait_match:
            return f"视频生成已提交，OriginalDoubao 预计等待 {wait_match.group(1)} 分钟，正在生成中"
        if model_name:
            return f"已提交到 {model_name}，OriginalDoubao 正在生成中"
        return "视频生成已提交，OriginalDoubao 正在生成中"

    @staticmethod
    def _conversation_key_from_url(url: str) -> str:
        """Extract a stable OriginalDoubao conversation key from known URL shapes."""

        try:
            parsed = urlparse(str(url or ""))
        except ValueError:
            return ""
        query = parse_qs(parsed.query)
        for name in (
            "conversation_id", "conversationId", "chat_id", "chatId", "thread_id", "threadId",
        ):
            value = str((query.get(name) or [""])[0]).strip()
            if value:
                return f"{name}:{value}"
        match = re.search(r"/(?:chat|conversation|thread)/([^/?#]+)", parsed.path, re.I)
        if match:
            return f"path:{match.group(1)}"
        return ""

    def _capture_generation_conversation(self, page: Any, task_id: str) -> dict[str, str]:
        """Capture the remote conversation created by the generation submit."""

        deadline = time.monotonic() + 12
        last_url = str(page.url or "")
        local_candidate: dict[str, str] | None = None
        while time.monotonic() < deadline:
            last_url = str(page.url or last_url)
            key = self._conversation_key_from_url(last_url)
            if key:
                conversation_id = key.split(":", 1)[-1]
                candidate = {"id": conversation_id, "key": key, "url": last_url}
                # OriginalDoubao first assigns /chat/local_* and then replaces it with
                # the server conversation ID. Wait for that transition so a
                # legitimate URL upgrade is not mistaken for a switched chat.
                if not conversation_id.lower().startswith("local_"):
                    return candidate
                local_candidate = candidate
            page.wait_for_timeout(250)
        if local_candidate is not None:
            return local_candidate
        local_id = f"task-{task_id}"
        return {"id": local_id, "key": "", "url": last_url}

    def _return_to_generation_conversation(self, page: Any, conversation: dict[str, str]) -> bool:
        target_url = str(conversation.get("url") or "").strip()
        expected_key = str(conversation.get("key") or "")
        if not target_url or not expected_key:
            return False
        try:
            page.goto(target_url, wait_until="domcontentloaded", timeout=30_000)
            page.wait_for_timeout(1_000)
            return self._conversation_key_from_url(str(page.url or "")) == expected_key
        except Exception:
            return False

    def _close_generation_window(self, page: Any) -> bool:
        """Close the account browser after its persisted result reaches the server.

        The persistent profile remains on disk, so the next task can start a new
        browser with the same login session. Closing the whole context (instead
        of navigating to a new chat) also guarantees that no popup/tab keeps the
        visible OriginalDoubao window alive.
        """

        try:
            page.context.close()
            return True
        except Exception:
            return False

    @staticmethod
    def _is_quota_exhausted_reason(reason: str) -> bool:
        normalized = re.sub(r"\s+", "", str(reason or ""))
        return bool(
            re.search(r"今日视频生成免费次数(?:已)?用完(?:了)?", normalized)
            or "视频生成额度不足" in normalized
        )

    def _visible_download_desktop_dialog(self, page: Any) -> Any | None:
        pattern = re.compile(r"下载.{0,12}电脑版|电脑版.{0,12}下载")
        selectors = (
            '[role="dialog"]:visible',
            '.semi-modal:visible',
            '[class*="modal"]:visible',
            '[class*="dialog"]:visible',
        )
        for selector in selectors:
            try:
                dialogs = page.locator(selector)
                for index in range(min(dialogs.count(), 12)):
                    dialog = dialogs.nth(index)
                    if dialog.is_visible() and pattern.search(dialog.inner_text(timeout=800)):
                        return dialog
            except Exception:
                continue
        return None

    def _dismiss_download_desktop_dialog(self, page: Any) -> None:
        """Best-effort dismissal of OriginalDoubao's desktop-download promotion."""

        for attempt in range(3):
            dialog = self._visible_download_desktop_dialog(page)
            if dialog is None:
                return
            close_candidates = (
                dialog.locator(
                    'button[aria-label*="关闭"], [role="button"][aria-label*="关闭"], '
                    'button[title*="关闭"], [role="button"][title*="关闭"]'
                ),
                dialog.get_by_role("button", name=re.compile(r"^(?:关闭|取消|暂不|以后再说|×|X)$", re.I)),
                dialog.locator(
                    '[class*="close"]:visible, [class*="Close"]:visible, '
                    '[class*="xicon"]:visible, [class*="XIcon"]:visible'
                ),
            )
            clicked = False
            for candidates in close_candidates:
                try:
                    for index in range(min(candidates.count(), 8)):
                        control = candidates.nth(index)
                        if not control.is_visible():
                            continue
                        control.click(timeout=1_500)
                        clicked = True
                        break
                except Exception:
                    continue
                if clicked:
                    break
            if clicked:
                page.wait_for_timeout(300)
                if self._visible_download_desktop_dialog(page) is None:
                    return
            try:
                page.keyboard.press("Escape")
            except Exception:
                pass
            page.wait_for_timeout(500)
            if self._visible_download_desktop_dialog(page) is None:
                return
            if attempt < 2:
                page.wait_for_timeout(500)

    def _has_visible_generation_confirmation_dialog(self, page: Any) -> bool:
        """Return whether a DOM modal requires the user to confirm generation."""

        selectors = (
            '[role="dialog"]:visible',
            '.semi-modal:visible',
            '[class*="modal"]:visible',
            '[class*="dialog"]:visible',
        )
        excluded_pattern = re.compile(
            r"验证|滑块|拖拽|登录|删除对话|退出登录|"
            r"生成失败|不支持|额度|违规|侵权|肖像保护"
        )
        confirm_pattern = re.compile(r"^(?:确认|确定|继续|同意|我知道了|继续生成|确认生成|确定生成)$")
        for selector in selectors:
            try:
                dialogs = page.locator(selector)
                for index in range(min(dialogs.count(), 12)):
                    dialog = dialogs.nth(index)
                    text = re.sub(r"\s+", "", dialog.inner_text(timeout=1_000))
                    if not text or excluded_pattern.search(text):
                        continue
                    if not re.search(r"视频|生成|创作|内容", text):
                        continue
                    controls = dialog.locator('button:visible, [role="button"]:visible')
                    for control_index in range(min(controls.count(), 12)):
                        control = controls.nth(control_index)
                        labels = (
                            control.inner_text(timeout=500),
                            control.get_attribute("aria-label"),
                            control.get_attribute("title"),
                        )
                        if any(confirm_pattern.fullmatch(str(label or "").strip()) for label in labels):
                            return True
            except Exception:
                continue
        return False

    def _visible_authorized_material_dialog(self, page: Any) -> Any | None:
        """Find OriginalDoubao's authorized-material safety confirmation dialog."""

        selectors = (
            '[role="dialog"]:visible',
            '.semi-modal:visible',
            '[class*="modal"]:visible',
            '[class*="dialog"]:visible',
        )
        authorization_pattern = re.compile(
            r"你在本功能中上传[、，,]?使用的素材[，,]?均已获充分授权"
        )
        for selector in selectors:
            try:
                dialogs = page.locator(selector)
                for index in range(min(dialogs.count(), 12)):
                    dialog = dialogs.nth(index)
                    text = re.sub(r"\s+", "", dialog.inner_text(timeout=1_000))
                    if "安全确认" in text and authorization_pattern.search(text):
                        return dialog
            except Exception:
                continue
        return None

    def _confirm_authorized_material_dialog(self, page: Any) -> bool:
        """Click the primary confirmation button and verify that the dialog closes."""

        dialog = self._visible_authorized_material_dialog(page)
        if dialog is None:
            return False

        confirm_pattern = re.compile(r"^(?:确认|确定|同意|继续生成|确认生成|确定生成)$")
        control_selectors = (
            '.semi-button-primary:visible',
            'button[class*="primary"]:visible',
            '[role="button"][class*="primary"]:visible',
            'button:visible, [role="button"]:visible',
        )
        clicked = False
        for selector in control_selectors:
            try:
                controls = dialog.locator(selector)
                for index in range(min(controls.count(), 12)):
                    control = controls.nth(index)
                    labels = (
                        control.inner_text(timeout=500),
                        control.get_attribute("aria-label"),
                        control.get_attribute("title"),
                    )
                    if not any(confirm_pattern.fullmatch(str(label or "").strip()) for label in labels):
                        continue
                    if not control.is_visible() or not control.is_enabled():
                        continue
                    control.click(timeout=3_000)
                    clicked = True
                    break
            except Exception:
                continue
            if clicked:
                break
        if not clicked:
            return False

        for _ in range(20):
            page.wait_for_timeout(250)
            if self._visible_authorized_material_dialog(page) is None:
                return True
        return False

    def _generation_confirmation_requested(self, page: Any) -> bool:
        """Detect OriginalDoubao asking for a redundant confirmation before generation."""

        normalized = re.sub(r"\s+", "", self._page_and_frame_text(page))
        return bool(
            "确认后我直接生成" in normalized
            or re.search(r"确认后[，,：:]?我再开始生成视频", normalized)
            or re.search(
                r"(?:请|等待|等你|收到你).{0,8}确认.{0,24}(?:我|就).{0,8}(?:直接|开始|立即)?生成",
                normalized,
            )
        )

    def _generation_block_reason(self, page: Any) -> tuple[str, bool]:
        """Return a user-facing reason when OriginalDoubao rejects this generation."""

        text = self._page_and_frame_text(page)
        normalized = re.sub(r"\s+", "", text)
        if self._has_visible_verification_surface(page) or (
            "请选择所有符合上述描述的图片" in normalized
            and ("拖拽到下方" in normalized or "拖拽到这里" in normalized)
        ) or (
            "拖拽到这里" in normalized
            and "刷新" in normalized
            and "反馈" in normalized
            and "提交" in normalized
        ) or re.search(
            r"(?:安全|人机|滑块|图片)验证|请(?:先)?完成(?:人脸|真人|身份)?验证|"
            r"(?:人脸|真人|身份)?验证后继续|请完成.{0,16}验证|完成验证后|验证通过后|"
            r"(?:请|按住).{0,12}(?:拖动|滑动).{0,12}(?:滑块|拼图)|"
            r"请依次点击|点击图中|请选择.{0,24}(?:图片|图案)",
            normalized,
        ):
            return (
                "OriginalDoubao 触发人工安全验证，本次任务已停止；请到设置中心打开对应生成账号，"
                "人工完成验证后重新生成",
                True,
            )
        if (
            re.search(r"疑似包含(?:侵权|违规|侵权/违规)内容", normalized)
            or ("无法返回该内容" in normalized and "换个主题" in normalized)
            or ("生成额度未扣除" in normalized and re.search(r"侵权|违规|内容风险", normalized))
        ):
            return (
                "OriginalDoubao 判定生成内容疑似侵权或违规，未返回视频；请更换参考图或主题后重试",
                False,
            )
        if "视频生成失败" in normalized and "生成额度未扣除" in normalized:
            return "OriginalDoubao 视频生成失败，本次生成额度未扣除；请重试", False
        if (
            "出于肖像保护考虑" in normalized
            or "暂不支持上传真实人脸素材作为参考" in normalized
            or re.search(r"(?:检测到|图片中|画面中|素材中|参考图中).{0,16}(?:人脸|真人)", normalized)
            or re.search(r"(?:人脸|真人).{0,24}(?:无法|不能|不支持|违规|风险|审核未通过|生成失败)", normalized)
            or re.search(r"(?:无法|不能|不支持).{0,16}(?:人脸|真人)", normalized)
        ):
            return (
                "OriginalDoubao 检测到人脸或真人内容并拒绝生成；请更换不含受限人脸内容的参考图后重试",
                False,
            )
        if any(
            hint in normalized
            for hint in (
                "登录已过期", "登录过期", "登录已失效", "登录失效", "登录状态已失效",
                "登录状态失效", "会话已过期", "会话过期", "会话失效", "重新登录",
                "需要登录", "请先登录", "请登录", "登录超时", "登录时间过长",
            )
        ):
            return (
                "生成账号登录已过期或会话失效，请到设置中心打开对应账号重新登录后再试",
                True,
            )
        if re.search(r"今日视频生成免费次数(?:已)?用完", normalized):
            return "OriginalDoubao 今日视频生成免费次数已用完，请切换有可用额度的账号或明日再试", False
        if "暂时无法使用专业版功能" in normalized and "视频" in normalized:
            return "当前生成账号暂时无法使用所选视频生成功能，请切换账号或生成模式", False
        if re.search(r"(?:创作|生成)(?:次数|额度).{0,8}(?:用完|不足)", normalized):
            return "当前生成账号的视频额度不足，请切换有可用额度的账号后重试", False
        return "", False

    def _page_and_frame_text(self, page: Any) -> str:
        """Collect visible verification copy from the page, popups and child frames."""

        texts: list[str] = []
        try:
            pages = list(page.context.pages)
        except Exception:
            pages = [page]
        for current_page in pages:
            try:
                frames = list(current_page.frames)
            except Exception:
                frames = [current_page.main_frame]
            for frame in frames:
                try:
                    value = frame.locator("body").inner_text(timeout=700)
                    if value:
                        texts.append(value)
                except Exception:
                    continue
        return "\n".join(texts)

    def _has_visible_verification_surface(self, page: Any) -> bool:
        """Detect ByteDance captcha shells even when their copy is rendered in a canvas."""

        selector = ",".join((
            'iframe[src*="captcha" i]:visible',
            'iframe[src*="verifycenter" i]:visible',
            'iframe[src*="challenge" i]:visible',
            'iframe[title*="验证"]:visible',
            '#captcha_container:visible',
            '[class*="captcha_verify"]:visible',
            '[class*="secsdk-captcha"]:visible',
            '[class*="captcha-container"]:visible',
            '[class*="captchaContainer"]:visible',
        ))
        try:
            pages = list(page.context.pages)
        except Exception:
            pages = [page]
        for current_page in pages:
            try:
                if current_page.locator(selector).count() > 0:
                    return True
                page_url = str(current_page.url or "").lower()
                if current_page is not page and re.search(r"captcha|verifycenter|challenge", page_url):
                    return True
            except Exception:
                continue
        return False

    def _video_id_from_media_url(self, media_url: str) -> str:
        """Read the MP4 comment metadata without downloading the whole video."""

        headers = {
            "Accept": "*/*",
            "Range": "bytes=0-131071",
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 Chrome/151.0.0.0 Safari/537.36"
            ),
        }
        try:
            prefix = bytearray()
            with httpx.stream(
                "GET",
                media_url,
                headers=headers,
                follow_redirects=True,
                timeout=30,
            ) as response:
                response.raise_for_status()
                for chunk in response.iter_bytes(chunk_size=16 * 1024):
                    prefix.extend(chunk)
                    if len(prefix) >= 128 * 1024:
                        break
            match = re.search(rb"vid:(v[0-9a-z]{20,80})", prefix, re.IGNORECASE)
            return match.group(1).decode("ascii") if match else ""
        except Exception:
            return ""

    def _video_fingerprints(self, page: Any) -> set[str]:
        fingerprints: set[str] = set()
        try:
            videos = page.locator("video")
            for index in range(videos.count()):
                video = videos.nth(index)
                for attribute in ("src", "poster"):
                    value = video.get_attribute(attribute)
                    if value:
                        fingerprints.add(value)
                current_src = video.evaluate("video => video.currentSrc || ''")
                if current_src:
                    fingerprints.add(str(current_src))
        except Exception:
            pass
        return fingerprints

    def _share_url_from_page(self, page: Any, evidence: OriginalDoubaoVideoEvidence) -> str:
        for selector, attribute in (
            ('a[href*="doubao.com/video-sharing"]', "href"),
            ('a[href*="doubao.com/thread/"]', "href"),
            ('input[value*="doubao.com/"]', "value"),
            ('textarea', "value"),
        ):
            try:
                items = page.locator(selector)
                for index in range(items.count()):
                    value = items.nth(index).get_attribute(attribute)
                    if value:
                        evidence.add(value)
            except Exception:
                continue
        try:
            evidence.add(page.locator("body").inner_text(timeout=2000))
        except Exception:
            pass
        video_shares = [url for url in evidence.share_urls if "/video-sharing" in url]
        return video_shares[-1] if video_shares else ""

    def _obtain_video_share_url(self, page: Any, evidence: OriginalDoubaoVideoEvidence) -> str:
        existing = self._share_url_from_page(page, evidence)
        if existing:
            return existing

        share_controls = []
        for locator in (
            page.get_by_role("button", name=re.compile(r"分享")),
            page.locator('[aria-label*="分享"], [title*="分享"]'),
            page.get_by_text(re.compile(r"^分享$")),
        ):
            try:
                for index in range(locator.count()):
                    item = locator.nth(index)
                    if item.is_visible() and item.is_enabled():
                        share_controls.append(item)
            except Exception:
                continue

        for control in reversed(share_controls):
            try:
                control.click(timeout=4000)
                page.wait_for_timeout(800)
                share_url = self._share_url_from_page(page, evidence)
                if share_url:
                    return share_url

                copy_controls = page.get_by_text(re.compile(r"复制链接|复制分享链接|^复制$"))
                for index in reversed(range(copy_controls.count())):
                    copy_control = copy_controls.nth(index)
                    if not copy_control.is_visible():
                        continue
                    try:
                        page.context.grant_permissions(
                            ["clipboard-read", "clipboard-write"],
                            origin="https://www.doubao.com",
                        )
                    except Exception:
                        pass
                    copy_control.click(timeout=3000)
                    page.wait_for_timeout(300)
                    try:
                        copied = page.evaluate("navigator.clipboard.readText()")
                        evidence.add(copied)
                    except Exception:
                        pass
                    share_url = self._share_url_from_page(page, evidence)
                    if share_url:
                        return share_url
            except Exception:
                continue
            finally:
                try:
                    page.keyboard.press("Escape")
                except Exception:
                    pass
        return ""

    def _collect_page_video_evidence(self, page: Any, evidence: OriginalDoubaoVideoEvidence) -> None:
        evidence.add(page.url)
        try:
            evidence.add(page.content())
        except Exception:
            pass
        videos = page.locator("video")
        for index in range(videos.count()):
            video = videos.nth(index)
            for attribute in ("src", "poster"):
                try:
                    evidence.add(video.get_attribute(attribute))
                except Exception:
                    pass

    def _resolve_nomark_in_logged_in_page(
        self,
        page: Any,
        evidence: OriginalDoubaoVideoEvidence,
    ) -> list[dict[str, Any]]:
        """Use the logged-in page to resolve media inside the browser context."""

        video_ids = list(reversed(evidence.video_ids))
        if not video_ids:
            return []
        models = page.evaluate(
            """
            async (videoIds) => {
              const models = [];
              for (const videoId of videoIds) {
                try {
                  const response = await fetch(
                    '/alice/resource/get_video_model',
                    {
                      method: 'POST',
                      credentials: 'include',
                      headers: {'content-type': 'application/json'},
                      body: JSON.stringify({params: [{uri: videoId, resource_id: ''}]})
                    }
                  );
                  const result = await response.json();
                  for (const item of result?.data?.results || []) {
                    let model = item?.video_model_result?.video_model;
                    if (typeof model === 'string') {
                      try { model = JSON.parse(model); } catch (_) { model = null; }
                    }
                    if (model?.fallback_api) {
                      models.push({video_id: videoId, fallback_api: model.fallback_api});
                    }
                  }
                } catch (_) {}
              }
              return models;
            }
            """,
            video_ids,
        )
        for model in models or []:
            try:
                with ThreadPoolExecutor(max_workers=1, thread_name_prefix="original-doubao-fplay") as executor:
                    videos = executor.submit(
                        lambda item=model: asyncio.run(
                            original_doubao_fplay_parse(str(item["fallback_api"]), str(item["video_id"]))
                        )
                    ).result(timeout=60)
                if videos:
                    return videos
            except Exception:
                continue
        return []

    def _browser_cookie_dict(self, page: Any) -> dict[str, str]:
        try:
            return {
                str(cookie["name"]): str(cookie["value"])
                for cookie in page.context.cookies("https://www.doubao.com")
            }
        except Exception:
            return {}

    def _save_media_url(self, media_url: str, task_id: str, settings: dict[str, Any]) -> Path:
        return save_media_url(media_url, task_id, settings)

    def _download_nomark_video(
        self,
        page: Any,
        evidence: OriginalDoubaoVideoEvidence,
        task_id: str,
        *,
        force: bool = False,
    ) -> tuple[str, str]:
        settings = self.api.get_settings()
        if not force and not settings.get("autoDownload", True):
            return "", "OriginalDoubao 视频已生成，自动下载已关闭"

        parser_error = "没有监听到本次视频的 video_id 或分享链接"
        cookies = self._browser_cookie_dict(page)
        real_share_urls = [
            url for url in reversed(evidence.share_urls)
            if "/video-sharing" in url and "share_id=" in url and "video_id=" in url
        ]
        try:
            authenticated_videos = self._resolve_nomark_in_logged_in_page(page, evidence)
            if authenticated_videos:
                output_path = self._save_media_url(
                    str(authenticated_videos[0]["url"]),
                    task_id,
                    settings,
                )
                return str(output_path), f"已通过 OriginalDoubao 登录态保存无水印流：{output_path.name}"
        except Exception as exc:
            parser_error = f"登录态解析失败：{exc}"

        for share_url in real_share_urls:
            try:
                with ThreadPoolExecutor(max_workers=1, thread_name_prefix="original-doubao-share") as executor:
                    videos = executor.submit(
                        lambda: asyncio.run(original_doubao_video_parse(share_url, cookies=cookies))
                    ).result(timeout=60)
                if not videos:
                    continue
                media_url = str(videos[0]["url"])
                if "watermark" in media_url.lower():
                    parser_error = "公开分享接口只返回带水印视频"
                    continue
                output_path = self._save_media_url(media_url, task_id, settings)
                return str(output_path), f"已通过 OriginalDoubao 真实分享链接保存无水印视频：{output_path.name}"
            except Exception as exc:
                parser_error = f"分享链接解析失败：{exc}"

        for parser_url in evidence.parser_urls():
            if parser_url in real_share_urls:
                continue
            try:
                # Playwright's synchronous API may already be running on top of
                # an asyncio loop. Resolve the async parser in its own thread so
                # asyncio.run() always owns the loop it creates.
                with ThreadPoolExecutor(max_workers=1, thread_name_prefix="original-doubao-parse") as executor:
                    videos = executor.submit(
                        lambda: asyncio.run(original_doubao_video_parse(parser_url, cookies=cookies))
                    ).result(timeout=60)
                if not videos:
                    parser_error = "解析接口没有返回可下载的视频"
                    continue
                media_url = str(videos[0]["url"])
                if "watermark" in media_url.lower():
                    parser_error = "解析接口只返回带水印视频"
                    continue
                output_path = self._save_media_url(media_url, task_id, settings)
                return str(output_path), f"已通过登录态解析保存：{output_path.name}"
            except Exception as exc:
                parser_error = str(exc)
        return "", f"登录态解析失败：{parser_error}"

    def _download_official_unwatermarked(
        self,
        page: Any,
        task_id: str,
        *,
        force: bool = False,
    ) -> tuple[str, str]:
        settings = self.api.get_settings()
        if not force and not settings.get("autoDownload", True):
            return "", "OriginalDoubao 视频已生成，自动下载已关闭"

        # Only use an explicit official no-watermark control. Do not extract
        # hidden media URLs or intercept private responses.
        names = re.compile(r"无水印下载|下载无水印|下载.*无水印")
        options = page.get_by_text(names)
        for index in range(min(options.count(), 12)):
            option = options.nth(index)
            try:
                if not option.is_visible():
                    continue
                with page.expect_download(timeout=15_000) as download_info:
                    option.click(timeout=5000)
                download = download_info.value
                output_dir = Path(str(settings["outputDir"])).resolve()
                output_dir.mkdir(parents=True, exist_ok=True)
                suffix = Path(download.suggested_filename).suffix or ".mp4"
                output_path = output_dir / f"original_doubao_{task_id}{suffix}"
                download.save_as(str(output_path))
                return str(output_path), f"无水印视频已通过 OriginalDoubao 官方入口保存：{output_path.name}"
            except Exception:
                continue
        return "", "OriginalDoubao 视频已生成，但页面未提供明确的官方无水印下载入口"

    def _download_watermarked_video(
        self,
        page: Any,
        evidence: OriginalDoubaoVideoEvidence,
        task_id: str,
        *,
        force: bool = False,
    ) -> tuple[str, str]:
        """Save the page-playable rendition when no-watermark parsing fails."""

        settings = self.api.get_settings()
        if not force and not settings.get("autoDownload", True):
            return "", "OriginalDoubao 视频已生成，自动下载已关闭"

        candidates: list[str] = []
        try:
            videos = page.locator("video")
            for index in range(videos.count() - 1, -1, -1):
                video = videos.nth(index)
                for value in (
                    video.evaluate("element => element.currentSrc || ''"),
                    video.get_attribute("src"),
                ):
                    clean_value = str(value or "").strip()
                    if clean_value.startswith(("http://", "https://")) and clean_value not in candidates:
                        candidates.append(clean_value)
        except Exception:
            pass
        for media_url in reversed(evidence.media_urls):
            if media_url not in candidates:
                candidates.append(media_url)

        last_error = "页面未读取到可下载的视频地址"
        for media_url in candidates:
            try:
                output_path = self._save_media_url(media_url, task_id, settings)
                return str(output_path), f"已保存 OriginalDoubao 页面有水印视频：{output_path.name}"
            except Exception as exc:
                last_error = str(exc)

        download_names = re.compile(r"^(?:下载|下载视频|保存视频)$")
        controls = (
            page.get_by_role("button", name=download_names),
            page.get_by_text(download_names),
            page.locator('[aria-label*="下载"]:visible, [title*="下载"]:visible'),
        )
        for control_group in controls:
            for index in range(min(control_group.count(), 12)):
                control = control_group.nth(index)
                try:
                    label = " ".join(filter(None, (
                        control.inner_text(timeout=1_000),
                        control.get_attribute("aria-label"),
                        control.get_attribute("title"),
                    )))
                    if "无水印" in label or not control.is_visible():
                        continue
                    with page.expect_download(timeout=15_000) as download_info:
                        control.click(timeout=5_000)
                    download = download_info.value
                    output_dir = Path(str(settings["outputDir"])).resolve()
                    output_dir.mkdir(parents=True, exist_ok=True)
                    suffix = Path(download.suggested_filename).suffix or ".mp4"
                    output_path = output_dir / f"original_doubao_{task_id}{suffix}"
                    download.save_as(str(output_path))
                    return str(output_path), f"已通过 OriginalDoubao 页面下载有水印视频：{output_path.name}"
                except Exception as exc:
                    last_error = str(exc)
        return "", f"有水印视频保存失败：{last_error}"
