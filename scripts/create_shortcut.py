"""
创建桌面快捷方式（.lnk）指向 启动应用.bat，并使用 assets/app-icon.ico 作图标
双击运行本脚本即可重新创建快捷方式
"""
import os
import sys
from pathlib import Path

# Windows CMD 默认 GBK 编码，强制 stdout 用 UTF-8 输出避免 emoji 报错
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except AttributeError:
        pass

try:
    import winreg
except ImportError:
    print("本脚本仅支持 Windows")
    sys.exit(1)


ROOT = Path(__file__).resolve().parent.parent
BAT_PATH = ROOT / "启动应用.bat"
ICON_PATH = ROOT / "assets" / "app-icon.ico"
SHORTCUT_NAME = "CDTV 漫剧客户端.lnk"


def get_desktop_dir() -> Path:
    """读取当前用户桌面目录（覆盖 OneDrive / 自定义路径情况）"""
    try:
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Explorer\Shell Folders",
            0,
            winreg.KEY_READ,
        )
        try:
            desktop, _ = winreg.QueryValueEx(key, "Desktop")
        finally:
            winreg.CloseKey(key)
        if desktop:
            return Path(desktop)
    except OSError:
        pass
    return Path.home() / "Desktop"


def create_shortcut() -> Path:
    if not BAT_PATH.is_file():
        raise FileNotFoundError(f"找不到启动脚本：{BAT_PATH}")
    if not ICON_PATH.is_file():
        raise FileNotFoundError(f"找不到图标文件：{ICON_PATH}")

    desktop = get_desktop_dir()
    desktop.mkdir(parents=True, exist_ok=True)
    shortcut_path = desktop / SHORTCUT_NAME

    # 通过 PowerShell + WScript.Shell COM 创建快捷方式
    # WindowStyle=1 表示正常显示 cmd 窗口（让用户能看到 Vite 启动日志和错误）
    ps_script = f"""
$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut("{shortcut_path}")
$shortcut.TargetPath = "{BAT_PATH}"
$shortcut.WorkingDirectory = "{ROOT}"
$shortcut.IconLocation = "{ICON_PATH},0"
$shortcut.WindowStyle = 1
$shortcut.Description = "漫剧客户端 - OriginalDoubao 视频生成"
$shortcut.Save()
"""
    import subprocess
    result = subprocess.run(
        ["powershell", "-NoProfile", "-Command", ps_script],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"PowerShell 创建快捷方式失败：{result.stderr}")

    return shortcut_path


def main() -> None:
    try:
        shortcut = create_shortcut()
        print(f"✅ 桌面快捷方式已创建：\n   {shortcut}")
        print(f"   目标：{BAT_PATH}")
        print(f"   图标：{ICON_PATH}")
    except Exception as exc:
        print(f"❌ 创建失败：{exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
