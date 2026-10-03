# MiniMax H3 输出配置

仅当目标模型为 `MiniMax-H3` 时读取本文件。短剧的风格锚点、一致性资产和状态链仍由本 Skill 的主流程负责；本文件只规定如何把每条 `shots[]` 变成符合官方 H3 约束的生成任务。

## 模式路由

每条生成任务只能使用一种官方 H3 模式。完整提示词契约见 [H3 工业级提示词契约](h3-prompt-contract.md)。

| 官方 H3 模式 | JSON `generation.mode` | 真实输入 | 提示词结构 |
|---|---|---|---|
| `T2VA` | `text_to_video` | 无上传参考文件 | 三个 Base 字段 |
| `I2VA` | `frame_to_video` | 仅首帧图片 | 首帧对齐指令 + 三个 Base 字段 |
| `FL2VA` | `frame_to_video` | 首帧和尾帧图片 | 首尾帧对齐指令 + 三个 Base 字段 |
| `L2VA` | `frame_to_video` | 仅尾帧图片 | 尾帧对齐指令 + 三个 Base 字段 |
| `Ref2VA` | `reference_to_video` | 角色/场景/道具/视频/音频参考 | 六个 Ref2VA 字段 |

JSON 额外保存 `generation.h3_mode`，用于审计真实模式；旧字段 `mode` 保持兼容。不要仅因为存在人物参考图就使用 `frame_to_video`：人物参考属于 `Ref2VA`，首尾帧才属于 I2VA/FL2VA/L2VA。

不要把 `CHAR-###`、`SCENE-###` 等稳定资产编号误写成 MiniMax 的上传槽位。最终 JSON 用 `generation.reference_order` 明确素材顺序；真正提交时，再把这些编号绑定到本地路径、URL 或 `mm_file://` 文件 ID，并保持顺序不变。

### 实际素材绑定（新编译契约）

内部 `shots[].references` 只表示依赖哪些一致性资产，不代表图片或音频已经存在。新编译输出标记 `generation.compiler_contract: "duanju_v2"`，用 `media_bindings` 明确实际输入。未绑定的资产不自动加入上传顺序；编译器将其卡片描述编入视频提示词，不复制参考设定图的四视图、白背景或负向块。

```json
{
  "generation": {
    "media_bindings": {
      "CHAR-001": {"kind": "image", "uri": "/absolute/path/character.png"}
    },
    "reference_order": ["CHAR-001"]
  }
}
```

路径仅展示结构，实际使用必须替换为已提供的文件路径、URL或 `mm_file://` 标识。`kind` 为 `image/video/audio`。身份卡与首尾帧不可互换；用作帧锚点的绑定额外声明 `role: "frame_anchor"`，只在 `first_frame/last_frame` 引用。绑定表示明确提供输入，不表示已上传或经过媒体尺寸、时长检查。

不提供绑定且不指定上传顺序时使用 T2VA；提供部分绑定时只上传指定资产，其余引用继续以文字约束。显式要求上传但未绑定会报 `E023`，不伪造文件，也不静默删除请求。旧JSON仍可按旧规则检查；重新编译进入新契约，须补全实际媒体绑定，或明确改为T2VA并清空 `reference_order` 与首尾帧。

Markdown分镜可以用 `**生成输入：** {单行JSON}` 写入该素材的 `generation`。绑定与正式模型模式的细节以本文件为准，不把资源声明混进画面文字。

## 官方限制

- 模型固定为 `MiniMax-H3`，分辨率固定为 2K。
- 单次时长为 4–15 秒整数；本 Skill 未指定时仍默认 10 秒。
- Prompt 最多 7000 字符。
- 参考图片最多 9 张；格式 JPEG/JPG/PNG/WebP，边长 256–5760 px，宽高比 0.4–2.5。
- 参考视频最多 3 段；MP4/MOV、H.264/H.265、23.976–60 FPS；每段 2–15 秒，总计不超过 15 秒。
- 参考音频最多 3 段；MP3/WAV；每段 2–15 秒，总计不超过 15 秒。
- 图片、视频和音频合计最多 12 个。MMX CLI 本地文件还受单文件和 Base64 请求体限制；真正提交前按官方 `mmx-h3-video` Skill 做媒体预检。

