# 核真 Veritas 前端（真实接通版）

与 `../frontend/`（GitHub Pages 宣传展示页，mock 数据）不同，本目录是**真实接通后端**的简洁前端，以 `../编程题A-传闻核查.py` 的 `check_rumor` 要求为主。

## 功能（简洁聚焦）

- 模型配置：URL / Key / 协议（OpenAI Chat/Responses/Anthropic）/ 模型 / Temperature，自带、仅存 localStorage
- 连通测试：调 `/api/llm/test`，通过后才能核查
- 传闻输入框 + 5 条样例载入
- **Agent 流式输出过程**：调 `/api/rumor/check/stream`（SSE），实时显示 planner → evidence → judge 各节点过程
- 核查结果：可信 / 存疑 / 无法核实 + 逐条依据 + 数据来源，可视化徽章 + 证据卡
- 核查报告：自动生成 Markdown 文档，可复制

## 跑

1. 起后端：`cd ../backend && uv run uvicorn app:app --port 8000`
2. 打开本目录 `index.html`（直接双击，或 `python -m http.server` 起静态服务）
3. 顶栏确认后端地址（默认 `http://localhost:8000`）→ 填模型配置 → 连通测试 → 输入传闻 → 开始核查

## 三个前端/后端目录分工

| 目录 | 角色 | 数据 |
|---|---|---|
| `frontend/` | GitHub Pages 宣传展示页 | mock |
| `backend/` | Python + FastAPI + LangGraph 核查后端 | 本地虚构数据 |
| `front/` | 本目录，真实接通 backend 的简洁前端 | 真实 |
