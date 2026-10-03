# MiniMax H3 工业级提示词契约

本契约按 MiniMax 开源仓库中的 [base prompt guide](https://github.com/MiniMax-AI/MiniMax-H3/blob/main/.agents/skills/h3-prompt-writing/references/base-en.txt) 与 [reference prompt guide](https://github.com/MiniMax-AI/MiniMax-H3/blob/main/.agents/skills/h3-prompt-writing/references/ref-en.txt) 重构；动作拆分、镜头明确、声音显式化和参考资产职责也吸收了 [awesome-minimax-h3-prompts](https://github.com/xianyu110/awesome-minimax-h3-prompts) 的公开实践。若官方字段更新，以官方仓库为准，再更新本契约与编译器。

本文件负责把状态、动作、参考资产和原生音频组装为 H3 提示词；机位状态与路径由 [运镜规划](camera-h3.md) 定义。这里的“编译”指数据派生过程，本仓库未附 `camera_h3.py` 等编译脚本，工具边界见 [客户端接入说明](client-integration.md)。

## 1. 先选输入模式，再写提示词

每条素材只能选择一种 H3 模式。选择依据是“输入文件真正要承担的任务”，不是资产数量。

| H3 模式 | 内部 `generation.mode` | 适用条件 | 关键连续性要求 |
|---|---|---|---|
| `T2VA` | `text_to_video` | 没有上传图片、视频或音频参考 | 从文字建立完整的视听时间线 |
| `I2VA` | `frame_to_video` | 只有首帧图片 | 第一帧先对齐，再从第一帧状态向前发展 |
| `FL2VA` | `frame_to_video` | 同时有首帧和尾帧图片 | 描述首帧到尾帧之间的可见路径；尾帧只能在结尾落地 |
| `L2VA` | `frame_to_video` | 只有尾帧图片 | 从合理的前置状态逐步收敛到尾帧 |
| `Ref2VA` | `reference_to_video` | 人物、场景、道具、声线等作为可追踪参考 | 使用六个固定字段和稳定参考标签 |

旧版 `mode` 继续保留，便于已有 JSON 兼容；新增 `generation.h3_mode` 作为明确的 H3 模式。未填写时按下列规则推导：`text_to_video→T2VA`、`reference_to_video→Ref2VA`、`frame_to_video+first_frame+last_frame→FL2VA`、`frame_to_video+first_frame→I2VA`、`frame_to_video+last_frame→L2VA`。

不要把人物参考图、场景参考图和白模布局图混成一类。角色/场景/道具图片用于身份和外观；首帧/尾帧图片用于时间锚点；视频参考用于动作或剪辑结构；音频参考用于复制或声线参考。

## 2. Base 模式的固定字段

`T2VA`、`I2VA`、`FL2VA`、`L2VA` 最终必须按以下顺序生成：

```text
[模式对齐指令，仅 I2VA / FL2VA / L2VA 有]

integrated_multimodal_description: [Shot 1] ...

overall_soundscape: ...

non_diegetic_music: ...
```

`integrated_multimodal_description` 是主体，必须按播放顺序写出开场构图、主体位置、环境、动作变化、反应、镜头运动、对白和同步的画内声音。`overall_soundscape` 只写全片环境声、动作声和非语言人声，不重复对白。`non_diegetic_music` 只写角色听不见的观众侧配乐；没有配乐时写 `N/A`。

对齐指令必须是提示词第一行，后空一行：

```text
For the target video, at 0.00 seconds into the target video, <Picture 1> (from [Shot 1]) is fully referenced.
How the reference pictures align with the target video — Picture 1 (from Shot 1) aligns with the 0.00-second mark of the target video; Picture 2 (from Shot 1) aligns with the 10.00-second mark of the target video.
How the reference pictures align with the target video — <Picture 1> (from [Shot 1]) aligns with the 10.00-second mark of the target video.
```

三条分别对应 I2VA、FL2VA、L2VA，不能同时出现。

## 3. Ref2VA 的六段固定顺序

只要使用 `reference_to_video`，提示词必须严格使用以下顺序，字段名保持英文小写：

```text
subject_definitions:
...

summary:
...

retention_analysis:
...

detailed_description:
...

overall_soundscape:
...

non_diegetic_music:
...
```

参考标签在六段中含义不变：

| 标签 | 代表 | 生成规则 |
|---|---|---|
| `<Subject N>` | 实际要出现在成片中的人物、场景、道具、服装、UI 或视觉效果 | 每个需要持续追踪的可见主体一行 |
| `<Picture N>` | 上传的图片素材 | 只在图片承担首帧、尾帧、构图锚点时单独定义；纯身份参考可写在 Subject 定义内 |
| `<Video N>` | 上传的视频素材 | 只在需要动作、剪辑、节奏或续接结构时定义 |
| `<Audio N>` | 上传的音频素材 | 说明是复制原声还是只参考音色、节奏或质感 |

`retention_analysis` 每行写一个标签和关系标记：`fully_preserved`、`partially_preserved`、`attribute_transfer`、`weak_reference`；音频使用 `fully_copy`、`partially_copy`、`reference` 或 `weak_reference`。不要把新增加的剧情动作误判成参考内容丢失。

主体定义必须按参考职责写词：人类使用 face/hair/clothing/proportions，非人单体使用 species/silhouette/anatomy/material，场景使用 geometry/landmarks/lighting， 道具使用 shape/material/condition。不能对场景和道具套用人物身份句式。每个 `<Picture N>`、`<Subject N>`、`<Video N>`、`<Audio N>` 标签在整条 Prompt 中只能有一个稳定含义；首帧和尾帧即使使用同一文件，也必须占用不同的 Picture 标签。

## 4. 时间线与切镜

- 第一镜永远写 `[Shot 1]`，不写时间戳。
- 后续真正硬切才增加编号，并写 `[Shot N] At MM:SS.mmm, ...`。
- 同一连续镜头内的自然动作节拍只写在同一个 Shot 段落中，不把每个 `acts[]` 自动变成硬切。
- 每个 `acts[].time` 都要在详细描述中落成明确的 `From HH:MM.mmm to HH:MM.mmm` 时间区间；这是动作节拍，不等于新增硬切。
- 所有切点必须严格递增、落在素材时长内；素材 10 秒就用 `10.00` 作为尾帧落点，不能写成 `00:10.000` 之外的模糊表达。
- 每个素材提示词必须自洽，不能出现“承接上一镜”“继续刚才动作”等外部指代。连续性必须展开为可见的开场状态。
- 单条素材围绕一条主要叙事因果链组织：准备/起势 → 动作发展 → 结果/反应。战斗可以包含互相承接的多轮攻防，按 [10 秒打戏 PREVIS](action-previs-10s.md) 分节拍；互不依赖的事件应拆素材。

## 5. 运镜写法

运镜由 `camera_motion` 唯一生成，不能在 Prompt 中另写一套。自然英语至少包含：运动类型、幅度、速度、关注目标和路径目的，例如：

```text
The camera pushes in with small amplitude at slow speed toward the glowing account badge, keeping the character on the left third while the background remains stable.
```

`push_in` 是机身前移，`zoom_in` 是焦距改变；不能用“靠近”同时表示两者。越轴必须在 `axis_bridge` 中给出可见路径。固定镜头、变焦、摇镜和机身移动须符合 [运镜规划](camera-h3.md) 的状态不变量。

## 6. 对白、屏幕文字和声音

- 角色或旁白分配稳定声源 ID `(S1)`、`(S2)`；同一角色全片复用同一 ID。
- 对白必须保留原语言并放在 `<d>[语言] 原文</d>` 中，例如 `<d>[Chinese] 我活到最后了。</d>`。
- 画面中实际出现的 UI、公告、招牌和字幕放入英文双引号，文字与标点逐字保留，例如 `The screen displays "全球公告：存活玩家：1".`。
- `overall_soundscape` 不重复对白；碰撞、脚步、风、机械运转等只写有画面声源的声音。
- 没有观众侧配乐时使用 `non_diegetic_music: N/A`。禁止为了填满音轨凭空加入心跳、鼓点或提示音。
- 中文创作稿可以保留在内部 `acts[]`；H3 提示词的字段名和结构必须保持英文，真正的对白、可见文字、专名按原文保留。

## 7. 参考资产的最小职责

每个上传文件只承担一个主要职责，并在 `generation.reference_manifest` 中写清楚：

```json
{
  "asset_id": "CHAR-001",
  "h3_label": "<Subject 1>",
  "input_label": "<Picture 1>",
  "role": "character_identity",
  "retention": "fully_preserved"
}
```

如果一张图同时包含人物和场景，可以定义两个 Subject，但必须在定义中说明同一张 Picture 提供哪些信息；如果图片只是人物身份参考，不要把它伪装成首帧。

## 8. 生产前硬校验

交付前必须逐条通过：

1. H3 模式与上传素材类型一致，旧 `mode` 与 `h3_mode` 不冲突。
2. Prompt 只出现一套正式字段；没有旧式大段中文“时间线”与新字段重复描述。
3. 所有 `[Shot N]` 只对应真实切镜，切点时间和 `acts[].time` 一致。
4. 所有 `camera_motion`、`camera`、导演时间线和 Prompt 中的运镜文字由同一来源生成。
5. `subject_definitions` 中的标签在 `summary`、`retention_analysis`、`detailed_description` 中保持一致。
6. 角色身份、服装、发型、比例和三视图逻辑由一致性卡锁定；镜头提示词只写动作和可见状态，不重新发明外貌。
7. 默认视觉路线为“高精度3D写实国漫 / 3D CG”；除非用户明确要求真人实拍，否则必须排除真人实拍、真人照片、真人实景、摄影棚真人肖像和写实摄影照片效果。
8. 内容表现尺度由 `style.negative_prompt` 统一决定，参考 [风格锚点](style-anchor.md) 的条件性约束；编译器不得追加与项目已确定的伤势表现相冲突的负向。媒介、身份漂移和水印等技术约束仍统一去重。未提供项目负向时才使用默认非血腥回退。

9. Prompt 不超过 7000 字符，素材时长为 4–15 秒整数；最多 9 张图片、3 段视频、3 段音频，总数不超过12项。
10. 负向约束只输出一份；style 锚点已经包含的负向句不得在编译器中重复拼接。
11. 若存在 `inner_theater`，详细时间线先描述现实层，再描述Q版的观众可见叠加关系、锚点、尺度、遮挡和动作；内心声按 `channel: inner` 绑定 `inner_voice` 声源和Q版口型，明确Q版开口说逐字原文、本体在该句期间闭嘴。独立童声须读取Q版音频卡的音色。不得把Q版写成现实小人或让其改变现实摄影机。
