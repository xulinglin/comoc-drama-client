# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包配置：生成免 Java、免登录、本地化的 Windows 客户端。

产物为目录模式（dist/CDTV/），exe 与依赖同目录。

需要与 exe 同级放置的外部资源（体积大、或需要可写，不打进 exe）：
- runtime/chrome-win64/   内置 Chromium（OriginalDoubao 自动化使用，约 420MB）
可选：
- runtime/jre/            仅在需要回退到 Java 存储服务时才需要，本地模式下不必提供

前端产物（frontend/dist）与图标资源会打包进 exe。
"""
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

ROOT = Path(SPECPATH).resolve()

datas = [
    (str(ROOT / "frontend" / "dist"), "frontend/dist"),
    (str(ROOT / "assets"), "assets"),
]

# playwright 需要在运行时定位其自带的 Node 驱动与 package 文件。
datas += collect_data_files("playwright")

hiddenimports = [
    "webview",
    "webview.platforms.edgechromium",
    "webview.platforms.winforms",
    "clr_loader",
    "pythonnet",
    "httpx",
    "httpcore",
    "local_storage",
    "model_seeds",
    "original_doubao_worker",
    "original_doubao_nomark",
    "media_server",
    "constants",
]
hiddenimports += collect_submodules("playwright")

block_cipher = None

a = Analysis(
    [str(ROOT / "launcher.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # 明确排除 Java 相关与体积大且用不到的库，避免误打包。
    excludes=[
        "tkinter",
        "matplotlib",
        "scipy",
        "pandas",
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

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
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(ROOT / "assets" / "app-icon.ico"),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="CDTV",
)
