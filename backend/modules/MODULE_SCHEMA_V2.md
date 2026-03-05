# OpenKeeper 模组 Schema v2

## 1. 顶层结构

```json
{
  "module_id": "whispering_hollow",
  "module_name": "空镇回声",
  "introduction": "给玩家看的背景简介",
  "opening_narration": "开场第一段叙事",
  "tone": "风格关键词",
  "investigation_principles": ["弱引导原则1", "弱引导原则2"],
  "nodes": [],
  "npcs": [],
  "clues": [],
  "items": [],
  "threat_clock": {},
  "victory_conditions": [],
  "failure_conditions": [],
  "endings": [],
  "keeper_notes": []
}
```

## 2. 字段说明

- `module_id`：英文唯一 ID（推荐 snake_case）。
- `module_name`：展示名（中文）。
- `introduction`：大厅与房间摘要使用。
- `opening_narration`：模组开始时的第一段 Keeper 叙事。
- `tone`：风格约束关键词。
- `investigation_principles`：调查原则（弱引导策略）。
- `nodes`：地点/场景节点集合（核心探索图）。
- `npcs`：关键人物与动机。
- `clues`：线索库（可验证信息）。
- `items`：道具库（有限用途，避免万能钥匙）。
- `threat_clock`：威胁时钟（推进压力）。
- `victory_conditions`：胜利条件文本列表。
- `failure_conditions`：失败条件文本列表。
- `endings`：可触发结局列表。
- `keeper_notes`：仅给 Keeper 的执行提醒。

## 3. 子结构规范

### `nodes[]`

```json
{
  "node_id": "clock_tower",
  "title": "旧钟楼",
  "mood": "金属寒意、回音迟滞",
  "public_signals": ["玩家可直接观察到的征兆"],
  "hidden_truths": ["不应一次性全揭示的真相层"],
  "connected_nodes": ["archive_hall"]
}
```

### `npcs[]`

```json
{
  "npc_id": "sarah_lane",
  "name": "莎拉·莱恩",
  "role": "夜巡警员",
  "public_face": "玩家初见印象",
  "private_motive": "深层动机",
  "pressure_points": ["可用于审问/施压的话题"]
}
```

### `clues[]`

```json
{
  "clue_id": "clue_order_fragment",
  "name": "封控令残页",
  "description": "线索描述（玩家悬停可见）",
  "discovered_at": ["archive_hall"],
  "validates": ["该线索可验证的命题"],
  "ambiguity": "low|medium|high"
}
```

### `items[]`

```json
{
  "item_id": "item_basement_key",
  "name": "地窖钥匙",
  "description": "道具描述",
  "discovered_at": ["clock_tower"],
  "usage_hint": "用途提示（不等于标准答案）"
}
```

### `threat_clock`

```json
{
  "name": "共鸣回潮",
  "max": 6,
  "tick_triggers": ["失败检定", "停留过久"],
  "tick_rules": [
    { "event": "check_failure", "amount": 1, "action_names": ["roll_dice"] },
    { "event": "hp_loss", "amount": 1, "min_loss": 1, "action_names": ["apply_damage"] },
    { "event": "san_loss", "amount": 1, "min_loss": 1, "action_names": ["apply_sanity_change"] },
    { "event": "status_added", "amount": 1, "status_contains": "疯狂", "action_names": ["add_status"] }
  ],
  "stages": [
    { "at": 2, "omen": "异象描述" },
    { "at": 4, "omen": "异象升级" }
  ]
}
```

`tick_rules.event` 可选值：
- `check_failure`：检定失败/大失败。
- `check_fumble`：仅大失败。
- `hp_loss`：生命值损失。
- `san_loss`：理智值损失。
- `status_added`：添加状态（可配 `status_contains` 关键词）。

### `endings[]`

```json
{
  "ending_id": "sealed_truth",
  "title": "封存真相",
  "summary": "结局简述",
  "trigger": "触发条件文本"
}
```

## 4. 编写建议（弱引导风格）

- 每个 `node` 只放 2-4 条 `public_signals`，让玩家自己拼图。
- `hidden_truths` 写“分层信息”，不要单条全剧透。
- `clues.ambiguity` 至少保留 30% `high`，避免直白破案。
- `threat_clock` 要和玩家犹豫成本挂钩，否则不会有压迫感。
- `endings.trigger` 用“状态+行为”描述，避免纯剧情句。

## 5. 节省 Token 的设计建议

- `nodes` 控制在 4-8 个；每个节点只保留必要信号，避免长篇背景。
- `clues.description` 尽量 1-2 句，`validates` 使用短命题。
- `npcs` 只保留会参与对抗或信息交换的人物（3-6 个）。
- `keeper_notes` 保持 3-5 条高价值原则，不写重复规则。
- 将大段世界观放到外部策划文档，不放进 JSON。
- 运行时会给 Keeper 发送“焦点信息包”，不是整本模组；所以请把每条线索写成可独立理解的最小单元。

## 6. 最小可运行检查清单

- 顶层关键字段全部存在（`module_id/module_name/opening_narration/threat_clock/endings`）。
- 至少 3 个 `nodes`、2 个 `npcs`、3 条 `clues`、2 个 `items`。
- `threat_clock.max >= 4` 且 `stages` 至少 2 段。
- `endings` 至少 2 个，且 `ending_id` 唯一。
