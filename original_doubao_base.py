"""OriginalDoubao 浏览器自动化基类。

video / image 两条流程共用的底层能力集中在这里：浏览器线程生命周期、命令循环、
登录态探测，以及与豆包网页交互的通用动作（开新对话、上传素材、填写提示词、
点击生成、会话绑定、风控/弹窗处理、结果保存等）。

子类（OriginalDoubaoVideoWorker / OriginalDoubaoImageWorker）只负责各自的
「创作入口」和「结果抓取」差异。
"""
from __future__ import annotations

import json
import queue
import re
import threading
import time
from typing import TYPE_CHECKING, Any
from urllib.parse import parse_qs, urlparse

from playwright.sync_api import sync_playwright

from constants import ACCOUNTS_DIR, BUNDLED_CHROME, DATA_DIR, ORIGINAL_DOUBAO_URL

if TYPE_CHECKING:
    from launcher import DesktopApi


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


class BaseAccountBrowserWorker:
    """每个 OriginalDoubao 账号一个 worker 线程，持有独立的 Chromium 持久化 profile。

    主线程通过命令队列投递任务，避免在多线程下直接操作 Playwright 同步 API。
    子类通过 _run 的命令分发调用各自的业务流程（video / image）。
    """

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

    def stop(self) -> None:
        self.commands.put({"type": "stop"})

    # ------------------------------------------------------------------ 命令分发
    def _dispatch_command(self, page: Any, context: Any, command: dict[str, Any]) -> None:
        """默认只处理登录检查等通用命令；业务命令由子类扩展。"""

        if command["type"] == "check_login":
            try:
                target = context.pages[0] if context.pages else page
                command["reply"].put({"success": True, "data": self._check_login(context, target)})
            except Exception as exc:
                command["reply"].put({"success": False, "error": str(exc)})

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
                self._dispatch_command(page, context, command)
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

    # ---------------------------------------------------------------- 登录态探测
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

    # ------------------------------------------------------------ 通用页面动作
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
        raise RuntimeError("没有找到图片上传控件；请确认当前已进入 OriginalDoubao 的生成页面")

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

    # ------------------------------------------------------------- 弹窗 / 风控
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

    # ------------------------------------------------------------ 视频 / 图片专属能力
    # 链接转换、视频/图片的下载与落盘等都由各自的子类实现，基类只保留账号浏览器通用能力。
