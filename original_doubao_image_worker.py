"""OriginalDoubao 图片生成 Worker。

复用 base 里已由视频流程验证过的底层动作（开新对话 / 上传参考图 / 填写提示词 /
点击发送 / 会话绑定 / 风控拦截），只把「视频生成」入口换成「图片生成」入口，
并抓取页面返回的 `<img>` 结果。豆包账号仍来自账号管理，无需在图片模型里单独配置。
"""
from __future__ import annotations

import base64
import re
import time
from pathlib import Path
from typing import Any

import httpx

from original_doubao_base import BaseAccountBrowserWorker, ManualOperationRequired, _secondary_monitor_chrome_args


# 保存图片时优先尝试的扩展名顺序；无法从 URL 或响应头判断时使用默认 .png。
_IMAGE_SUFFIX_HINTS: tuple[tuple[str, str], ...] = (
    ("image/jpeg", ".jpg"),
    ("image/jpg", ".jpg"),
    ("image/webp", ".webp"),
    ("image/gif", ".gif"),
    ("image/png", ".png"),
)


def _image_suffix_from_url(media_url: str) -> str:
    """Guess an image file suffix from the URL or its query parameters."""

    from urllib.parse import parse_qs, urlparse

    try:
        parsed = urlparse(str(media_url or ""))
    except ValueError:
        return ".png"
    path = parsed.path.lower()
    for suffix in (".png", ".jpg", ".jpeg", ".webp", ".gif"):
        if path.endswith(suffix):
            return ".jpg" if suffix == ".jpeg" else suffix
    query = parse_qs(parsed.query)
    for key in ("format", "type", "ext", "suffix", "image_type"):
        value = str((query.get(key) or [""])[0]).strip().lower().lstrip(".")
        if not value:
            continue
        if value in {"jpg", "jpeg"}:
            return ".jpg"
        if value in {"png", "webp", "gif"}:
            return f".{value}"
    return ".png"


def save_image_url(media_url: str, task_id: str, settings: dict[str, Any]) -> Path:
    """Download one generated image URL to the output directory."""

    output_dir = Path(str(settings["outputDir"])).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    suffix = _image_suffix_from_url(media_url)
    output_path = output_dir / f"original_doubao_{task_id}{suffix}"
    partial_path = output_path.with_name(f"{output_path.name}.part")
    headers = {
        "Referer": "https://www.doubao.com/",
        "Accept": "image/avif,image/webp,image/png,image/*,*/*;q=0.8",
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/151.0.0.0 Safari/537.36"
        ),
    }
    try:
        with httpx.stream("GET", media_url, headers=headers, follow_redirects=True, timeout=120) as response:
            response.raise_for_status()
            content_type = str(response.headers.get("content-type") or "").split(";")[0].strip().lower()
            resolved_path = output_path
            if suffix == ".png" and content_type and content_type != "image/png":
                for hint, hint_suffix in _IMAGE_SUFFIX_HINTS:
                    if hint == content_type:
                        resolved_path = output_dir / f"original_doubao_{task_id}{hint_suffix}"
                        partial_path = resolved_path.with_name(f"{resolved_path.name}.part")
                        break
            with partial_path.open("wb") as output:
                for chunk in response.iter_bytes(chunk_size=1024 * 256):
                    output.write(chunk)
        partial_path.replace(resolved_path)
        return resolved_path
    except Exception:
        try:
            partial_path.unlink(missing_ok=True)
        except OSError:
            pass
        raise


