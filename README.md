# 核真 Veritas · 市场传闻核查助手

用户转发一条股市传闻，Agent 调用行情/公告/资讯工具查证，输出「可信 / 存疑 / 无法核实」的判断、依据与数据来源。

## 技术栈

- **后端**：Python · FastAPI · LangGraph（planner → evidence → judge 三节点流水线）
- **LLM 接入**：自写三协议适配（OpenAI Chat Completions / Responses / Anthropic），用户自带 URL/Key
- **前端（真实接通）**：原生 HTML/CSS/JS，SSE 流式展示 Agent 过程
- **前端（宣传展示）**：静态页，部署 GitHub Pages，mock 数据
- **数据**：题目本地虚构数据（A 股场景）

## 目录

| 目录 | 说明 |
|---|---|
| `backend/` | FastAPI + LangGraph 核查后端（含 SSE 流式接口）|
| `front/` | 真实接通前端（输入 + 流式过程 + 结果 + 报告）|
| `frontend/` | GitHub Pages 宣传展示页（mock）|
| `plan/` | AGENT.md 设计约束 · PRD · 开源项目调研笔记 |

## 运行

```bash
cd backend
uv sync
uv run uvicorn app:app --port 8000
# 打开 front/index.html，填模型配置 → 连通测试 → 输入传闻 → 核查
```
