---
name: duanju
description: 根据中文短剧剧本生成、修改或转换分镜 JSON，包含人物、场景、道具、声音一致性与连续性复核；新建创作默认高精度3D写实国漫，目标为 MiniMax H3 时追加其模式、运镜和 Prompt 规范。
---

# 短剧 AI 视频生产 Skill

本 Skill 负责把剧本变成可审计、可提交、可连续生成的短剧 JSON。新建创作的默认媒介是**高精度3D写实国漫**；人物、场景、道具和镜头使用同一个视觉锚点。已有数据的格式转换保留来源已确定的媒介和参数。

## 使用范围与运行环境

本仓库提供创作参考规范，未随附编译器、校验脚本或完整示例资产。首次对接客户端、转换第三方 JSON 或准备执行外部工具时，读取 [客户端接入与工具边界](references/client-integration.md)。导入成功、人工复核、自动校验和成片验证分别报告。

| 用户任务 | 读取与处理范围 |
| --- | --- |
| 从剧本新建分镜 | 执行下方生产管线，按题材加载对应参考 |
| 修改现有角色、镜头或 JSON | 读取相关规则，修正上游事实并同步受影响的引用、状态和提示词 |
| 导入第三方 JSON | 先按客户端字段映射；仅格式转换时不强制改媒介、时长或模型 |
| 输出 MiniMax H3 数据 | 追加 H3 配置、Prompt 契约和运镜规则 |

## 执行契约

- 用户明确给出的角色事实、服装、画幅、时长、模型和负向要求优先级最高。
- 不把风格预设中的姓名、身高、衣服、配饰、场景或物种移植给当前剧本。
- 人物身份、场景几何、道具结构和声音只在一致性卡定义一次；分镜只写可见状态和动作。
- 新建创作默认每条素材 10 秒；H3 目标接受用户明确指定的 4–15 秒整数，其他模型遵守其支持范围。格式转换保留来源已确定的时长。
- 用户要求 JSON 时交付完整、可解析、通过校验的 JSON；较大项目保存为文件并提供链接，用户明确要求直接粘贴时输出完整代码块。不得用摘要、占位符或截断片段替代数据。
- 默认不提交付费生成任务；只生成和校验提交所需数据。

## 生产管线

按 [工业级短剧生产协议](references/production-protocol.md) 执行六段管线：

1. **输入契约**：识别剧本、已有分镜、人物样本、既有 JSON 和修改要求，锁定模型、画幅、时长和媒介。
2. **风格锚点**：默认写入高精度3D写实国漫、CG建模、PBR材质、细腻材质、稳定曝光和用户指定色彩；不把镜头动作、UI 或临时状态写进公共风格词。
3. **一致性资产**：提取 `CHAR-###`、`SCENE-###`、`PROP-###`、`AUDIO-###`，为每个视觉资产生成完整参考图提示词和 `identity_lock`。
4. **状态图与分镜**：每条素材建立 `spatial_state → acts → end_state` 和 `continuity.state_in/state_out`；桥接动作不得省略。
   对白、悬疑、情绪、救援与操作戏读取 [文戏导演与时间管理](references/drama-editing.md)；限时剧情区分生成、剪辑与故事时间。
5. **目标模型输出**：仅在目标为 MiniMax H3 时读取 [H3 输出配置](references/minimax-h3.md)、[H3 Prompt 契约](references/h3-prompt-contract.md) 和 [H3 运镜规划](references/camera-h3.md)，统一派生运镜与最终 Prompt。其他目标不强加 H3 字段。
6. **质量门禁**：按 [质量校验](references/quality-validator.md) 解析 JSON 并复核结构与语义；已安装外部校验器时再运行自动检查。有任何 `E` 级问题就修复上游事实并全量重检，警告需确认，不能伪称未执行的检查已通过。
   新项目可在顶层写 `design_contract: "duanju_design_v1"`，声明人物服装/外貌、场景地标、道具结构和各自 `identity_lock` 应可复现；自动门禁需外部工具支持，旧项目不强制迁移。

## 人物资产分支

