# 核真 Veritas 后端

市场传闻核查助手后端（MVP v0.1）。设计与约束见 `../plan/AGENT.md`，需求见 `../plan/PRD.md`。

## 怎么跑

```bash
cd backend
uv sync                                   # 安装依赖
uv run uvicorn app:app --reload --port 8000
```

访问 `http://localhost:8000/api/health` 返回 `{"status":"ok"}` 即可。

### 接口

| 方法 | 路径 | 入参 | 出参 |
|---|---|---|---|
| GET | /api/health | — | `{status:"ok"}` |
| GET | /api/rumors | — | `{rumors:[{id,text}]}`（5 条） |
| POST | /api/llm/test | `{llm:LLMConfig}` | `LLMTestResult` |
| POST | /api/rumor/check | `{rumor_text, llm:LLMConfig}` | `RumorCheckResult` |

`LLMConfig = {base_url, api_key, protocol: "openai_chat"|"openai_responses"|"anthropic", model, temperature?}`

### 调用示例

```bash
curl -X POST http://localhost:8000/api/rumor/check \
  -H "Content-Type: application/json" \
  -d '{"rumor_text":"听说恒润科技昨天涨停了，是不是有大资金进场？",
       "llm":{"base_url":"https://api.openai.com/v1","api_key":"sk-xxx",
              "protocol":"openai_chat","model":"gpt-4o"}}'
```

## 设计思路

- **LangGraph 三节点流水线**（`pipeline.py`）：`planner`（识别公司 + 分解原子断言）→ `evidence`（对每家公司调行情/公告/资讯工具，聚合数据快照）→ `judge`（基于快照逐条核查 + 汇总三分类判断）。
- **数据锚定防幻觉**（参考 TradingAgents v0.4.0）：`evidence` 取回的快照注入 `judge` prompt，模型所有数值引用只能来自快照，查不到标「无法核实」。
- **LLM 不碰算术**（参考 FinRobot/AlphaAnalyst）：数值判断走 `tools/calculator.py`，模型不做算术。
- **自写三协议适配**（`llm/protocols.py`）：统一中间消息格式 → 转换到 Chat Completions / Responses / Anthropic 原生请求体，响应归一化为 `ChatResponse`。用户自带 URL/Key，后端不落盘。
- **数据层抽象**：`tools/*` + `data/local_data.py` 统一接口，MVP 用题目虚构数据，未来可接 akshare 不动 Agent。
- **模块拆分**：单文件均远低于 3000 行上限，按 `llm/`、`agents/`、`tools/`、`data/` 分层。

## 已知缺陷

- **Responses 协议**：部分第三方 OpenAI 兼容端点未实现 `/responses`，仅支持 `/chat/completions`。
- **tool_choice 强制调用**：少数模型可能不遵守强制工具调用；`judge` 已对「未返回结构化结果」做兜底（标 unverifiable）。
- **连通测试**：返回 `200 + ok=false`（语义化），与 PRD §5.2 的 4xx/5xx 表述略有偏差。
- **安全**：无鉴权、CORS 全开（MVP，前端自带 Key，上线前需收紧 allow_origins）。
- **确定性**：`temperature=0` 仍不保证 LLM 输出完全可复现。
- **暂未接前端**：MVP 阶段后端自测，前端 `frontend/` 接通为下一迭代。
