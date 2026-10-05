"""macOS 系统适配；Cocoa 依赖仅在对应功能调用时导入。"""
from __future__ import annotations

from pathlib import Path

from constants import BUNDLE_DIR, BUNDLED_CHROME, ROOT


def resolve_chrome() -> Path:
    """查找 Mac 版内置浏览器或本机 Chrome，不下载浏览器。"""
    candidates = [
        BUNDLED_CHROME,
        BUNDLE_DIR / BUNDLED_CHROME.relative_to(ROOT),
    ]
    for root in (Path("/Applications"), Path.home() / "Applications"):
        candidates.extend([
            root / "Google Chrome.app" / "Contents" / "MacOS" / "Google Chrome",
            root / "Google Chrome for Testing.app" / "Contents" / "MacOS" / "Google Chrome for Testing",
            root / "Chromium.app" / "Contents" / "MacOS" / "Chromium",
        ])
    for executable in candidates:
        if executable.is_file():
            return executable.resolve()
    raise RuntimeError("未找到 Mac 版 Chrome，请先将 Google Chrome 安装到“应用程序”目录")


def copy_files(file_paths: list[str]) -> dict[str, int]:
    """以文件 URL 写入剪贴板，支持 Finder 和浏览器粘贴。"""
    paths = [Path(str(value)).resolve() for value in file_paths]
    if not paths:
        raise ValueError("没有可复制的参考图")
    missing = [path for path in paths if not path.is_file()]
    if missing:
        raise ValueError(f"参考图文件不存在：{missing[0].name}")

    from AppKit import NSPasteboard
    from Foundation import NSAutoreleasePool, NSURL

    pool = NSAutoreleasePool.alloc().init()
    try:
        urls = [NSURL.fileURLWithPath_(str(path)) for path in paths]
        clipboard = NSPasteboard.generalPasteboard()
        clipboard.clearContents()
        if not clipboard.writeObjects_(urls):
            raise ValueError("无法复制参考图到剪贴板")
        return {"count": len(paths)}
    finally:
        pool.drain()
