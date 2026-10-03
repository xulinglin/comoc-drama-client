# 数据模型：duanju 最终 JSON（v2.6）

内部完成前三步后，必须把全部有效结果序列化为一个完整 JSON 对象。交付方式以 `SKILL.md` 为准：小对象可直接给代码块，大项目交付完整 `.json` 文件；不得用摘要替代项目数据。

本文件的 JSON 代码块是字段示例，不能直接拼接后当作已验证项目。正式产物须补齐必填字段、完整提示词和全部素材，再按质量规则复核；客户端导入与外部工具边界见 [接入说明](client-integration.md)。

## 输出硬规则

- Schema 2.6 的资产只有人物、场景、道具、音频；参考图提示词只有人物、场景、道具。空间约束写入 `spatial_state/end_state` 和 `continuity`，不输出 `layouts` 字段或布局引用。
- 稳定编号只使用 `CHAR-###`、`SCENE-###`、`PROP-###`、`AUDIO-###`；每个视觉资产必须有同 ID 的完整参考图提示词。

- 最终 JSON 是项目数据的唯一正式产物；文件交付可附简短路径和校验结果，不展示冗余中间稿。
- 输出必须是可直接解析的标准 JSON：使用双引号，不写注释，不使用 `...`、`……`、`null` 占位已知内容或模板变量。
- 新输出的 `schema_version` 固定为 `2.6`；旧文件保留其原始版本，是否需要迁移取决于任务；外部校验器的兼容版本以实际安装版本为准。
- Schema 2.6 的 `identity_lock`、`exit_state`、`landmarks`、`lighting_baseline`、`performance`、高风险导演时间线和 `hook` 按 [动画导演字段](animation-direction.md) 执行。
- MiniMax H3 输出必须包含顶层 `target`，且每条 `shots[]` 包含 `generation`；详细字段和模式边界见 [minimax-h3.md](minimax-h3.md)。
- 不使用 `Mixed`、`asset_tag` 或 `voice_tag` 替代正式资产编号。
- `consistency.reference_prompts` 必须收录第二步全部人物、场景和道具参考图提示词；分别写入 `characters`、`scenes`、`props`，提示词不得缩写。
- 每条参考图提示词应标注 `scope` 与 `negative_scope`：人物为 `character_identity`，场景为 `scene_environment`，道具为 `prop_design`；`negative_scope` 默认 `asset_only`。它们限制该提示词只服务于当前资产，不把视频级运镜、UI、阶段状态或整组非血腥词自动复制进来。
- 每个 `characters[]` 必须包含 `character_type`、`member_count`、`background_mode` 和 `output_format`。单体资产固定为 `individual / 1 / white / png`；现实人类单体使用左侧特写＋右侧正/侧/背全身设定板，非人单体使用单一画面完整生物设定图。`visual_variant: "chibi"` 使用 [Q版分支](inner-theater.md) 的单一全身设定图，不套用现实人物四视图。固定群体人物为 `group / 准确成员数 / transparent / png`，整个群体使用一个 `CHAR-###` 和一张透明背景群体角色图，禁止三视图、角色设定板、分栏和多宫格。
- Schema 2.3及以上每个 `characters[]` 必须包含 `identity_lock`，每个 `scenes[]` 必须包含 `landmarks` 与 `lighting_baseline`。
- 剧本含丧尸、僵尸、亡灵、尸化角色、腐尸、尸王或变异怪物时，`style.taboos` 必须声明“非血腥表现”或“无血腥”；`style.negative_prompt`、`style.public_visual_prompt.zh` 的负向段保留视频所需的非血腥约束；人物参考图按当前资产选择必要负向项，不要求固定词组逐字匹配。相关 `characters[].appearance` 只能使用灰败肤色、干枯完整皮肤、凹陷眼窝、僵硬姿态等非血腥正向特征，不得以伤口、腐烂创面、裸露组织、内脏或残缺肢体塑造角色。
- `shots[].references[].id` 必须能在对应一致性卡中找到；`kind` 与 ID 前缀必须匹配。
- `shots[].duration_s` 默认全部为 `10`；MiniMax H3 允许用户明确指定 4–15 秒整数。
- 每个 `shots[]` 必须同时包含 `spatial_state` 和 `end_state`。`spatial_state` 是00:00第一帧，必须与第一幕第一句一致；`end_state` 是最后一幕结束时的确定可见状态，必须与最后一幕最后一刻一致。
- 每个 `shots[]` 必须包含 [连续性账本](continuity-combat.md) `continuity`；`continuous` 素材的 `state_in` 必须与上一素材 `state_out` 逐键完全一致。
- Schema 2.6 中每镜必须包含 `risk_level` 与 `hook`；高风险镜头必须包含完整 `director_timeline`，且各幕必须包含 `performance`。战斗镜头还必须包含 `action_design`；角色退场写入 `continuity.exit_state`。
- 除剧本明确时间跳跃或转场外，相邻素材必须满足上一条 `end_state` 与下一条 `spatial_state` 的物理状态连续：人物位置、姿态、朝向、左右手、持有道具、穿戴装备、伤势、门窗或车辆状态和UI状态不得无桥接动作改变。机位允许切换，但下一素材必须完整重述。
- `shots[].acts` 必须完整保留时间码、画面、运镜和音频，不得在 JSON 中压缩或概括。
- 战斗幕的 `visual` 必须展开起始距离与相对站位、脚步与重心、左右手和攻击轨迹、防守动作、接触点、受击反应、收势与结束距离；伤害数字只能作为接触后的结果，不能替代动作。2至4秒内不得压入多个独立攻击或多个换装/拾取/学习动作。
- 配音按每秒最多约4.5个可读字符校验；同幕存在咆哮、碰撞或关键动作音效时，先为音效预留至少0.5秒。超出预算时拆分字段或新增素材，不得用“快速播报”强行容纳。
- 没有额外声音的幕，`audio` 保留一条 `type: "none"`；不得为避免空数组而编造音效。
- 面板原文保存在 `visual` 中并保持换行；`audio[].detail` 保存自然播报文本。进度型显示值如 `经验：0/100` 默认播报为 `经验：0`，不得把斜杠机械读出。
- 输出前必须执行 [质量校验与自动修复](quality-validator.md)。自动检查仅在外部校验器确实可用时执行，见 [工具边界](client-integration.md)；存在任何 `E` 级错误（包括 MiniMax H3 的 `E016`）时修复并重新全量校验，不能交付带阻断错误的JSON。
- MiniMax H3 的 `generation.reference_order` 必须遵守最多9张图片、3段视频、3段音频、合计12项；首帧/尾帧写在 `first_frame/last_frame`，不得混入 `reference_order`。`reference_manifest` 的 `<Picture N>`、`<Subject N>`、`<Video N>`、`<Audio N>` 标签不得重复。

