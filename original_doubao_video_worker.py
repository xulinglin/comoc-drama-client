"""OriginalDoubao 视频生成 Worker。

只保留视频 / 链接转换专属逻辑；浏览器生命周期、登录态探测与通用网页动作
全部继承自 original_doubao_base.BaseAccountBrowserWorker。
"""
from __future__ import annotations

import asyncio
import re
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import httpx

from generation_accounts import is_platform_url
from original_doubao_base import BaseAccountBrowserWorker, ManualOperationRequired, _secondary_monitor_chrome_args
from original_doubao_nomark import (
    OriginalDoubaoVideoEvidence,
    dola_video_parse,
    original_doubao_fplay_parse,
    original_doubao_video_parse,
    is_douyin_media_url,
    is_dola_media_url,
    is_supported_conversion_url,
    conversion_account_type,
    platform_media_proxy,
)


# OriginalDoubao 最终生成/发送开关；关闭时保留填写好的内容，便于检查流程。
ORIGINAL_DOUBAO_VIDEO_AUTO_SUBMIT_ENABLED = True
ORIGINAL_DOUBAO_MATERIAL_PLEDGE = "本次视频生成使用的参考图片均为 AI 生成的原创虚构角色，不对应现实人物，仅用于虚构剧情创作。"


def save_media_url(media_url: str, task_id: str, settings: dict[str, Any], *, referer: str = "https://www.doubao.com/") -> Path:
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
        headers = {"Referer": referer, "User-Agent": "Mozilla/5.0"}
    try:
        with httpx.stream("GET", media_url, headers=headers, follow_redirects=True, timeout=120,
                          proxy=platform_media_proxy(referer)) as response:
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


