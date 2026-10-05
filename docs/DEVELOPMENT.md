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
.venv\Scripts\python -m unittest scripts.test_migration_regressions scripts.test_image_generation scripts.test_generation_accounts -v
.venv\Scripts\python -m scripts.test_local_storage
node --test scripts/test_chapter_save.mjs
node --test scripts/test_account_creation.mjs
```

前端测试需先安装 `frontend/` 的依赖。已检查的迁移问题与实测边界见 [迁移检查记录](MIGRATION_AUDIT.md)。

账号中心支持 `doubao`（OriginaDoubao）与 `dola`（Dola）两种 `accountType`；历史账号缺少该字段时默认 OriginaDoubao。添加账号时选定平台，每个账号仍使用独立浏览器 profile。固定平台的自动分配在该平台内轮换，Dola 登录校验读取国际版页面；图片 / 视频生成共用流程匹配中英文控件。

账号默认每日视频次数为 OriginaDoubao 3 次、Dola 4 次，分别读取 `dailyVideoQuota` 与 `dolaDailyVideoQuota`。旧 Dola 账号即使存有 `dailyQuota: 3`，也按 4 次计算。登录或重新登录不清空当天已用次数；新账号初始化、成功扣次、账号卡片、剩余次数和自动分配均使用对应平台次数。保留原有“单账号上限”控件及其 `dailyVideoQuota` 保存方式，选择 Dola 不切换或修改该控件；平台差异只体现在账号次数和分配逻辑中。`scripts.test_generation_accounts` 与 `scripts/test_account_quotas.mjs` 覆盖第四次可用、第五次拦截、次数保留及控件保持不变。

Dola 的生成确认若同时提示“今日剩余 0 个视频生成额度”（或英文当天剩余 0 视频额度），本次任务继续等待视频，不立即标记额度用完。视频返回后，保存 `quotaExhaustedAfterGeneration`；下载 / 上传流程进入终态时，先完成成功扣次，再将账号今日剩余额度归零，最后释放账号，避免被自动分配再次选中。视频已生成但下载 / 上传失败也归零；尚未返回视频或已取消的任务不凭这条确认归零。普通成功计数及次日重置方式保持原逻辑，未扩展为按模型消耗量计费。

链接转换接受两个平台的官方页面以及 `*.douyin.com` / `v*-*.dola.com` 视频直链，必须选择对应平台账号。直链读取 MP4 的 `vid:` 元数据；豆包继续通过 `/alice/resource/get_video_model` 获取 fplay 模型并解析无 logo 视频流。

Dola 使用网页实际调用的 `/creativity/resource/get_without_watermark`，请求为 `vid: [video_id]`，Web aid 为 `495671`。若返回 `without_watermark: false`，读取 `/creativity/user_config/get`；账号不要求升级且去 AI 水印开关尚未开启时，通过 `/creativity/user_config/set` 设置 `config_type: 1`、`watermark_option.is_on: true` 并重试。成功后保留开启状态，失败时恢复原关闭状态。只接受官方明确返回 `without_watermark: true` 的 `download_video[video_id].download_url`，不把播放或预览地址当成原片。Dola 的 HTTP 请求使用对应浏览器的新鲜 Cookie、系统代理与 Dola Referer，不调用豆包国内解析接口。此流程已用真实 Dola 直链验证成功，下载的 1280×720、10.08 秒视频保留音轨，抽查多个时刻未见 Dola AI 水印。

自动生成结果也优先走对应平台的原片解析；解析失败的链接转换报错，不把原带水印直链当作转换结果。自动生成仍保留有水印下载兜底并标记 `resultWatermarked`。仅改变 `lr` 参数不能保证去水印，未来原片获取仍受登录态、地区、账号功能与站点接口变化限制。

`python -m unittest scripts.test_link_conversion` 和 `node --test scripts/test_link_conversion.mjs` 覆盖链接域名、账号匹配、MP4 ID、平台 Referer、原片选择及解析失败处理。

`scripts.test_generation_accounts` 使用临时账号数据和本地网页夹具检查路由、登录、上传与提交，不访问真实 Dola 服务、不消耗账号额度。真实站点的模型可用性和页面布局仍需登录账号进行验证。

视频工作台提供 Do 与 Seedance 卡片。Do 下可选择自动、OriginaDoubao、Dola，也支持批量切换；新分镜默认 Do 自动。自动模式提交 `generationEngine: do`、`accountType: auto`，随机分配两个平台内未占用且有额度的账号，排除未登录过和已知登录失效的账号，不受顶部账号平台限制。固定平台提交对应的 `accountType`，只在该平台分配；旧请求仍沿用所选账号平台，旧项目的固定平台选择保持不变。任务表的 `accountType` 始终保存实际账号类型。Dola 的中英文模型控件与独立比例/时长下拉框均有本地夹具覆盖；`node --test scripts/test_video_platforms.mjs` 检查工作台选择、提交和任务恢复。

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
