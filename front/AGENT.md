# front/ — 核真 Veritas 真实前端（Vue 3 + Vite）

> 本目录是连接真实后端（`backend/`，FastAPI）的正式前端，**完全基于 Vue 3 + Vite 实现**。
> `frontend/` 目录是 GitHub Pages 宣传页（含 mock 演示），与本目录无关；其设计规范见 `frontend/AGENT.md`。

## 技术栈

- **Vue 3**（`<script setup>` Composition API，无 class 组件、无额外状态库）
- **Vite 6** + `@vitejs/plugin-vue`；dev 代理 `/api → http://localhost:8000`
- 原生 `fetch` + `ReadableStream` 消费 SSE（POST 流式）
- 样式：全局 `src/style.css` + CSS 变量设计令牌（延续 frontend/AGENT.md 的低噪音规范）

## 运行

```bash
cd front
npm install
npm run dev      # http://localhost:5173（需后端已启动：uv run uvicorn app:app --port 8000）
npm run build    # 产物 dist/
```

## 目录结构

```
front/
├── index.html                  # Vite 入口
├── vite.config.js              # vue 插件 + /api 代理
└── src/
    ├── main.js                 # createApp 挂载
    ├── App.vue                 # 壳：顶栏 / 首页 / 工作视图；持有唯一 cfg 数据源
    ├── api.js                  # fetch 封装：SSE 流式、configs、runs、chat API
    ├── style.css               # 设计令牌 + 全部样式
    └── components/
        ├── SettingsModal.vue   # 模型配置弹窗
        ├── HistoryModal.vue    # 历史核查记录弹窗
        └── ImModal.vue         # IM（飞书）接入占位
```

## 关键设计决策

### 1. 配置单一数据源（踩过的坑）

`cfg` 只在 `App.vue` 中创建一次（`ref(loadCfg())`），通过 prop 传给 `SettingsModal`
**直接变更**。禁止在弹窗里再 `loadCfg()` 复制一份独立状态 —— 曾因此出现
「弹窗保存后，App 点开始核查用旧配置反向覆盖 localStorage」导致配置丢失。
任何请求发出前以 `cfg.value` 为准。

### 2. 双层配置持久化

| 层 | 写入时机 | 用途 |
|----|----------|------|
| localStorage（`veritas.config`） | 弹窗字段变动即自动保存（deep watch） | 刷新/重开页面不丢 |
| 后端 SQLite（`model_configs` 表） | 点「保存配置」按钮，按名称 upsert | 多配置管理、换机复用 |

后端地址（`baseUrl`）不暴露给用户：恒为空字符串 = 同源（dev 走 Vite 代理）。
`loadCfg()` 会强制删除历史存储的 `baseUrl`。

### 3. SSE 事件契约（`POST /api/rumor/check/stream`）

事件流：`start`（含 `run_id`）→ `node`（planner/evidence/judge）→ `done`（含 result）或 `error`。
`start` 的 `run_id` 是后续「会话追问」「历史回放」的钥匙。

### 4. SQLite 持久化（后端 `storage.py`，stdlib sqlite3）

| 表 | 内容 |
|----|------|
| `model_configs` | 模型配置（名称唯一 upsert；含 api_key，**db 文件已 gitignore**） |
| `runs` | 每次核查：传闻、状态、结论、完整 result JSON、报告 Markdown |
| `run_events` | SSE 事件逐条落库 → 支持过程回放 |
| `messages` | 用户 ↔ Agent 会话（挂在 run 下，带上下文追问） |

对应 REST API：
- `GET/POST /api/configs`、`DELETE /api/configs/{id}`
- `GET /api/runs`、`GET /api/runs/{id}`（含 events + messages）、`DELETE /api/runs/{id}`
- `POST /api/runs/{id}/chat`（服务端基于核查结果组装 system 上下文，回复落库）
- 流式核查全程自动落库，前端无需单独上报

### 5. 历史回放

`HistoryModal` 列出 runs → 点击 → `GET /api/runs/{id}` →
用 events 重建过程日志、result 重建结果卡、messages 重建会话，进入只读回放态（可继续追问）。

## LLM 配置校验

后端 `llm/client.py::_validate` 在调用前检查 api_key / base_url / model 非空，
空 Key 返回语义化错误（HTTP 400 / SSE error 事件），而不是 httpx 的
`Illegal header value b'Bearer '` 裸异常。

## 视觉规范

沿用 `frontend/AGENT.md` 的设计令牌与低噪音原则：中性灰为主、1px 边框替代阴影
（弹窗/胶囊输入除外）、每屏 ≤1 个实心主按钮、过渡 150–200ms。
