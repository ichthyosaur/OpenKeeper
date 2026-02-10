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
