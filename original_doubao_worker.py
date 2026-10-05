"""OriginalDoubao 视频生成 Worker。拆分自 launcher.py，逻辑保持一致。

每个 OriginalDoubao 账号对应一个 AccountBrowserWorker 线程，持有独立的 Chromium 持久化
profile。主线程通过命令队列向 worker 投递生成 / 链接转换任务，避免在多线程
下直接操作 Playwright 同步 API。

实现已拆分：
- original_doubao_base.py         浏览器线程 / 登录态 / 通用网页动作基类
- original_doubao_video_worker.py 视频生成与链接转换
- original_doubao_image_worker.py 图片生成

本模块保留原有导出名（AccountBrowserWorker 指向视频 worker，save_media_url 指向
视频媒体下载），作为向后兼容门面，现有 import 无需改动。
"""
from __future__ import annotations

from original_doubao_base import (
    BaseAccountBrowserWorker,
    ManualOperationRequired,
    _secondary_monitor_chrome_args,
)
from original_doubao_image_worker import (
    OriginalDoubaoImageWorker,
    _IMAGE_SUFFIX_HINTS,
    _image_suffix_from_url,
    save_image_url,
)
from original_doubao_video_worker import (
    ORIGINAL_DOUBAO_VIDEO_AUTO_SUBMIT_ENABLED,
    OriginalDoubaoVideoWorker,
    save_media_url,
)

# 向后兼容：历史代码按「视频」语义使用 AccountBrowserWorker。
AccountBrowserWorker = OriginalDoubaoVideoWorker

__all__ = [
    "AccountBrowserWorker",
    "BaseAccountBrowserWorker",
    "ManualOperationRequired",
    "OriginalDoubaoImageWorker",
    "OriginalDoubaoVideoWorker",
    "ORIGINAL_DOUBAO_VIDEO_AUTO_SUBMIT_ENABLED",
    "save_media_url",
    "save_image_url",
    "_IMAGE_SUFFIX_HINTS",
    "_image_suffix_from_url",
    "_secondary_monitor_chrome_args",
]