class OriginalDoubaoImageWorker(BaseAccountBrowserWorker):
    """豆包网页版图片生成 worker（账号级，与视频共用一个浏览器线程）。"""

    def submit_image_generation(self, task_id: str, payload: dict[str, Any]) -> None:
        self.commands.put({"type": "image_generate", "taskId": task_id, "payload": payload})

    def _dispatch_command(self, page: Any, context: Any, command: dict[str, Any]) -> None:
        if command["type"] == "image_generate":
            self._generate_image(page, command["taskId"], command["payload"])
        super()._dispatch_command(page, context, command)

    # ------------------------------------------------------------------ 主流程
    def _generate_image(self, page: Any, task_id: str, payload: dict[str, Any]) -> None:
        """OriginalDoubao 网页版图片生成。

        复用视频流程里已经验证过的浏览器自动化能力（打开新对话 / 上传参考图 /
        填写提示词 / 点击发送），只把「视频生成」入口换成「图片生成」入口，并抓取
        页面返回的 `<img>` 结果。豆包账号仍来自账号管理，无需在图片模型里单独配置。
        """
        from constants import ORIGINAL_DOUBAO_URL

        listeners: tuple[Any, Any] | None = None
        try:
            if not self.api._has_saved_original_doubao_session(self.account_id):
                self.api._update_task(
                    task_id,
                    status="failed",
                    statusText="该豆包账号未登录或登录已过期，请到设置中心打开对应账号完成登录后再试",
                    progress=0,
                )
                self._close_generation_window(page)
                return
            self.api._update_task(task_id, status="opening", statusText="正在打开豆包创作页面", progress=10)
            if not page.url.startswith("https://www.doubao.com"):
                page.goto(ORIGINAL_DOUBAO_URL, wait_until="domcontentloaded", timeout=60_000)
            page.wait_for_timeout(1500)
            self._dismiss_download_desktop_dialog(page)

            self.api._update_task(task_id, status="opening", statusText="正在创建并确认豆包新对话", progress=12)
            self._open_new_conversation(page)
            self._dismiss_download_desktop_dialog(page)

            self.api._update_task(task_id, status="configuring", statusText="正在进入图片生成", progress=18)
            self._open_image_creation(page)
            self._dismiss_download_desktop_dialog(page)

            attachments = [
                item
                for item in payload.get("attachments", [])
                if isinstance(item, dict) and str(item.get("path", "")).strip()
            ]
            if attachments:
                self.api._update_task(
                    task_id,
                    status="uploading",
                    statusText=f"正在向豆包上传 {len(attachments)} 张参考图",
                    progress=24,
                )
                self._upload_attachments(page, attachments)

            self.api._update_task(task_id, status="submitting", statusText="正在填写图片描述", progress=38)
            self._fill_prompt(page, str(payload["prompt"]))

            before_images = self._image_fingerprints(page)
            conversation_guard: dict[str, str] = {"key": ""}
            evidence, listeners = self._listen_for_image_evidence(page, conversation_guard)
            self._click_generate(page)
            conversation = self._capture_generation_conversation(page, task_id)
            conversation_guard["key"] = str(conversation.get("key") or "")
            self.api._update_task(
                task_id,
                status="generating",
                statusText="已提交到豆包，正在等待生成结果",
                progress=55,
                demo=False,
                conversationId=str(conversation.get("id") or ""),
                conversationUrl=str(conversation.get("url") or ""),
                generationSubmittedAt=int(time.time() * 1000),
            )
            self._monitor_image_result(
                page,
                task_id,
                before_images,
                evidence,
                listeners,
                payload,
                conversation,
            )
            listeners = None
        except Exception as exc:
            if listeners is not None:
                self._stop_image_evidence_listener(page, listeners)
            blocked_reason, requires_manual_verification = self._generation_block_reason(page)
            if blocked_reason:
                if "登录已过期" in blocked_reason or "会话失效" in blocked_reason:
                    self.api.mark_account_login_expired(self.account_id)
                self.api._update_task(
                    task_id,
                    status="failed",
                    statusText=blocked_reason,
                    progress=0,
                    resultPath="",
                    resultUrl="",
                    requiresManualVerification=requires_manual_verification,
                )
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
                statusText=f"豆包图片生成页面操作失败：{exc}{debug_note}",
                progress=0,
                demo=False,
            )

    def _open_image_creation(self, page: Any) -> None:
        """点击豆包「图片生成」入口（对应视频流程里的「视频生成」入口）。"""

        for attempt in range(3):
            exact = page.get_by_text(re.compile(r"^\s*图片生成\s*$"))
            for index in range(min(exact.count(), 12)):
                item = exact.nth(index)
                if item.is_visible():
                    try:
                        item.click(timeout=4000)
                        page.wait_for_timeout(1500)
                        return
                    except Exception:
                        continue

            names = re.compile(r"图片生成|生成图片|AI\s*图片|AI绘画|AI绘图|文生图|图像生成")
            candidates = page.get_by_text(names)
            for index in range(min(candidates.count(), 12)):
                item = candidates.nth(index)
                if item.is_visible():
                    try:
                        item.click(timeout=3000)
                        page.wait_for_timeout(1500)
                        return
                    except Exception:
                        continue

            if attempt < 2:
                page.wait_for_timeout(1000)
        raise RuntimeError("没有找到“图片生成”入口")

    def _image_fingerprints(self, page: Any) -> set[str]:
        """抓取页面中可见生成图片的指纹，用于判断是否返回了新图。"""

        fingerprints: set[str] = set()
        try:
            images = page.locator("img")
            for index in range(images.count()):
                image = images.nth(index)
                try:
                    box = image.bounding_box()
                except Exception:
                    box = None
                if not box or box.get("width", 0) < 96 or box.get("height", 0) < 96:
                    continue
                for attribute in ("src", "data-src", "data-original"):
                    value = image.get_attribute(attribute)
                    if value:
                        fingerprints.add(value)
                current_src = image.evaluate("img => img.currentSrc || ''")
                if current_src:
                    fingerprints.add(str(current_src))
        except Exception:
            pass
        return fingerprints

    def _listen_for_image_evidence(
        self,
        page: Any,
        conversation_guard: dict[str, str] | None = None,
    ) -> tuple[list[str], tuple[Any, Any]]:
        """监听页面网络请求，收集豆包返回的图片 URL（含 response body 里的 URL）。"""

        image_urls: list[str] = []

        def belongs_to_bound_conversation() -> bool:
            expected_key = str((conversation_guard or {}).get("key") or "")
            if not expected_key:
                return True
            return self._conversation_key_from_url(str(page.url or "")) == expected_key

        def collect(url: str) -> None:
            if url and url not in image_urls:
                image_urls.append(url)

        def on_request(request: Any) -> None:
            if not belongs_to_bound_conversation():
                return
            try:
                if request.resource_type == "image" and self._is_generated_image_url(request.url):
                    collect(request.url)
            except Exception:
                pass

        def on_response(response: Any) -> None:
            if not belongs_to_bound_conversation():
                return
            url = response.url
            try:
                resource_type = response.request.resource_type
            except Exception:
                resource_type = ""
            if resource_type == "image" and self._is_generated_image_url(url):
                collect(url)
            try:
                headers = response.headers
                content_type = str(headers.get("content-type") or "").lower()
                content_length = int(headers.get("content-length", "0") or 0)
            except Exception:
                return
            if not any(host in url for host in ("doubao.com", "byteimg.com", "bytedance")):
                return
            if content_length > 4_000_000:
                return
            if not ("json" in content_type or "text" in content_type or resource_type in {"xhr", "fetch"}):
                return
            try:
                body = response.text()[:4_000_000]
            except Exception:
                return
            for match in re.findall(r"https?://[^\s\"'\\)]+", body):
                if self._is_generated_image_url(match):
                    collect(match)

        page.on("request", on_request)
        page.on("response", on_response)
        return image_urls, (on_request, on_response)

    def _stop_image_evidence_listener(self, page: Any, listeners: tuple[Any, Any]) -> None:
        request_listener, response_listener = listeners
        try:
            page.remove_listener("request", request_listener)
            page.remove_listener("response", response_listener)
        except Exception:
            pass

    @staticmethod
    def _is_generated_image_url(url: str) -> bool:
        """判断 URL 是否像豆包生成的图片，排除头像 / 图标 / 二维码等静态资源。"""

        value = str(url or "")
        if not value.startswith(("http://", "https://")):
            return False
        lowered = value.lower()
        if lowered.startswith("data:") or lowered.startswith("blob:"):
            return False
        if any(host in lowered for host in ("avatar", "icon", "logo", "qrcode", "sprite")):
            return False
        if "byteimg.com" not in lowered and not re.search(
            r"\.(?:png|jpe?g|webp|gif)(?:\?|$)", lowered
        ):
            return False
        return not any(
            keyword in lowered
            for keyword in ("emoji", "sticker", "static", "favicon", "default")
        )

    def _monitor_image_result(
        self,
        page: Any,
        task_id: str,
        before_images: set[str],
        evidence: list[str],
        listeners: tuple[Any, Any],
        payload: dict[str, Any],
        conversation: dict[str, str],
    ) -> None:
        """等待豆包返回图片并保存结果。"""

        manual_confirmation_waiting = False
        authorized_material_confirmation_rounds = 0
        for tick in range(300):
            page.wait_for_timeout(2000)
            if not page.context.pages:
                raise RuntimeError("豆包浏览器已关闭")
            self._dismiss_download_desktop_dialog(page)
            expected_conversation_key = str(conversation.get("key") or "")
            current_conversation_key = self._conversation_key_from_url(str(page.url or ""))
            if expected_conversation_key and current_conversation_key != expected_conversation_key:
                self.api._update_task(
                    task_id,
                    status="returning_to_conversation",
                    statusText="检测到豆包已切换会话，正在返回本任务绑定会话",
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
                            statusText="安全确认校验已通过，正在继续生成图片",
                            progress=55,
                            requiresManualVerification=False,
                        )
                        continue
                if not manual_confirmation_waiting:
                    manual_confirmation_waiting = True
                    self.api._update_task(
                        task_id,
                        status="waiting_confirmation",
                        statusText="安全确认自动校验未通过，请在豆包浏览器中人工确认",
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
                self._stop_image_evidence_listener(page, listeners)
                self.api._update_task(
                    task_id,
                    status="failed",
                    statusText=blocked_reason,
                    progress=0,
                    resultPath="",
                    resultUrl="",
                    requiresManualVerification=requires_manual_verification,
                )
                return
            if tick % 5 == 0:
                waiting_message = self._image_waiting_message(page)
                if waiting_message:
                    self.api._update_task(task_id, status="generating", statusText=waiting_message)
            current_images = self._image_fingerprints(page)
            has_new_image = bool(current_images - before_images)
            has_network_image = any(url not in before_images for url in evidence)
            if has_new_image or has_network_image:
                self.api._update_task(
                    task_id,
                    status="sharing",
                    statusText="图片已返回，正在读取图片地址",
                    progress=94,
                )
                media_url = self._pick_generated_image_url(page, evidence, before_images)
                if not media_url:
                    page.wait_for_timeout(1500)
                    continue
                self._stop_image_evidence_listener(page, listeners)
                self.api._update_task(
                    task_id,
                    status="downloading",
                    statusText="图片已生成，正在保存到本地",
                    progress=96,
                )
                result_path = self._save_generated_image(page, media_url, task_id)
                display_path = self.api._webview_preview_path(str(result_path)) if result_path else ""
                self.api._update_task(
                    task_id,
                    status="succeeded",
                    statusText="图片已生成并保存到本地",
                    progress=100,
                    resultPath=str(display_path) if display_path else "",
                    resultUrl=self.api._media_url_for(str(display_path)) if display_path else "",
                    resultFileId="",
                    resultWatermarked=False,
                    requiresManualVerification=False,
                )
                return
            progress = min(92, 55 + tick // 4)
            self.api._update_task(task_id, progress=progress)
        self._stop_image_evidence_listener(page, listeners)
        raise RuntimeError("等待图片生成结果超时")

    def _image_waiting_message(self, page: Any) -> str:
        try:
            text = page.locator("body").inner_text(timeout=2000)
        except Exception:
            return ""
        normalized = re.sub(r"\s+", "", text)
        if re.search(r"图片生成中|正在生成图片|正在绘制|生成中", normalized):
            return "豆包正在生成图片，请稍候"
        return ""

    def _pick_generated_image_url(
        self,
        page: Any,
        evidence: list[str],
        before_images: set[str],
    ) -> str:
        """从网络监听结果和页面 `<img>` 中挑选最可能的生成图片地址。"""

        for url in reversed(evidence):
            if url not in before_images:
                return url
        current = self._image_fingerprints(page)
        for url in sorted(current - before_images):
            if url.startswith(("http://", "https://")):
                return url
        return ""

    def _save_generated_image(self, page: Any, media_url: str, task_id: str) -> Path:
        """优先在登录态页面内抓取图片字节，失败时回退到直连下载。"""

        try:
            data_url = page.evaluate(
                """
                async (url) => {
                  const response = await fetch(url, { credentials: 'include' });
                  if (!response.ok) throw new Error('HTTP ' + response.status);
                  const blob = await response.blob();
                  return await new Promise((resolve, reject) => {
                    const reader = new FileReader();
                    reader.onload = () => resolve(reader.result);
                    reader.onerror = () => reject(new Error('读取图片失败'));
                    reader.readAsDataURL(blob);
                  });
                }
                """,
                media_url,
            )
            raw = str(data_url or "")
            marker = ";base64,"
            if marker in raw:
                content = base64.b64decode(raw.split(marker, 1)[1])
                output_dir = Path(str(self.api.get_settings()["outputDir"])).resolve()
                output_dir.mkdir(parents=True, exist_ok=True)
                output_path = output_dir / f"original_doubao_{task_id}{_image_suffix_from_url(media_url)}"
                output_path.write_bytes(content)
                return output_path
        except Exception:
            pass
        return save_image_url(media_url, task_id, self.api.get_settings())


__all__ = [
    "OriginalDoubaoImageWorker",
    "save_image_url",
    "_image_suffix_from_url",
    "_IMAGE_SUFFIX_HINTS",
    "_secondary_monitor_chrome_args",
]
