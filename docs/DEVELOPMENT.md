# 开发、构建与打包

[English](DEVELOPMENT.en.md) | 简体中文

本文档面向开发者，说明源码运行、构建、前端开发、打包为 exe 与目录结构。面向用户的功能说明见 [README](../README.md)。

---

## 环境要求（源码运行）

- Windows 10 / 11
- Python 3.11+
- Node.js 20.19+（20.x）或 22.12+；建议使用满足此范围的 LTS 版本
- 系统需安装 **WebView2 Runtime**（Win10/11 通常自带）

## 安装

以下 PowerShell 命令从项目根目录执行。`npm ci` 按仓库锁文件安装依赖；Node.js 下限以当前 Vite 与 Vue 插件的 `engines.node` 为依据。

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
cd frontend
npm ci
npm run build
cd ..
```

## 运行桌面版

```powershell
.venv\Scripts\python launcher.py
```

应用启动时会自动拉起内置的本地存储服务并以单机账号进入，无需额外启动任何服务。

## 前端开发模式

安装依赖后，可直接双击项目根目录的 `启动应用.bat`：脚本会启动或复用 5173 端口上的 Vite，再以开发模式打开桌面客户端；需先准备 `.venv` 环境。手动启动方式如下：

先启动 Vite：

```powershell
cd frontend
npm run dev
```

再打开另一个位于**项目根目录**的终端：

```powershell
.venv\Scripts\python launcher.py --dev
```

---

## 打包为 exe

项目已提供 `launcher.spec`，用 PyInstaller 打包为 Windows 可执行文件（目录模式）：

```powershell
# 1. 先构建前端
cd frontend
npm run build
cd ..

# 2. 安装 PyInstaller（若未安装）
.venv\Scripts\python -m pip install pyinstaller

# 3. 打包
.venv\Scripts\python -m PyInstaller launcher.spec --noconfirm --clean
```

产物位于 `dist/CDTV/`。分发时保留整个目录及 PyInstaller 依赖，不能只复制 exe。**分发时把 `runtime/chrome-win64` 放到 `CDTV.exe` 同级目录**，使最终路径为 `dist/CDTV/runtime/chrome-win64/chrome.exe`。当前 Worker 必须读取此路径，不会自动下载浏览器；`data/`、`output/` 会在首次运行时自动生成在 exe 同级目录。

注意：

- 目标机器需安装 **WebView2 Runtime**，否则 pywebview 无法启动。
- 不再需要 Java 运行时，也不需要 storage jar。
- Playwright 驱动随 exe 打包；浏览器内核复用 `runtime/chrome-win64`。

## 本地回归验证

以下测试使用临时数据库和本机模拟模型服务，不读取真实 API Key，也不消耗模型额度：

```powershell
.venv\Scripts\python -m unittest scripts.test_migration_regressions scripts.test_image_generation -v
.venv\Scripts\python -m scripts.test_local_storage
node --test scripts/test_chapter_save.mjs
```

前端测试需先安装 `frontend/` 的依赖。已检查的迁移问题与实测边界见 [迁移检查记录](MIGRATION_AUDIT.md)。

## 常见启动问题

- **找不到前端产物**：在 `frontend/` 执行 `npm ci` 和 `npm run build`，再回项目根目录运行 `launcher.py`。
- **开发模式空白页**：检查 `http://127.0.0.1:5173` 是否可访问、Vite 是否仍在运行；单独用浏览器打开页面不具备 `pywebview` 桌面 API。
- **提示内置浏览器不存在**：核对 `runtime/chrome-win64/chrome.exe`，OriginalDoubao 自动化需要此文件。
- **AI 生成配置报错**：图片、MiniMax 音色试听、Seedance 视频和文本转发已接入，检查模型是否启用，以及 API 地址、API Key 和模型名是否完整。修改 Python 服务代码后需重启客户端。
- **修改存储目录后仍使用旧目录**：目录修改在重启客户端后生效，不会自动搬移原数据。需要保留原数据时，关闭客户端后复制完整实际存储目录到目标目录。
- **修改后仍显示旧逻辑**：Python 改动需完全退出并重启客户端；Vite 只热更新前端。非开发模式读取 `frontend/dist`，前端改动后需重新构建。

## 目录结构

```text
comoc-drama-client/
├─ launcher.py            # 桌面主入口
├─ local_storage.py       # 内置纯 Python 本地存储服务（SQLite + 文件桶）
├─ original_doubao_worker.py       # Playwright 账号 Worker 与转换流程
├─ original_doubao_nomark.py       # 链接类型、域名校验与视频解析
├─ media_server.py        # 本地媒体预览服务
├─ constants.py           # 共享常量与路径
├─ launcher.spec          # PyInstaller 打包配置
├─ SKILL/                 # AI 分镜创作能力定义（SKILL.md + references/）
├─ frontend/              # Vue 3 前端
├─ assets/                # 应用图标
├─ scripts/               # 工具脚本（图标生成、窗口调试、快捷方式等）
├─ docs/                  # 补充文档
└─ data/ output/          # 运行时数据（已 gitignore）
```
