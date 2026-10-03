# H3 运镜规划与提示词编译

Schema 2.6 的 H3 素材使用本规范。`camera_plan` 和 `camera_motion` 是本 skill 的内部导演字段，不是 MiniMax API 参数或保证执行的控制器；最终提交的是自然语言 `generation.prompt`。

运镜词义依据 MiniMax H3 官方仓库的 [base prompt guide](https://github.com/MiniMax-AI/MiniMax-H3/blob/main/.agents/skills/h3-prompt-writing/references/base-en.txt) 与 [reference prompt guide](https://github.com/MiniMax-AI/MiniMax-H3/blob/main/.agents/skills/h3-prompt-writing/references/ref-en.txt)，核对日期 2026-09-05。本文件只负责运镜与时间线；完整字段、参考分析和原生音频规则见 [H3 工业级提示词契约](h3-prompt-contract.md)。

## 先规划再编译

1. 确定素材是一条连续镜头还是用户要求的剪辑片段。默认 `continuous`；4–7个动作节拍仍可属于同一个镜头。
2. 在同一场景坐标系下写摄影机开场状态，之后每个节拍以前一段终点作为起点。机位不混入人物事实账本。
3. 每段选一个主要运动类型，明确路径和目标。普通幅度、正常速度不必在最终英文动作句中重复强调；发生明显速度或方向变化时，用动作节拍划分，不机械每0.5秒拆段。
4. 检查轨迹是否在给定时间内可完成，接触点是否可见，人物运动是否会出画。不要为了景别变化同时塞入推、摇、升降和变焦；必要的复合运动可按连续路径分段。
5. 从结构字段统一生成 `acts[].camera` 和导演时间线中的 `camera`，再生成最终 Prompt，不独立手写三份运镜。

## 数据字段

每个 H3 素材包含：

```json
{
  "camera_plan": {
    "mode": "continuous",
    "axis": "SCENE-001 内人物东西对话轴线",
    "transition_from_previous": "start",
    "transition_reason": "序列开场"
  }
}
```

`mode` 为 `continuous/montage`。素材之间的摄影机衔接使用 `start/match/cut`：第一条为 `start`；`match` 要求上一素材末机位与本素材首机位逐键一致且轴线相同；`cut` 说明换机位的叙事目的。此字段与人物 `continuity.transition_from_previous` 独立：人物时间连续时也可以切换摄影机。未经用户要求不把素材内部改为蒙太奇。

每个 `acts[]` 增加以下结构，时间直接使用该 act 的 `time`，不另造时间线：

```json
{
  "camera_motion": {
    "movement": "push_in",
    "start": {
      "position": "门内南侧距门4米",
      "height_m": 1.5,
      "facing": "北侧人物胸前",
      "framing": "中全景，人物居中",
      "focal_mm": 35,
      "axis_side": "south"
    },
    "end": {
      "position": "门内南侧距门3米",
      "height_m": 1.5,
      "facing": "北侧人物胸前",
      "framing": "中景，人物居中",
      "focal_mm": 35,
      "axis_side": "south"
    },
    "speed": "slow",
    "amplitude": "small",
    "path": "沿南北方向向人物平稳前移1米",
    "target": "人物双手与信封",
    "motivation": "让观众看清信封交到谁手中",
    "cut_before": false
  }
}
```

`position` 用场景地标表达机身位置，连续状态复制原值，不换同义词；`facing` 表示视轴方向/固定瞄准点；`framing` 写景别和主体构图；高度、焦距是正数规划值，不代表模型精确物理模拟。画幅来自 `target.aspect_ratio`。

`speed` 为 `slow/normal/fast`，`amplitude` 为 `small/medium/large`。固定机位建议 `normal/small`，最终动作句不输出速度幅度。`target`、`path`、`motivation` 写具体内容，不能只写“跟随主体”“增加电影感”。

`cut_before: true` 只允许 montage 的非首段，并填写 `cut_reason`。连续运动越轴时填写 `axis_bridge`，说明可见弧线或经过轴线的过程；不能靠一句“保持轴线”掩盖机位瞬移。cut 的理由与实际动作切点必须吻合。

## 运动类型与不变量

| movement | 意义 | 需要核对 |
|---|---|---|
| static | 固定机身和镜头 | 位置、高度、朝向、焦距不变；主体可移动 |
| push_in / pull_out | 机身前移/后移 | 位置变化，焦距不变 |
| zoom_in / zoom_out | 变焦推近/拉远 | 机身位置、高度、朝向不变；焦距增大/减小 |
| pan_left / pan_right | 原地水平摇镜 | 机身位置、高度、焦距不变，改变视轴 |
| truck_left / truck_right | 机身横移 | 位置变化，焦距不变 |
| tilt_up / tilt_down | 原地俯仰 | 机身位置、高度、焦距不变 |
| pedestal_up / pedestal_down | 机身升降 | 高度增加/减少，焦距不变 |
| arc | 绕目标弧线移动 | 路径写方向和范围；跨轴要交代 |
| tracking | 跟随移动主体 | 写跟随谁、沿什么路线及相对距离 |
| handheld | 手持晃动 | 写晃动幅度与基准机位，不等同硬切 |

POV 是视点关系，写在状态和目标中。甩镜是快速摇镜，不是横移；Crash Zoom 是快速变焦，不是机身快速前进。动作慢放属于时间表现，不等于摄影机移动缓慢。

## 最终 Prompt

编译器保留中文剧情、台词与空间描述，摄影机运动用自然英文动作句表达，包含运动类型、幅度、速度、路径、目标和目的。完整机位起点/终点保存在 `camera_motion` 供校验，不重复塞进每个镜头句。结构字段是唯一运镜来源，`camera` 是派生文本。不要把整个导演 JSON 再重复拼入 Prompt。

每条素材只从 `[Shot 1]` 开始；后续动作节拍只保留 act 时间段，不增加 Shot 编号。只有实际硬切才增加 `[Shot N]` 并使用素材内的精确切点时间。不要把“中景变近景”自动翻译为剪辑。

`spatial_state` 的机位与首段 start 一致，`end_state` 的机位与末段 end 一致。修改摄影机后同步这些自然语言状态，但不能改动人物的世界位置去迎合机位。

内部 Markdown 可用 `**运镜计划：** {单行JSON}` 记录素材计划，用每幕 `- **运镜状态：** {单行JSON}` 记录运动状态，再映射到 JSON 的 `camera_plan` / `camera_motion`。缺字段或机位断裂先修复，不从含糊术语猜测距离；这些标记不代表客户端会直接解析 Markdown。

修改既有 JSON 时，保留用户已确定的生成模式、首尾帧和画幅，从 `camera_motion` 统一派生运镜文本，再全量复核。若另行安装了支持 `--compile-json` 的编译器，可使用其实际命令；本仓库未附该脚本，见 [客户端接入与工具边界](client-integration.md)。

## 校验边界

`E020 CAMERA_PLAN` 检查字段、连续段相等、match 跨素材相等、切镜模式、基本运动不变量，以及派生运镜是否进入最终 Prompt。速度是否合理、焦距和景别是否匹配、镜头是否穿墙、人物是否出画、打击点是否遮挡，仍需语义检查；实际执行效果需要成片核对。不要把结构校验结果说成 H3 成片保证。