人物参考图必须读取 [人物提示词编排器](references/character-prompt-style.md) 和 [一致性提取器](references/consistency-extractor.md)。

- **服装设计**：创建人物卡时执行人物提示词编排器的“服装设计与定稿”规则；未指定的服装主动完成符合世界观与身份的角色造型，主角具有可辨识的廓形、搭配层次和材质细节，不能只填颜色与衣服品类。先写入人物卡，再生成参考图。
- **人类单体**：固定保留用户指定的 16:9 横版布局——左侧同一角色大幅正脸半身特写，右侧正面/标准侧面/背面全身；正面双手自然下垂，侧面端正站立，背面和鞋子完整入镜。这个逻辑不可改成其他三视图或单人全身图。
- **非人单体**：不使用人类四视图模板。用单一画面全身生物设定图锁定物种、整体剪影、头部识别点、材质、四肢、爪和尾部；城市规模、天气、建筑和剧情动作只进入镜头层。
- **固定群体**：使用透明 PNG 单画面，完整展示准确成员数量；不生成三视图、分栏、多宫格或场景背景。
- **状态边界**：基础人物图保持干净常态；“干净”指没有剧情临时状态，不要求服装素面或删去固有剪裁、纹样、饰边与配饰。灰尘、磨损、账号牌、武器、投影、HUD、表演情绪和战斗姿态写入镜头状态或道具卡，不写进基础身份。
- **媒介负向**：默认排除真人实拍、真人照片、真人实景、摄影棚真人肖像、写实摄影照片效果、身份漂移、肢体错误、文字和水印。涉及危险题材时按资产用途加入必要的非血腥约束，不把整组视频负向机械复制到人物参考图。
- **3D Q版内心戏**：用户要求内心戏、吐槽或脑内小剧场时，读取 [3D Q版内心戏](references/inner-theater.md)。Q版建立独立 `CHAR-###` 并用 `variant_of` 关联现实本体；现实层、Q版叠加层、内心声和退场状态分开记录。

## 场景与道具资产设计

创建或修改场景、道具卡时，读取 [场景与道具设计定稿](references/environment-prop-design.md)。场景先明确主形体、区域关系、视觉焦点、材质分区和光源；道具先明确轮廓、功能结构、材质工艺和识别点。未指定的美术设计先写入卡片再生成参考图，不能只列地点或物件名称，也不能靠装饰新增剧情功能。

## H3 模式与素材边界

| 模式 | 适用输入 | Prompt 结构 |
|---|---|---|
| `T2VA` | 无上传参考 | `integrated_multimodal_description` + 声音 + 配乐 |
| `I2VA` | 只有首帧 | 首帧对齐指令 + Base 三段 |
| `FL2VA` | 首帧和尾帧 | 首尾帧对齐指令 + Base 三段 |
| `L2VA` | 只有尾帧 | 尾帧对齐指令 + Base 三段 |
| `Ref2VA` | 身份/场景/道具/视频/音频参考 | 六段 Ref2VA 字段 |

H3 硬上限：4–15 秒整数、Prompt 不超过 7000 字符、图片最多 9 张、视频最多 3 段、音频最多 3 段、合计最多 12 个。身份参考不能冒充首帧，首尾帧不能放进 `reference_order`。

## 镜头与连续性硬规则

- `camera_plan` 定义素材级轴线和开场机位，`camera_motion` 定义幕级路径；`camera`、导演时间线和 H3 Prompt 全部由 `camera_motion` 派生。
- 固定、推拉、变焦、摇镜、横移和环绕必须符合机位状态；变焦改变焦距，机身移动改变位置，不能混写。
- 只有真实硬切才增加 `[Shot N]`；连续镜头内自然节拍不自动切镜。
- 每个动作必须有触发、可见过程、结果和收势；进出门、起身、转身、拾取、放下、换手、换装、上下车和退场需要桥接动作。
- 声音必须有剧本、可见动作或明确交互来源；对白放入 `<d>[语言] 原文</d>`，画面文字保留逐字原文，`overall_soundscape` 不重复对白。
- Q版通过 `inner_voice` 选择沿用本体或独立声线（可为用户指定的童声），用 `channel: "inner"` 和 Q版 `lip_sync_target` 标记；最终 Prompt 明确Q版开口说原文、本体在该句期间闭嘴。按 [3D Q版内心戏](references/inner-theater.md) 编排出入场、口型与停顿；普通旁白不自动触发Q版。

