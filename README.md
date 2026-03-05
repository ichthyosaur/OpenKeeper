# OpenKeeper

面向 TRPG 的 Keeper/GM Agent 系统。

## 功能概览
- LLM 作为 Keeper，输出 JSON 并通过 actions 驱动状态
- 1920s 经典规则（CoC 7e）判定：常规/困难/极难 + 奖励/惩罚骰
- 角色与模组管理，结局由 Keeper 触发

## 环境要求
- Python 3.9+
- MongoDB

## Python 环境构建
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r backend/requirements.txt
```

## 配置
编辑 `backend/config.yaml`：
```yaml
mongo_uri: "mongodb://localhost:27017"
mongo_db: "openkeeper"
api_key: "你的APIKey"
base_url: "你的OpenAI兼容地址"
model: "你的模型名"
history_count: 100
max_followups: 5
stream_cps: 50
temperature: 0.7
llm_parse_retries: 3
```

## 启动服务
```bash
source .venv/bin/activate
python backend/run.py
```

访问：
- 玩家页面：`http://localhost:8000/player`
- Host 页面：`http://localhost:8000/host`

## 游玩流程
1. Host 页面选择模组并开始
2. 玩家页面创建或选择角色进入游戏
3. 玩家输入行动，Keeper 会自动叙事与判定输出

## 玩家指南（PLAYER）

### 1. 怎么开始
1. 打开玩家页面：`http://localhost:8000/player`
2. 创建新角色，或选择已有角色
3. 点击进入房间，等待主持人开局

### 2. 你在页面上会看到什么
- `历史记录`：故事正文、你的行动、判定结果
- `角色卡`：生命、理智、技能
- `判定面板`：最近一次检定
- `推进与代价`：这回合你获得了什么信息、付出了什么代价
- `异兆与症状`：当前不安征兆与角色精神状态
- `调查笔记本`：手记、线索、随身物

### 3. 如何行动
- 直接输入一句行动并发送，例如：
  - “检查钟楼入口地面的拖痕”
  - “试探看守者是否在隐瞒什么”
- 支持回车发送，方向键上/下可找回上一条输入

### 4. 快捷行动怎么用
- 你可以切换按钮页签：
  - `建议`：系统给你的推荐后续动作
  - `调查`：找痕迹、看细节、搜证据
  - `交涉`：询问、试探、施压
  - `求生`：撤离、警戒、控风险
  - `神秘`：符号、异象、仪式相关
- 点击按钮可直接发送

### 5. 风险档位（很关键）
- 每次行动前可选：
  - `保守`：更稳，推进慢
  - `标准`：默认节奏
  - `冒险`：推进快，但代价可能更重
- 这会直接影响你的游戏体验，建议按局势随时切换

### 6. CoC 感的核心体验
- 失败不等于白做：你通常仍会拿到信息，但代价会上升
- 异兆会递进：你会逐步感到环境变得更“不对劲”
- 理智会反噬行为：某些精神症状会限制你的行动选择
- 结局不是单纯胜负：常见是“活下来了但失去真相”或“知道真相但付出巨大代价”

### 7. 为什么我现在不能发送行动
- 可能是以下情况：
  - 主持人还没开局
  - 你的角色已无法继续行动
  - 叙事正在播放中，请稍等几秒再发

## 主持人指南（HOST）

### 开局步骤
1. 打开主持页面：`http://localhost:8000/host`
2. 选择模组并开始
3. 确认玩家已进入房间，再推进第一段叙事
4. 剩下全部交给Keeper吧！
