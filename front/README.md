# 核真 Veritas 前端（真实接通版 · Vue 3 + Vite）

与 `../frontend/`（GitHub Pages 宣传展示页，mock 数据）不同，本目录是**真实接通后端**的前端，以 `../编程题A-传闻核查.py` 的 `check_rumor` 要求为主。技术栈：**Vue 3（`<script setup>`）+ Vite**。

## 功能（简洁聚焦）

- 首页极简：居中「准备开始核查？」+ 胶囊输入（粘贴剪贴板 / 圆形提交），回车即核查
- 设置弹窗（⚙）：协议（OpenAI Chat/Responses/Anthropic）/ 后端地址 / Base URL / 模型（支持拉取模型列表）/ API Key，仅存 localStorage
- 连通测试：调 `/api/llm/test`
- **Agent 流式过程**：调 `/api/rumor/check/stream`（SSE），实时显示 planner → evidence → judge 各节点
- 核查结果：可信 / 存疑 / 无法核实 + 逐条依据 + 数据来源，徽章 + 证据卡
- 核查报告：自动生成 Markdown，一键复制
- IM 入口（💬）：飞书接入预留

## 跑

```bash
# 1. 起后端
cd ../backend && uv run uvicorn app:app --port 8000

# 2. 起前端（Vite dev server，/api 自动代理到 localhost:8000）
cd front
npm install
npm run dev        # 打开 http://localhost:5173

# 生产构建
npm run build      # 产物在 dist/
npm run preview    # 本地预览构建产物
```

设置里「后端地址」默认 `http://localhost:8000`；dev 模式下可留空走 Vite 代理（同源免 CORS）。

## 结构

```
front/
├── index.html              # Vite 入口
├── vite.config.js          # /api 代理 → localhost:8000
├── public/icon.png         # 图标
└── src/
    ├── main.js             # 挂载入口
    ├── style.css           # 全局样式（安静克制，同 AGENT.md token）
    ├── api.js              # 配置存取 + API/SSE 封装
    ├── App.vue             # 首页 + 工作视图 + 核查流程编排
    └── components/
        ├── SettingsModal.vue   # 模型配置弹窗（含拉取模型）
        └── ImModal.vue         # IM（飞书）接入预留
```

## 三个前端/后端目录分工

| 目录 | 角色 | 数据 |
|---|---|---|
| `frontend/` | GitHub Pages 宣传展示页 | mock |
| `backend/` | Python + FastAPI + LangGraph 核查后端 | 本地虚构数据 |
| `front/` | 本目录，真实接通 backend 的前端（Vue 3 + Vite） | 真实 |