## Prompt 组装

每个 `shots[].generation.prompt` 必须是一条可独立提交的完整 Prompt，不得写“承接上一镜”。编译器必须按 [H3 工业级提示词契约](h3-prompt-contract.md) 输出正式字段：

1. 先决定 `h3_mode`，再决定参考文件的职责；不允许先堆素材再猜模式。
2. Base 模式输出 `integrated_multimodal_description`、`overall_soundscape`、`non_diegetic_music`；I2VA/FL2VA/L2VA 的对齐指令必须放在第一行。
3. Ref2VA 输出 `subject_definitions`、`summary`、`retention_analysis`、`detailed_description`、`overall_soundscape`、`non_diegetic_music`，并在六段中稳定复用 `<Subject N>`、`<Picture N>`、`<Video N>`、`<Audio N>` 标签。
4. 从 `spatial_state` 开始，把 `acts[]` 的画面、运镜和有声源的声音按播放顺序展开，最终到达 `end_state`；对白和可见文字保持原语言。
5. 负向约束作为独立句子写入，不要把用户未要求的品牌、对白、字幕或音乐塞进画面。

运镜按 [H3 运镜规划](camera-h3.md) 生成并编译，区分动作节拍与实际切镜。运镜字段属于本 skill 的导演结构，不是官方 API 参数。总时长与每幕动作时间线都要保留；自然节拍边界沿用 acts，不要求每0.5秒机械拆分。只有实际硬切才增加 Shot 编号。

本次运镜依据 MiniMaxAI 官方基础与参考提示词指南（链接见运镜规划）。本文件的服务参数沿用现有配置，提交时仍须核对所用服务端点；不要把运镜指南中的写法当作强制 API 字段或执行保证。

## JSON 字段

顶层 `target`：

```json
{
  "provider": "MiniMax",
  "model": "MiniMax-H3",
  "resolution": "2K",
  "aspect_ratio": "16:9"
}
```

每条 `shots[]` 增加：

```json
{
  "generation": {
    "mode": "reference_to_video",
    "h3_mode": "Ref2VA",
    "prompt_contract": "h3_official_v1",
    "prompt": "可独立提交且不超过7000字符的完整提示词",
    "first_frame": null,
    "last_frame": null,
    "reference_order": [
      "CHAR-001",
      "SCENE-001"
    ],
    "reference_manifest": [
      {
        "asset_id": "CHAR-001",
        "h3_label": "<Subject 1>",
        "input_label": "<Picture 1>",
        "role": "character_identity",
        "retention": "fully_preserved"
      }
    ]
  }
}
```

`frame_to_video` 的 I2VA 必须设置 `first_frame`，FL2VA 同时设置 `first_frame` 和 `last_frame`，L2VA 必须只设置 `last_frame`；填写可解析为图片文件的稳定资产 ID，并保持 `reference_order` 为空。其他模式的 `first_frame`、`last_frame` 写 `null`。`reference_order` 只列真正作为 H3 输入文件上传的视觉/视频/音频资产。用于内部事实约束但未上传的资产仍可保留在 `shots[].references`，不要放入 `reference_order`。

## 提交边界

本 Skill 默认只生成并校验 JSON，不自动产生付费任务。用户明确要求生成视频时，再遵循 MiniMax 官方 `mmx-h3-video` Skill：先检查付费 API Key 和媒体，固定传 `--model MiniMax-H3`，使用一次阻塞式生成命令等待并下载；已有任务 ID 后不得因等待或下载问题重复创建付费任务。
