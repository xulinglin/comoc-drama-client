# 人物一致性、场景锚点与动画导演字段

本文件定义 Schema 2.6 的动画导演字段。普通镜头保持轻量；`risk_level: high` 使用自然动作节拍导演时间线和完整表演曲线。Schema 2.3 的 `per_second_directives` 仅作旧文件兼容。

## 1. identity_lock

每个 `consistency.characters[]` 必须包含简短身份锁。它只保存跨图、跨镜绝不能变化的高辨识特征，不重复完整人物卡。

```json
{
  "identity_lock": {
    "silhouette": "清瘦长身、高马尾、窄袖短袍",
    "face_anchor": "琥珀眼、左眉尾短疤",
    "palette": "深灰、暗红、黑",
    "signature_props": [
      "PROP-001"
    ],
    "immutable": [
      "高马尾长度",
      "左眉尾短疤",
      "右手持剑习惯"
    ]
  }
}
```

群体资产的 `silhouette` 写群体共同轮廓，`immutable` 写成员数量和物种特征；成员间差异仍由人物卡与每镜空间状态管理。

## 2. landmarks + lighting_baseline

每个 `consistency.scenes[]` 必须包含：

```json
{
  "landmarks": {
    "断裂牌楼": "石阶顶端中央",
    "镇山碑": "石阶左侧"
  },
  "lighting_baseline": {
    "key_light": "左后方冷青月光",
    "fill_light": "云海冷色漫反射",
    "rim_light": "牌楼裂缝暗金光"
  }
}
```

同场景换机位时，地标在画面中的位置可以变化，但必须描述由镜头运动导致的变化；地标本身的空间关系和光源方向不能无解释翻转。

## 3. exit_state

`shots[].continuity.exit_state` 专门解释上一镜出现、后续镜头不再出现的角色：

```json
{
  "CHAR-003": {
    "last_position": "第八级石阶",
    "exit_action": "共享影核破碎，四只玄影狼同步崩解",
    "exit_direction": "原地消散",
    "reason": "失去共享影核供能",
    "final_status": "dissolved",
    "visible_result": "无狼形实体残留",
    "may_return": false
  }
}
```

`final_status` 使用：`offscreen`、`left_scene`、`escaped`、`defeated`、`incapacitated`、`dead`、`dissolved`、`sealed`、`captured`。退场动作必须实际出现在本镜 `acts[]`；`offscreen` 和 `may_return: true` 的角色仍保留在连续性跟踪中。

## 4. performance

高风险镜头的每个 `acts[]` 必须包含：

```json
{
  "performance": {
    "anticipation": "动作前可见预备",
    "action": "主要动作",
    "overshoot": "动作越过目标后的惯性；不适用时写不适用并说明",
    "settle": "身体如何稳定",
    "follow_through": "发丝、衣摆、武器或次级肢体的延迟跟随",
    "expression_path": "警觉 → 决断 → 确认"
  }
}
```

3D 国漫强调可读预备、惯性和收势，不机械照搬夸张挤压拉伸。静态停留也要说明呼吸、眼神或衣摆等最小生命感。

## 5. 高风险镜头导演时间线

以下任一情况将镜头标为 `risk_level: high`：打斗、追逐、多人交互、道具交接、复杂进出场、死亡/消散/退场、关键情绪爆发、口型与动作精确同步。

高风险镜头增加 `director_timeline[]`，覆盖整个素材且无空档、无重叠。按动作节拍划分，通常 4–7 段，每段 0.5–3 秒；禁止为了凑满时间重复同一句动作。每条包含：

```json
{
  "time": "00:00-00:01.5",
  "action_performance": "动作、姿态、表情与必要的预备/惯性",
  "camera": "景别与镜头运动",
  "spatial": "人物、道具和固定地标的位置",
  "audio": "声音线索或 silent",
  "handoff": "本段结束时交给下一段的确定状态"
}
```

`director_timeline` 与 `acts[]` 使用同一时间边界，避免两套时间线互相冲突。普通镜头使用 `risk_level: standard`，允许不写 `director_timeline`。

## 6. hook

每条 `shots[]` 必须包含：

```json
{
  "hook": {
    "type": "reveal",
    "payoff": "四只狼共享同一枚影核",
    "next_hook": "牌楼之后是谁在呼唤陆烬"
  }
}
```

`type` 只能是：`setup`、`visual-joke`、`reversal`、`reveal`、`callback`、`suspense`、`tender`、`chase`、`expression-beat`、`climax`。Hook 必须来自剧情，不为了满足密度凭空添加新事件。

## 校验边界

- Schema 2.6 强制执行本文件；2.2/2.3/2.4/2.5 旧文件保持兼容。
- 每个角色必须有 `identity_lock`；每个场景必须有 `landmarks` 与 `lighting_baseline`。
- 每镜必须有 `hook` 和 `risk_level`。
- `high` 镜头必须有覆盖全时长的 `director_timeline`，且每幕必须有完整 `performance`。
- 角色从下一镜消失时，上一镜必须有该角色的 `exit_state`；只写 `<ID>.status` 不再足够。