## 顶层结构

```json
{
  "schema_version": "2.6",
  "project": "mori-online",
  "title": "末日online",
  "generated_at": "2026-08-16T00:00:00+00:00",
  "target": {
    "provider": "MiniMax",
    "model": "MiniMax-H3",
    "resolution": "2K",
    "aspect_ratio": "16:9"
  },
  "style": {},
  "consistency": {},
  "shots": []
}
```

## style（第一步）

```json
{
  "visual_route": "3d_cg",
  "public_visual_prompt": {
    "zh": "完整中文公共视觉词",
    "en": null
  },
  "genre": "末日重生、游戏系统流",
  "type_tags": [
    "男频爽剧",
    "末日生存"
  ],
  "benchmark": "未指定",
  "mood": {
    "core": [
      "爽",
      "燃"
    ],
    "pacing": "默认10秒一个生成素材，长内容继续拆分"
  },
  "visual": {
    "overall_style": "风格化3D动画、电影级末日游戏CG",
    "color": "低饱和冷灰青色调",
    "lighting": "阴天漫射光",
    "quality_texture": "4K、高精度建模、细腻材质",
    "static_elements": "破败混凝土、锈蚀金属",
    "dynamic_ui_style": "半透明冰蓝数据框、淡蓝系统光屏、红色敌人血条；只用于逐幕变化段或后期叠加"
  },
  "camera": {
    "shot_size": "开场特写，环境揭示使用全景",
    "movement": "紧张段缓推，环境揭示使用摇镜",
    "pacing": "每幕2至4秒"
  },
  "audio": {
    "bgm": "低频电子氛围",
    "sfx": "只使用剧本、可见动作或明确交互能够支持的声音",
    "voice_direction": "角色使用固定声线；面板原文完整显示，系统声线按显示顺序自然播报，进度值默认只读当前值"
  },
  "taboos": [
    "无血腥断肢特写"
  ],
  "negative_prompt": "每项均带独立否定指令的完整负向要求"
}
```

`public_visual_prompt.en` 仅在确实生成英文版时填写；没有英文版时允许为 `null`。当前生成模式不用的 `first_frame/last_frame` 也可按 H3 规则写 `null`；这些声明允许为空的字段与占位不同。其他能够从前三步确定的字段不得使用 `null`。

## consistency（第二步）

