# helloTravel

智能旅行助手基础工程骨架，采用前后端分离架构。

## 技术架构

- 前端层：Vue 3 + TypeScript，负责表单输入、结果展示、地图可视化。
- 后端层：FastAPI，负责 API 路由、数据验证、业务逻辑编排。
- 智能体层：HelloAgents，负责景点搜索、天气查询、酒店推荐、行程规划。
- 外部服务层：高德地图 API、Unsplash API、LLM API。

## 目录结构

```text
helloTravel/
├── backend/
│   ├── app/
│   │   ├── agents/
│   │   ├── api/
│   │   ├── models/
│   │   ├── services/
│   │   ├── config.py
│   │   └── main.py
│   └── requirements.txt
└── frontend/
    ├── src/
    │   ├── views/
    │   ├── services/
    │   ├── types/
    │   ├── router/
    │   ├── App.vue
    │   └── main.ts
    └── package.json
```

## 本地运行

后端：

```bash
cd backend
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

前端：

```bash
cd frontend
npm install
npm run dev -- --host 127.0.0.1
```

前端默认访问 `http://127.0.0.1:5173/`，API 代理到 `http://127.0.0.1:8000/`。

## Agent 协作设计

多 Agent 角色划分、提示词、工具调用格式和协作流程见：

[docs/agent_design.md](docs/agent_design.md)

高德地图 MCP 集成、共享 MCP 实例和工具调用流程见：

[docs/amap_mcp_integration.md](docs/amap_mcp_integration.md)
