# 客户端链接转换维护说明

本文档用于保护客户端“链接转换”功能，避免后续重构再次引入带水印下载、错误域名校验、账号锁未释放等问题。

适用范围是独立的 `convert_original_doubao_link` 链路。视频生成流程另有明确标记为带水印的保存回退，不能将其与本文件的“链接转换失败不得回退”规则混用。末尾样本是历史回归证据，不代表当前第三方接口或签名链接仍然可用。

## 支持的链接

### 1. OriginalDoubao 分享链接

支持：

```text
https://www.doubao.com/video-sharing?video_id=...
https://www.doubao.com/thread/...
```

校验规则：

- 协议只能是 `http` 或 `https`。
- 域名只能是 `doubao.com` 或 `www.doubao.com`。
- 使用用户选择的、已经登录的 OriginalDoubao 账号进行解析。

### 2. 抖音/OriginalDoubao 视频 CDN 直链

支持：

```text
https://*.douyin.com/.../video/tos/...?lr=video_gen_watermark_dyn...
```

校验规则：

- 域名必须是 `douyin.com` 或其真实子域名，例如 `v26-default.douyin.com`。
- 路径必须包含 `/video/tos/`。
- 不允许仅通过字符串包含 `douyin.com` 来判断域名，必须使用 `urlparse(...).hostname`，防止接受 `douyin.com.evil.example`。

## 必须保持的转换流程

### OriginalDoubao 分享链接

```text
用户输入分享链接
  → 校验链接
  → 选择并锁定已登录 OriginalDoubao 账号
  → 使用该账号的 Playwright Worker 和 Cookie
  → 解析 video_id / original media / fplay
  → 过滤带 watermark 的候选地址
  → 下载无水印媒体
  → 生成本地预览地址
  → 无论成功或失败都释放账号锁
```

此流程有历史验证记录。修改解析或登录态行为时，应按下方回归要求验证，不要仅凭公开、无 Cookie 的请求返回 HTTP 200 就认定结果等价。

### `douyin.com/video/tos` 直链

```text
用户输入 watermarked CDN 直链
  → 校验真实域名和 /video/tos/ 路径
  → 选择并锁定已登录 OriginalDoubao 账号
  → Range 请求读取 MP4 前部元数据
  → 从 comment 中提取 vid:v...
  → 使用账号登录态和 video_id 查询原始媒体地址
  → 优先解析登录态 fplay；必要时使用带 Cookie 的分享接口
  → 严格过滤 URL 中含 watermark 的结果
  → 下载确认后的无水印媒体
  → 无论成功或失败都释放账号锁
```

实测样例的 MP4 前 128 KiB 中包含：

```text
vid:v0269cg10004da255ja7dld0l91o9hpg
```

## 关键结论

### 账号是否必须

当前生产方案需要选择一个已登录 OriginalDoubao 账号。

原因不是下载 CDN 文件需要账号，而是从水印直链还原真正的原始无水印媒体地址需要 OriginalDoubao 登录态接口。账号只应在转换期间占用，完成或失败后必须释放。

### 禁止用 `lr` 参数改写冒充去水印

禁止把下面的改写当作可靠的无水印转换：

```text
lr=video_gen_watermark_dyn
↓
lr=video_gen_no_watermark
```

真实测试中，原 URL 和改写 URL 均返回 HTTP 200，但文件完全相同：

- 文件大小相同：`2,160,329` 字节。
- SHA-256 相同：`999010ff2f581bc3327eb23b03e1170ea439a348468122a6115baefb2da7ceef`。

因此，“请求成功”不代表“去水印成功”。

### 禁止回退保存水印源文件

如果无法获得确认后的无水印地址：

- 必须明确返回转换失败。
- 不允许回退下载原始 `watermark_dyn` 链接。
- 不允许显示“无水印转换完成”。

宁可失败，也不要把带水印文件当作成功结果交付。

## 关键代码位置

- 链接类型与域名校验：`original_doubao_nomark.py`
  - `is_douyin_media_url`
  - `is_supported_conversion_url`
