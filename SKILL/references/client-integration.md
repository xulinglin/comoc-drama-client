# CDTV 客户端接入与工具边界

本文件用于把分镜规范接入当前仓库，避免把创作字段、客户端导入和模型提交当成同一个步骤。操作依据为 `frontend/src/components/VideoCreationWorkspace.vue`、`launcher.py` 和 `local_storage.py`。

## 仓库包含什么

`SKILL/` 当前包含 `SKILL.md` 和 `references/` 创作规范，未随附 `scripts/`、`assets/minimal-project.json` 或自动化回归测试。文档中的“编译”指按规则派生数据与提示词，不代表本仓库已提供可执行编译器。

- 可以依据规范生成、转换和人工复核完整 JSON。
- 使用外部安装的 `duanju` 工具包时，先确认其脚本、版本和参数实际存在，再运行编译或校验。
- 未执行外部校验器时，报告“已解析 JSON／已按规则复核”，不得报告“自动校验通过”“回归测试通过”或伪造错误代码日志。
- 文档中的 `E/W` 编号是复核问题的分类；客户端导入器没有实现这些完整质量门禁。

## 客户端实际导入范围

创作任务的 JSON 导入器按字段读取数据，当前没有按 `schema_version` 严格拒绝版本。界面中的“JSON 2.0”是提示文案；本规范的新输出版本为 `2.6`，两者不能据此认定为完全兼容或不兼容。

| 来源字段 | 客户端用途 |
| --- | --- |
| `consistency`，否则 `assets`，否则顶层 | 资产数据根对象 |
| `characters` / `roles` / `people` | 人物资产 |
| `scenes` | 场景资产 |
| `props` / `items` | 道具资产 |
| `audio` / `audios` | 音频资产 |
| `layouts` / `white_models` / `whiteModels` / `blockings` | 客户端兼容的白模资产；Schema 2.6 不新增这类正式资产 |
| `reference_prompts` 中各组的 `id` 和 `prompt` | 按资产 ID 匹配参考图提示词 |
| 顶层 `shots`，否则资产根对象中的 `shots` | 分镜列表 |
| `shots[].title`、`duration_s` / `duration` | 分镜名称和时长；客户端时长归一到 1–15 秒整数 |
| `shots[].acts` 中的 `time/name/visual/camera/audio` | 组合为界面可编辑的视频描述 |
| `shots[].references` | 解析到已有资产；不存在的引用会被过滤，导入前须主动检查 |
| `title` / `project`、`schema_version` | 导入标题和版本显示 |

导入至少需要一项可识别资产。只有 `shots` 的文件会被拒绝；没有可导入分镜时，当前任务的原分镜会保留。导入会替换资产列表，存在分镜时也会替换分镜列表，操作前先保存当前任务。

`generation.prompt`、H3 模式、`media_bindings`、结构化连续性、导演时间线和剪辑时间字段目前不会完整映射为客户端生成参数。导入成功只说明部分数据可读取，不代表完整 H3 任务已配置或会原样提交。音频资产的生成提示词目前使用客户端内置文本，不能把它当作对白原文已接入 TTS 的证明。

## 按任务选择处理范围

- **从剧本新建数据**：按主流程生成资产、参考图提示词、连续性和分镜；目标为 H3 时追加 H3 字段。
- **转换第三方 JSON**：先识别来源和目标结构，保留已确定的剧情、对白、镜头顺序及用户指定参数。只为格式兼容的转换，不强制改成 3D、10 秒或 H3。
- **继续按本 Skill 创作**：只有用户要求进入完整生产规范时，才按目标模型补齐导演、连续性和提交字段；不能把转换顺便扩展成重写剧情。
- **提交视频任务**：独立检查所选生成引擎、实际媒体和接口。H3 创作规范不代表客户端已内置 H3 调用。

## 校验与外部工具

先解析标准 JSON，再按 [数据模型](json-schema.md) 和 [质量校验](quality-validator.md) 检查引用、时间覆盖、状态交接、对白预算和目标字段。手工复核与自动校验分别记录，成片结果需要另外检查。

本仓库环境可做 JSON 语法检查，以下命令从项目根目录运行；请把文件名换成实际输出文件：

```powershell
.\.venv\Scripts\python.exe -m json.tool .\output\project.json > $null
```

这条命令只检查 JSON 语法，不验证 Schema、剧情语义或生成能力。

仅当另行安装的工具包确实包含相应脚本时，可按该工具包说明使用 `duanju_plugin.py`、`validate_duanju_json.py` 以及 `--compile-json`、`--strict-design`、`--verify-media`。工具目录使用实际安装路径；不要将这些脚本路径拼到本仓库 `SKILL/` 下。外部工具的版本兼容性、文件存在性检查和报错行为，以实际执行结果为准。