```json
{
  "characters": [
    {
      "id": "CHAR-001",
      "name": "林风",
      "character_type": "individual",
      "member_count": 1,
      "background_mode": "white",
      "output_format": "png",
      "aliases": [
        "林风"
      ],
      "gender_age": "男，约25岁",
      "appearance": "坚毅面容，锐利双眼，颧骨分明，身形修长结实",
      "outfit": "军绿色旧工装夹克，深色内搭，多口袋结构，袖口与下摆自然磨损，破旧直筒牛仔裤，深色作战靴",
      "hair": "黑色碎短发",
      "temperament": "谨慎、坚毅、冷静",
      "scenes": [
        "末日废墟街道"
      ]
    },
    {
      "id": "CHAR-002",
      "name": "五只普通丧尸群",
      "character_type": "group",
      "member_count": 5,
      "background_mode": "transparent",
      "output_format": "png",
      "aliases": [
        "五只普通丧尸群",
        "丧尸群"
      ],
      "gender_age": "成年男性体型群体",
      "appearance": "五只灰败皮肤的普通丧尸，面部结构与干枯皮肤质感有可见差异",
      "outfit": "五套脏污破损的末日前日常服装，颜色与破损位置各不相同",
      "hair": "稀疏凌乱短发，长度与缺损细节各不相同",
      "temperament": "迟钝、僵硬、具有攻击性",
      "scenes": [
        "末日废墟街道"
      ]
    }
  ],
  "scenes": [
    {
      "id": "SCENE-001",
      "name": "末日废墟街道",
      "asset_type": "environment",
      "environment": "坍塌街道、破损高楼、瓦砾和废弃车辆",
      "lighting": "阴天漫射光、低饱和冷灰青色调",
      "key_elements": [
        "破败混凝土",
        "碎玻璃",
        "锈蚀金属"
      ],
      "characters": [
        "林风",
        "普通丧尸"
      ],
      "persistent": true,
      "continuity": "本场景全部分镜"
    }
  ],
  "props": [
    {
      "id": "PROP-001",
      "name": "破旧钢管",
      "appearance": "暗灰色锈蚀金属，多处刮痕，一端轻微弯曲",
      "tags": [
        "白色·普通",
        "属性文字后期叠加"
      ],
      "scene": "末日废墟街道",
      "holder": "林风",
      "persistent": true,
      "continuity": "林风捡起后持续握持至本场景结束"
    }
  ],
  "audio": [
    {
      "id": "AUDIO-001",
      "character": "林风",
      "voice": "青年男声，中低音，略带沙哑",
      "speed": "中速",
      "tone": "警惕、震惊、自嘲",
      "catchphrase": "这他娘的真是游戏"
    },
    {
      "id": "AUDIO-002",
      "character": "系统播报",
      "voice": "中性电子声，吐字清晰",
      "speed": "中速",
      "tone": "客观、平稳",
      "catchphrase": "无"
    }
  ],
  "reference_prompts": {
    "characters": [
      {
        "id": "CHAR-001",
        "name": "林风",
        "scope": "character_identity",
        "negative_scope": "asset_only",
        "prompt": "完整人物参考图提示词"
      },
      {
        "id": "CHAR-002",
        "name": "五只普通丧尸群",
        "scope": "character_identity",
        "negative_scope": "asset_only_plus_non_gore_if_needed",
        "prompt": "完整透明背景群体人物参考图提示词；准确展示五名成员；禁止三视图、设定板、场景和背景"
      }
    ],
    "scenes": [
      {
        "id": "SCENE-001",
        "name": "末日废墟街道",
        "scope": "scene_environment",
        "negative_scope": "asset_only_plus_non_gore_if_needed",
        "prompt": "完整场景参考图提示词"
      }
    ],
    "props": [
      {
        "id": "PROP-001",
        "name": "破旧钢管",
        "scope": "prop_design",
        "negative_scope": "asset_only",
        "prompt": "完整道具参考图提示词"
      }
    ]
  }
}
```

正式输出时，`prompt` 必须替换为第二步已经生成的完整提示词，不能保留示例文字。

## shots（第三步）

Schema 2.6 的 H3 素材必须包含 [H3 运镜规划](camera-h3.md) 中的 `camera_plan` 与每幕 `camera_motion`，`camera` 由编译器派生。以下片段只演示通用字段，完整 H3 输出还须合并运镜字段。

每个 `### **《剧名》N秒动画脚本**` 对应一条 shot。顶部一致性引用只保存一次，各幕不重复保存引用。`spatial_state` 保存00:00开场状态，`end_state` 保存素材结束状态；两者用于相邻素材连续性校验，不得省略。