- 客户端 API、账号加锁和释放：`launcher.py`
  - `DesktopApi.convert_original_doubao_link`
- Worker 转换流程：`original_doubao_worker.py`
  - `AccountBrowserWorker._convert_link`
  - `AccountBrowserWorker._video_id_from_media_url`
  - `AccountBrowserWorker._resolve_nomark_in_logged_in_page`
  - `AccountBrowserWorker._browser_cookie_dict`
  - `save_media_url`
- 前端输入、账号选择和结果展示：`frontend/src/App.vue`
  - `canConvertLink`
  - `convertOriginalDoubaoLink`

## 账号锁约束

- OriginalDoubao 分享链接和水印 CDN 直链转换都需要占用所选账号。
- 同一账号不能同时执行生成任务和链接转换。
- 转换必须使用唯一的 `usage_id`。
- 所有退出路径都必须通过 `finally` 调用 `_release_account_usage`。
- Worker 异常退出时不能遗留永久锁。
- 不要在转换尚未结束时提前释放账号锁。

## 错误提示要求

错误应区分以下情况：

- 链接域名或路径不受支持。
- 未选择 OriginalDoubao 账号。
- 所选账号正在运行其他任务。
- 所选账号未登录或登录态失效。
- CDN 链接已过期或无法访问。
- MP4 元数据中没有读取到 `video_id`。
- 登录态接口没有返回无水印地址。
- 下载无水印媒体失败。

错误信息不得把“无法解析无水印地址”描述成普通下载成功。

## 修改后的最低回归测试

修改以下文件中的链接校验、转换、下载、账号锁或对应界面逻辑后，应执行本节检查。纯文档、样式或无关功能修改不要求重新调用第三方转换接口：

```text
launcher.py
original_doubao_worker.py
original_doubao_nomark.py
frontend/src/App.vue
```

### 静态检查

```powershell
cd comoc-drama-client
.venv\Scripts\python.exe -m py_compile launcher.py original_doubao_worker.py original_doubao_nomark.py
cd frontend
npm run build
```

### 功能回归

联网回归使用可访问的近期样本与有效登录态；逐项记录结果。静态检查通过不代表功能回归通过，无法执行的项目标记为未验证。

1. 使用已登录账号转换一个 `doubao.com/thread/...` 链接，应成功生成无水印视频。
2. 使用已登录账号转换一个 `doubao.com/video-sharing?...` 链接，应成功生成无水印视频。
3. 使用已登录账号转换一个带 `lr=video_gen_watermark_dyn` 的 `*.douyin.com/video/tos/...` 直链，应先提取 `video_id`，再下载不同于水印源文件的原始媒体。
4. 验证输出 URL 不包含 `watermark`。
5. 对输出视频至少抽取开头、中间、结尾三帧，确认没有 OriginalDoubao 动态角标水印。
6. 转换完成后刷新账号列表，确认账号不再显示“运行中”。
7. 使用未登录账号测试，应明确失败，不得回退保存水印源文件。
8. 使用伪造域名 `https://douyin.com.evil.example/video/tos/...`，必须被拒绝。
9. 使用普通 `https://www.douyin.com/not-a-video`，必须被拒绝。

## 运行时注意事项

- Vue/Vite 可以热更新前端，但 Python 模块不会热更新。
- 修改 `launcher.py`、`original_doubao_worker.py` 或 `original_doubao_nomark.py` 后，必须完全退出 CDTV 客户端再重新启动。
- 如果错误提示仍是旧文案，优先检查是否仍在运行修改前启动的 Python 进程。
- CDN 直链可能带签名并会过期，调试时应使用刚复制的最新链接。

## 已验证基线

已验证的水印直链：

```text
host: v26-default.douyin.com
path contains: /video/tos/
query contains: lr=video_gen_watermark_dyn
video_id: v0269cg10004da255ja7dld0l91o9hpg
```

该链接的水印源文件为 `2,160,329` 字节；通过登录态解析得到的原始媒体为 `1,800,115` 字节，两者内容不同。此数据只用于回归判断，CDN 链接本身可能过期。
