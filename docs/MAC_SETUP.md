# Mac 用户安装、浏览器配置与打包说明

适用于这次已加入 Mac 适配的源码版本。主要工作是安装 Mac 环境和浏览器，无需再修改 Windows 代码。Mac 路径尚未经过实机运行或打包验证。

## 1. 把修改后的源码复制到 Mac

使用这次修改后的完整项目源码，放到 Mac 的一个新文件夹，例如“文稿”里的 `comoc-drama-client`。如果这些改动还没有发布到 GitHub，直接下载仓库旧版本不会包含它们。

项目根目录应能看到这些文件：

```text
launcher.py
constants.py
dola_login.py
original_doubao_base.py
macos_support.py
requirements.txt
requirements-macos.txt
launcher.macos.spec
启动应用.command
frontend/
```

复制源码时跳过 Windows 生成的 `.venv/`、`frontend/node_modules/`、`frontend/dist/`、`build/`、`dist/`、`release/` 和 `runtime/chrome-win64/`。这些环境和产物在 Mac 上重新准备。已有的 Windows 项目和数据保留在原电脑，不用删除。

## 2. 安装 Python、Node.js 和 Mac Chrome

按官方页面下载并安装：

- [Python 的 macOS 安装包](https://www.python.org/downloads/macos/)：项目要求 Python 3.11 或更高版本。
- [Node.js](https://nodejs.org/en/download)：选择 macOS 的 LTS 安装包。当前前端依赖要求 Node 20.19+（20.x）或 22.12+。
- [Google Chrome](https://www.google.com/chrome/)：选择 Mac 版本，把 `Google Chrome.app` 放到“应用程序”里。

使用普通 Google Chrome 时，无需创建 `runtime/`，也不用改浏览器路径。客户端会查找 `/Applications/Google Chrome.app/Contents/MacOS/Google Chrome`，也支持用户自己的 `~/Applications` 目录。

打开 Mac 的“终端”，确认安装后能找到命令：

```bash
python3 --version
node --version
npm --version
```

若显示 `command not found`，先完成对应软件安装，再关闭并重新打开终端。

## 3. 安装项目依赖并构建前端

在终端输入 `cd` 和一个空格，把项目文件夹拖进终端，然后按回车。后面的命令都从这个项目目录开始执行。

依次执行下面的命令；某一步报错时，先处理该错误再继续：

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-macos.txt
cd frontend
npm ci
npm run build
cd ..
```

必须使用 `requirements-macos.txt`，它会一起安装基础依赖和 Mac 的 Cocoa / WebKit 依赖。不要使用 Windows 的 `.venv/Scripts/python.exe`。

## 4. 启动客户端

在项目根目录执行：

```bash
.venv/bin/python launcher.py
```

也可以执行：

```bash
bash ./启动应用.command
```

希望以后双击启动时，先执行一次：

```bash
chmod +x ./启动应用.command
```

之后在 Finder 双击 `启动应用.command`。这个脚本使用已构建的页面；修改前端源码后，需要在 `frontend/` 目录重新执行 `npm run build`。

进入客户端后，添加豆包或 Dola 账号，再打开该账号的浏览器并手动登录。建议在 Mac 重新登录，不直接复制 Windows 的 Chrome Profile。Mac 的自动化浏览器窗口会保持可见。

## 可选：内置 Mac 浏览器

安装普通 Mac Chrome 已足够。只有希望项目自带浏览器时，才需要准备下面这些目录。

在 Mac 的“关于本机”查看芯片：Apple M 系列选择 `mac-arm64`，Intel 处理器选择 `mac-x64`。从 [Chrome for Testing 官方下载页](https://googlechromelabs.github.io/chrome-for-testing/) 的 Stable 区域下载 **chrome** 对应平台的压缩包，解压后把整个浏览器目录放到项目的 `runtime/`。

最终目录应当是：

```text
comoc-drama-client/
└─ runtime/
   ├─ chrome-mac-arm64/                 # Apple M 系列，选择这一套
   │  └─ chrome.app/
   │     └─ Contents/MacOS/Google Chrome for Testing
   └─ chrome-mac-x64/                   # Intel，选择这一套
      └─ chrome.app/
         └─ Contents/MacOS/Google Chrome for Testing
```

按自己的芯片选择一套即可。保留完整 `chrome.app`，不要只复制其中一个可执行文件。不能通过把 `chrome-win64` 改名来获得 Mac 浏览器，也不用把 Python 里的路径手动改成 Windows 路径。

## 可选：在 Mac 上打包成 CDTV.app

先完成上面的依赖安装和前端构建，再在 **Mac 本机的项目根目录**执行：

```bash
.venv/bin/python -m pip install 'pyinstaller>=6'
.venv/bin/python -m PyInstaller launcher.macos.spec --noconfirm --clean
```

输出为 `dist/CDTV.app`，可复制到“应用程序”。Mac 用 `launcher.macos.spec`，Windows 仍用原来的 `launcher.spec`。[PyInstaller 要求在目标操作系统上构建应用](https://pyinstaller.org/en/stable/)。

这份配置默认依赖接收者已安装的 Mac Chrome，不会把 `runtime/` 里的浏览器一并打进 `.app`。Apple Silicon 与 Intel 版本按各自架构环境分别构建；当前配置未验证构建，也未配置公开分发用的 Developer ID 签名和公证。

## 数据位置和常见问题

源码运行时，数据仍放在项目下的 `data/`，生成文件默认放在 `output/`。打包 `.app` 后，默认分别放到 `~/Library/Application Support/CDTV/data/` 和 `~/Library/Application Support/CDTV/output/`。设置中心可以修改存储和输出目录。

若需要迁移已有项目，先关闭两端客户端并保留原始备份，再复制项目数据；进入 Mac 客户端后检查存储目录、输出目录和素材路径，Windows 的绝对路径需要重新选择。源码的数据不会自动迁移到 `.app` 的新目录。

| 提示或现象 | 处理方法 |
| --- | --- |
| 找不到 `requirements-macos.txt` 或 `macos_support.py` | 使用这次改过的完整源码；确认终端已经进入项目根目录。 |
| 找不到 `frontend/dist/index.html` | 进入 `frontend/`，执行 `npm ci` 和 `npm run build`。 |
| 找不到 `webview`、`AppKit` 或 `Foundation` | 用 `.venv/bin/python -m pip install -r requirements-macos.txt` 安装，启动时也用同一个 Python。 |
| 提示未找到 Mac 版 Chrome | 把 Mac 版 Google Chrome 放到“应用程序”，或核对内置浏览器的目录层级。 |
| `.venv/bin/python` 不存在或环境不可执行 | 在一个未复制 Windows 环境的新源码目录里，重新执行第 3 步。 |
| 前端提示 Node 版本不支持 | 按当前依赖的版本要求升级 Node.js，再安装前端依赖。 |
| 提示缺少 `ffmpeg` / `ffprobe` | 视频兼容转换等功能需要另装 FFmpeg；从 Finder 启动会搜索 `/opt/homebrew/bin` 和 `/usr/local/bin`。 |

本文仅说明准备和启动步骤，不表示 Mac 功能已经验证通过。
