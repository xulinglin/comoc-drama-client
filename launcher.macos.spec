# -*- mode: python ; coding: utf-8 -*-
"""仅在 Mac 上构建 CDTV.app；不改变 launcher.spec 的 Windows 打包流程。"""
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

if sys.platform != "darwin":
    raise SystemExit("launcher.macos.spec 必须在 macOS 上构建；Windows 请使用 launcher.spec")

ROOT = Path(SPECPATH).resolve()
datas = [
    (str(ROOT / "frontend" / "dist"), "frontend/dist"),
    (str(ROOT / "assets"), "assets"),
]
datas += collect_data_files("playwright")
datas += collect_data_files("webview")

hiddenimports = [
    "webview.platforms.cocoa",
    "macos_support",
    "AppKit",
    "Foundation",
    "Quartz",
    "WebKit",
    "Security",
    "objc",
    "PyObjCTools.AppHelper",
]
hiddenimports += collect_submodules("playwright")

a = Analysis(
    [str(ROOT / "launcher.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "tkinter", "matplotlib", "scipy", "pandas",
        "clr", "clr_loader", "pythonnet",
        "webview.platforms.winforms", "webview.platforms.edgechromium",
        "webview.platforms.gtk", "webview.platforms.qt", "webview.platforms.cef",
    ],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="CDTV",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe, a.binaries, a.datas,
    strip=False,
    upx=False,
    name="CDTV",
)
app = BUNDLE(
    coll,
    name="CDTV.app",
    icon=str(ROOT / "assets" / "app-icon.png"),
    bundle_identifier="com.cdtv.comic-drama-client",
    info_plist={
        "CFBundleShortVersionString": "0.1.0",
        "NSHighResolutionCapable": True,
        "NSAppTransportSecurity": {"NSAllowsArbitraryLoads": True},
    },
)