class OriginalDoubaoVideoWorker(BaseAccountBrowserWorker):
    """豆包网页版视频生成 worker（账号级，与图片共用一个浏览器线程）。"""

    def submit_generation(self, task_id: str, payload: dict[str, Any]) -> None:
        self.commands.put({"type": "generate", "taskId": task_id, "payload": payload})

    def submit_link_conversion(self, link: str, reply: "Any") -> None:
        self.commands.put({"type": "convert_link", "link": link, "reply": reply})

    def submit_check_login(self, reply: "Any") -> None:
        self.commands.put({"type": "check_login", "reply": reply})

    def _dispatch_command(self, page: Any, context: Any, command: dict[str, Any]) -> None:
        if command["type"] == "generate":
            self._generate(page, command["taskId"], command["payload"])
        if command["type"] == "convert_link":
            try:
                command["reply"].put({"success": True, "data": self._convert_link(page, command["link"])})
            except Exception as exc:
                command["reply"].put({"success": False, "error": str(exc)})
        super()._dispatch_command(page, context, command)

    # ------------------------------------------------------------------ 主流程
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
            if not self._is_platform_page(page):
                page.goto(self.home_url, wait_until="domcontentloaded", timeout=60_000)
            page.wait_for_timeout(1500)
            if self.account_type == "dola" and not self._check_login(page.context, page)["loggedIn"]:
                raise RuntimeError("Dola 登录已过期，请重新登录后重试")
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
            prompt = str(payload["prompt"]).strip()
            if not prompt.endswith(ORIGINAL_DOUBAO_MATERIAL_PLEDGE):
                prompt = f"{prompt}\n\n{ORIGINAL_DOUBAO_MATERIAL_PLEDGE}"
            self._fill_prompt(page, prompt)

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

    # ------------------------------------------------------------ 视频创作入口
    def _open_video_creation(self, page: Any) -> None:
        for attempt in range(3):
            exact = page.get_by_text(re.compile(r"^(?:视频生成|Create Videos|Generate Videos|Video Generation)$", re.I))
            for index in range(min(exact.count(), 12)):
                item = exact.nth(index)
                if item.is_visible():
                    try:
                        item.click(timeout=4000)
                        page.wait_for_timeout(1000)
                        return
                    except Exception:
                        continue

            names = re.compile(r"视频生成|生成视频|AI\s*视频|AI\s*创作|图片生成视频|Create Videos|Generate Videos|Video Generation|AI\s*Creation", re.I)
            candidates = page.get_by_text(names)
            for index in range(min(candidates.count(), 12)):
                item = candidates.nth(index)
                if item.is_visible():
                    try:
                        item.click(timeout=3000)
                        page.wait_for_timeout(1000)
                        if re.fullmatch(r"AI\s*(?:创作|Creation)", item.inner_text().strip(), re.I):
                            break
                        return
                    except Exception:
                        continue

            if attempt < 2:
                page.wait_for_timeout(1000)
        raise RuntimeError("没有找到“视频生成”入口")

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
            page.get_by_role("button", name=re.compile(r"Seedance|选择模型|模型|Select model|Choose model|Model", re.I)),
            page.get_by_text(re.compile(r"^(?:模型|Model)\s*[:：]?\s*\d", re.I)),
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
        trigger_pattern = re.compile(r"(自动|Auto|3:4|4:3|9:16|16:9|1:1|21:9)\s*[·・]\s*\d+\s*s", re.I)
        triggers = page.get_by_text(trigger_pattern)
        if self.account_type == "dola" and not any(triggers.nth(i).is_visible() for i in range(triggers.count())):
            self._configure_dola_video(page, ratio, duration)
            return
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
        ratio_options = page.get_by_text(re.compile(r"^(?:自动|Auto)$", re.I)) if ratio_text == "自动" else page.get_by_text(ratio_text, exact=True)
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

    @staticmethod
    def _click_video_setting(page: Any, pattern: re.Pattern) -> bool:
        controls = page.get_by_text(pattern)
        for index in range(controls.count() - 1, -1, -1):
            control = controls.nth(index)
            try:
                if control.is_visible():
                    control.click(timeout=4000)
                    page.wait_for_timeout(300)
                    return True
            except Exception:
                continue
        return False

    def _configure_dola_video(self, page: Any, ratio: str, duration: int) -> None:
        """Dola 中英文页面也有独立的「比例」和「10s」下拉控件。"""
        ratio_names = r"自动|Auto|21:9|16:9|4:3|1:1|3:4|9:16"
        if not self._click_video_setting(page, re.compile(rf"^(?:比例|Ratio|Aspect ratio|{ratio_names})$", re.I)):
            raise RuntimeError("没有找到 Dola 画面比例设置入口")
        option_pattern = re.compile(r"^(?:自动|Auto)$", re.I) if ratio in ("auto", "自动") else re.compile(rf"^{re.escape(ratio)}$")
        if not self._click_video_setting(page, option_pattern):
            raise RuntimeError(f"没有找到画面比例选项：{ratio}")
        page.locator("body").press("Escape")
        if not self._click_video_setting(page, re.compile(r"^(?:\d+\s*(?:s|秒)|时长|Duration)$", re.I)):
            raise RuntimeError("没有找到 Dola 视频时长设置入口")
        sliders = page.locator('[role="slider"]:visible, input[type="range"]:visible')
        if sliders.count():
            slider = sliders.last
            minimum = float(slider.get_attribute("min") or slider.get_attribute("aria-valuemin") or 4)
            maximum = float(slider.get_attribute("max") or slider.get_attribute("aria-valuemax") or 15)
            step = float(slider.get_attribute("step") or 1)
            steps = (duration - minimum) / step
            if not minimum <= duration <= maximum or not steps.is_integer():
                raise RuntimeError(f"Dola 当前模型不支持 {duration} 秒时长")
            slider.press("Home", timeout=4000)
            for _ in range(int(steps)):
                slider.press("ArrowRight", timeout=2000)
        elif not self._click_video_setting(page, re.compile(rf"^{duration}\s*(?:s|秒)$", re.I)):
            raise RuntimeError(f"没有找到 Dola 视频时长选项：{duration}s")
        page.locator("body").press("Escape")

    # ------------------------------------------------------------ 结果监听 / 抓取
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
            if not any(host in request.url for host in (self.platform_domain, "douyin.com", "365yg.com", "byteoversea.com", "ibytedtos.com")):
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
            if not any(host in url for host in (self.platform_domain, "douyin.com", "365yg.com", "byteoversea.com", "ibytedtos.com")):
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
        quota_exhausted_after_generation = False
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
            quota_exhausted_after_generation = (
                quota_exhausted_after_generation or self._dola_generation_reports_zero_quota(page)
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
                    "I confirm, start generating the video." if self.account_type == "dola" else "我确认开始生成视频",
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
                    quotaExhaustedAfterGeneration=quota_exhausted_after_generation,
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
                if not evidence.video_ids and self.account_type != "dola":
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

    def _dola_generation_reports_zero_quota(self, page: Any) -> bool:
        """Latch the submitted video's zero balance, without stopping its generation."""
        if self.account_type != "dola":
            return False
        try:
            messages = page.locator(
                '[data-message-author-role="assistant"]:visible, '
                '[data-testid*="assistant-message"]:visible, [class*="assistant-message"]:visible'
            )
            if messages.count():
                text = messages.last.inner_text(timeout=1_000)
            else:
                # Do not mistake a quoted acknowledgement in the user's prompt
                # for a Dola response. The body fallback supports unlabelled UI.
                if page.locator(
                    '[data-message-author-role="user"]:visible, '
                    '[data-testid*="user-message"]:visible, [class*="user-message"]:visible'
                ).count():
                    return False
                text = page.locator("body").inner_text(timeout=1_000)
        except Exception:
            return False
        clean_text = re.sub(r"[*_`]+", "", text)
        normalized = re.sub(r"\s+", "", clean_text)
        zero_remaining = bool(
            re.search(r"今日剩余(?:0|零)个视频生成额度", normalized)
            or re.search(
                r"\b0\s+video\s+(?:generation\s+)?credits?\s+(?:remaining|left)\s+(?:for\s+)?today\b"
                r"|\b(?:remaining|left)\s+video\s+(?:generation\s+)?credits?\s+(?:for\s+)?today\s*[:：]?\s*0\b"
                r"|\btoday['’]s\s+remaining\s+video\s+(?:generation\s+)?credits?\s*[:：]?\s*0\b",
                clean_text, re.I,
            )
        )
        # A refusal also mentions exhausted credits. Require confirmation that
        # this video was accepted and is being generated before deferring it.
        generating = bool(
            self._generation_waiting_message_from_text(clean_text)
            or re.search(
                r"video\s+(?:is\s+being\s+generated|generation\s+(?:has\s+been\s+|is\s+)?(?:submitted|started))"
                r"|(?:I\s+will|I'll|we\s+will|we'll).{0,80}(?:send|notify|share).{0,80}(?:video|ready)"
                r"|(?:estimated|expected)\s+wait(?:ing)?\s*(?:time)?\s*[:：]?\s*\d+\s*(?:minutes?|mins?)",
                clean_text, re.I | re.S,
            )
        )
        return zero_remaining and generating

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

    # ------------------------------------------------------------ 视频证据 / 标识
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
                proxy=platform_media_proxy(self.home_url),
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
        if not is_platform_url(str(page.url), self.platform_domain):
            raise ValueError("视频解析页面与账号平台不一致，请重新打开对应账号")
        if self.account_type == "dola":
            cookies = self._browser_cookie_dict(page)
            with ThreadPoolExecutor(max_workers=1, thread_name_prefix="dola-nomark") as executor:
                return executor.submit(lambda: asyncio.run(
                    dola_video_parse(video_ids, cookies, proxy=platform_media_proxy(self.home_url))
                )).result(timeout=180)
        models = page.evaluate(
            """
            async (videoIds) => {
              const models = [];
              let error = '';
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
                  if (result?.code && result.code !== 0) {
                    error = String(result.msg || result.message || '视频模型解析失败');
                    if (result.code === 710012001) error = '账号登录已过期，请重新登录';
                    if (result.code === 710022003) error = 'Dola 当前网络受地区限制，请检查账号浏览器使用的网络';
                  }
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
              return {models, error};
            }
            """,
            video_ids,
        )
        if isinstance(models, dict):
            if not models.get("models") and models.get("error"):
                raise ValueError(str(models["error"]))
            models = models.get("models", [])
        for model in models or []:
            try:
                with ThreadPoolExecutor(max_workers=1, thread_name_prefix="original-doubao-fplay") as executor:
                    videos = executor.submit(
                        lambda item=model: asyncio.run(
                            original_doubao_fplay_parse(str(item["fallback_api"]), str(item["video_id"]),
                                                       referer=self.home_url, proxy=platform_media_proxy(self.home_url))
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
                for cookie in page.context.cookies(self.home_url)
            }
        except Exception:
            return {}

    def _save_media_url(self, media_url: str, task_id: str, settings: dict[str, Any]) -> Path:
        return save_media_url(media_url, task_id, settings, referer=self.home_url)

    # ------------------------------------------------------------ 结果下载
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

        parser_error = "接口未返回无水印视频流" if evidence.video_ids else "没有监听到本次视频的 video_id 或分享链接"
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
                return str(output_path), f"已通过 {self.platform_label} 登录态保存无水印流：{output_path.name}"
        except Exception as exc:
            parser_error = f"登录态解析失败：{exc}"

        if self.account_type == "dola":
            # 国际版在自己的登录页面解析，不进入豆包国内公开分享接口。
            return "", f"Dola 无水印解析失败：{parser_error}"

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

        # Fallback for pages exposing an explicit no-watermark download control.
        names = re.compile(r"无水印下载|下载无水印|下载.*无水印|Download.*(?:without watermark|watermark.free)", re.I)
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
                return str(output_path), f"无水印视频已通过 {self.platform_label} 官方入口保存：{output_path.name}"
            except Exception:
                continue
        return "", f"{self.platform_label} 视频已生成，但页面未提供明确的官方无水印下载入口"

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

        download_names = re.compile(r"^(?:下载|下载视频|保存视频|Download|Download video|Save video)$", re.I)
        controls = (
            page.get_by_role("button", name=download_names),
            page.get_by_text(download_names),
            page.locator('[aria-label*="下载"]:visible, [title*="下载"]:visible, [aria-label*="Download" i]:visible, [title*="Download" i]:visible'),
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
                    if "无水印" in label or re.search(r"without watermark|watermark.free", label, re.I) or not control.is_visible():
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

    # ------------------------------------------------------------ 链接转换
    def _convert_link(self, page: Any, link: str) -> dict[str, str]:
        clean_link = str(link).strip()
        if not is_supported_conversion_url(clean_link):
            raise ValueError("请输入 Doubao / Dola 官方视频分享链接或视频直链")

        if conversion_account_type(clean_link) != self.account_type:
            raise ValueError("链接平台与所选账号不一致，请切换对应平台的账号")
        if self.account_type == "dola":
            evidence = OriginalDoubaoVideoEvidence()
            evidence.add(clean_link)
            direct_link = is_dola_media_url(clean_link)
            if direct_link:
                video_id = self._video_id_from_media_url(clean_link)
                if not video_id:
                    raise ValueError("Dola 视频直链中没有读取到 video_id；链接可能已过期，请重新复制")
                evidence.add(f'{{"video_id":"{video_id}"}}')
                if not is_platform_url(str(page.url), self.platform_domain):
                    page.goto(self.home_url, wait_until="domcontentloaded", timeout=60_000)
                    page.wait_for_timeout(1500)
            else:
                page.goto(clean_link, wait_until="domcontentloaded", timeout=60_000)
                page.wait_for_timeout(1500)
                self._collect_page_video_evidence(page, evidence)
                if not evidence.video_ids:
                    for media_url in reversed(evidence.media_urls):
                        video_id = self._video_id_from_media_url(media_url)
                        if video_id:
                            evidence.add(f'{{"video_id":"{video_id}"}}')
                            break
            if "region-restricted" in str(page.url):
                raise ValueError("Dola 当前网络受地区限制，无法读取视频下载入口")
            if self._detect_login_state(page) == "login":
                raise ValueError("Dola 页面需要登录，请打开对应账号完成登录后重试")
            conversion_id = f"dola_link_{uuid.uuid4().hex[:10]}"
            path, message = self._download_nomark_video(page, evidence, conversion_id, force=True)
            if not path and not direct_link:
                path, official_message = self._download_official_unwatermarked(page, conversion_id, force=True)
                if path:
                    message = official_message
            if not path:
                raise ValueError(f"{message}；未取得无水印原片，请确认 Dola 账号已登录且当前网络可用")
            output_path = Path(path)
            return {
                "path": str(output_path), "name": output_path.name,
                "previewUrl": self.api._media_url_for(str(output_path)),
                "watermarkStatus": "official_unwatermarked",
                "message": message,
            }

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


__all__ = [
    "OriginalDoubaoVideoWorker",
    "save_media_url",
    "ORIGINAL_DOUBAO_VIDEO_AUTO_SUBMIT_ENABLED",
    "_secondary_monitor_chrome_args",
    "ManualOperationRequired",
]