## 文件与校验

交付完整、可解析的 `.json` 文件或完整代码块。先检查 JSON 语法，再按 [数据模型](references/json-schema.md) 和 [质量校验](references/quality-validator.md) 复核资产、时间与连续性。工具可用性及语法检查命令见 [客户端接入说明](references/client-integration.md#校验与外部工具)。

`design_contract: "duanju_design_v1"` 是设计完整性的声明；当前客户端不会自动执行该门禁。使用另行安装的 `duanju` 工具包时，以其实际版本和检查结果为准。

## 导入第三方创作数据 JSON

外部数据先核对字段，再决定是否转换。已符合客户端支持结构的数据可直接导入；仅有语法有效不代表满足本 Skill 的完整生产规范。

### 导入流程

1. **识别来源和用途**：读取 JSON 或字段说明，确认是只导入客户端，还是继续按本 Skill 生产；目标结构参照 [数据模型](references/json-schema.md)，当前新输出版本为 `2.6`。
2. **建立字段映射**：标题 → `shots[].title`，画面 → `shots[].acts[].visual`，时长 → `duration_s`，角色/场景/道具/配音 → `consistency` 各组；实际客户端读取范围见 [客户端接入说明](references/client-integration.md)。
3. **保留来源事实**：剧情、对白原文、镜头顺序、既定媒介、画幅、时长与模型保持不变。已知事实不留空；无法确定且会影响结果的缺失信息询问用户。
4. **按用途补齐**：进入完整生产规范时补充稳定 ID、引用、空间状态和连续性；仅在目标为 H3 时派生 H3 字段。只做格式兼容时，不额外改写剧情或强制套用默认参数。
5. **分层复核**：解析 JSON，检查字段、引用、时间和语义；外部工具存在时执行其校验，再检查客户端实际导入结果。转换草稿与正式产物分开保存。

### 导入约定

- **以用户明确给出的事实为准**（角色、服装、画幅、时长、模型、负向要求）；来源未提供且无法确定的信息直接向用户询问，不猜测、不套用风格预设。
- 只做**格式转换**：不改变来源已经确定的剧情、对白原文和镜头顺序；本 Skill 只补全结构、派生 H3 字段并做一致性收敛。
- 继续创作且来源含丧尸、僵尸等题材时，按 [输出硬规则](references/json-schema.md) 的非血腥条款复核 `style.taboos` 等约束；仅转换格式时保留既有表现要求。
- 转换草稿与最终 JSON 分开保存；最终 JSON 才是项目数据的唯一正式产物。
- 默认不提交付费生成任务，导入只产出可提交、可校验的数据。

## 参考文档路由

按当前任务读取，不要求每次加载全部参考文档。

- 客户端、导入和外部工具：[client-integration.md](references/client-integration.md)

- 生产协议：[production-protocol.md](references/production-protocol.md)
- 风格锚点：[style-anchor.md](references/style-anchor.md)
- 人物与资产：[character-prompt-style.md](references/character-prompt-style.md)、[consistency-extractor.md](references/consistency-extractor.md)
- Q版内心戏：[inner-theater.md](references/inner-theater.md)
- 分镜与连续性：[shot-prompt-generator.md](references/shot-prompt-generator.md)、[continuity-combat.md](references/continuity-combat.md)、[action-previs-10s.md](references/action-previs-10s.md)
- H3：[minimax-h3.md](references/minimax-h3.md)、[h3-prompt-contract.md](references/h3-prompt-contract.md)、[camera-h3.md](references/camera-h3.md)
- JSON 与门禁：[json-schema.md](references/json-schema.md)、[quality-validator.md](references/quality-validator.md)