```json
{
  "shots": [
    {
      "id": 1,
      "duration_s": 10,
      "title": "末日Online：系统面板初现",
      "generation": {
        "mode": "reference_to_video",
        "h3_mode": "Ref2VA",
        "prompt_contract": "h3_official_v1",
        "prompt": "完整的 MiniMax H3 可提交提示词",
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
      },
      "references": [
        {
          "kind": "character",
          "label": "林风参考",
          "id": "CHAR-001"
        },
        {
          "kind": "scene",
          "label": "末日废墟街道场景参考",
          "id": "SCENE-001"
        },
        {
          "kind": "audio",
          "label": "系统声线参考",
          "id": "AUDIO-002"
        }
      ],
      "spatial_state": "林风坐在末日废墟街道中央偏左的瓦砾中，身体微微前倾，左手手腕抬至胸前，右手撑在身体右侧地面；机位位于林风右后方并与肩部齐高，过肩特写。",
      "end_state": "林风仍坐在瓦砾中，左手手腕保持在胸前，右手仍撑地；淡蓝色系统面板保持展开并显示当前字段；机位停在林风右后方过肩近景。",
      "continuity": {
        "transition_from_previous": "start",
        "state_in": {
          "CHAR-001.location": "街道中央偏左瓦砾中",
          "CHAR-001.pose": "坐姿",
          "CHAR-001.left_hand": "抬至胸前",
          "CHAR-001.right_hand": "撑地",
          "ui.system_panel": "关闭"
        },
        "state_out": {
          "CHAR-001.location": "街道中央偏左瓦砾中",
          "CHAR-001.pose": "坐姿",
          "CHAR-001.left_hand": "抬至胸前",
          "CHAR-001.right_hand": "撑地",
          "ui.system_panel": "展开"
        }
      },
      "acts": [
        {
          "time": "00:00-00:03",
          "name": "第一幕：欢迎信息",
          "visual": "淡蓝色光屏展开，准确文字标注为后期叠加。",
          "camera": "过肩中近景，缓推镜头靠近手腕光屏。",
          "audio": [
            {
              "type": "voice",
              "desc": "系统配音（客观播报）",
              "detail": "欢迎来到‘末日online’。"
            }
          ]
        },
        {
          "time": "00:03-00:10",
          "name": "第二幕：静默停留",
          "visual": "面板保持显示。",
          "camera": "固定镜头锁定面板。",
          "audio": [
            {
              "type": "none",
              "desc": "无额外音效/配音"
            }
          ]
        }
      ]
    }
  ]
}
```

### references 类型映射

| ID 前缀 | kind | 分镜写法 |
|---|---|---|
| `CHAR-` | `character` | `林风参考 {{CHAR-001}}` |
| `SCENE-` | `scene` | `末日废墟街道场景参考 {{SCENE-001}}` |
| `PROP-` | `prop` | `破旧钢管道具参考 {{PROP-001}}` |
| `AUDIO-` | `audio` | `林风声线参考 {{AUDIO-001}}` |

## 最终输出方式

交付完整 JSON 文件或代码块，包含 `style`、四类正式资产及三类参考图提示词的 `consistency`、全部 `shots`；目标模型需要时包含 `target` 和 `generation`。默认不展示 Markdown 中间稿。

## 2.6兼容扩展：生产字段

- `generation.compiler_contract: "duanju_v2"` 与 `media_bindings`：实际素材输入检查，见 [H3 输出配置](minimax-h3.md)。旧文档中的裸ID参考示例仅表示引用结构，重新编译须补实际绑定。
- `consistency.audio[].source_id`、`acts[].audio[].source_id`：全剧稳定的 `S1/S2` 声源ID，编译器保留并校验身份冲突。
- `acts[].action_type`：`combat/interaction/dialogue/reveal/movement/hold`。明确类型优先于关键词；旧数据的 `combat` 对象继续兼容，未分类且出现战斗词只提示语义复核。
- `shots[].timing`、顶层 `time_constraints`：可选剪辑区间及故事时钟，限时剧情必须填写；结构与示例见 [文戏导演与时间管理](drama-editing.md)。
- 场景和道具支持 `identity_lock`；Markdown卡用“身份锁JSON”列承载，音频卡可用“声源ID”列。美术新增细节必须写入卡片，不能只写到参考图。
- `consistency.characters[]` 的 Q版变体使用 `visual_variant: "chibi"`、`variant_of` 与 `chibi_design`；`shots[].inner_theater` 必须包含锚点、相对尺寸、遮挡、光线和 `composition.safe_area / max_frame_occupancy / occlusion_limit`；`pov_character`、`acts[].inner_action` 和内心声字段见 [3D Q版内心戏](inner-theater.md)。这些字段只在用户要求内心戏时出现。
- 新项目按严格设计要求复核；外部校验器支持时可用 `--strict-design`：人物服装/外貌、场景地标与 `identity_lock`、道具外观与 `identity_lock` 必须可复现；旧 JSON 是否迁移按当前任务决定。
- 顶层可写 `design_contract: "duanju_design_v1"`，声明需要严格设计复核；自动执行该门禁需对应外部工具支持。
- H3 有本地上传素材时检查文件是否存在；外部校验器支持时可用 `--verify-media`；远程 URL 与 `mm_file://` 只检查绑定格式，不自动下载。
