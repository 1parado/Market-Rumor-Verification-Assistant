# PRD · 核真 Veritas 市场传闻核查助手

> 版本：MVP v0.1 · 日期：2026-09-15
> 上游约束：`plan/AGENT.md`（项目设计目标与约束，已确认决策见 §六）
> 本文件定义 MVP 的范围、接口契约、核查流水线与数据结构；超出 MVP 的能力列入 §10 迭代路线。

---

## 1. 概述

核真 Veritas 是一个股市传闻核查助手。用户在 WebUI 转发一条传闻，后端用 LangGraph 编排核查流水线，调用行情 / 公告 / 资讯工具查证，输出「可信 / 存疑 / 无法核实」的判断、依据与数据来源。

MVP 目标：**跑通「输入一条传闻 → 输出结构化核查结果」的核心链路**，并支持用户自带模型配置（URL / Key / 协议）与连通测试。前端复用已有 `frontend/`，本 PRD 仅覆盖后端 `backend/`。

## 2. MVP 范围

### 2.1 包含（In Scope）
- 三协议 LLM 调用：OpenAI Chat Completions、OpenAI Responses、Anthropic Messages。
- 模型连通测试接口。
- 5 条待核查传闻的查询接口（读本地虚构数据）。
- 核查流水线：规划（识别公司 + 分解断言）→ 取证（调三个工具，形成数据快照）→ 裁决（逐条核查 + 汇总判断）。
- 三个工具基于题目本地虚构数据：`get_quote` / `get_announcements` / `get_news`。
- 结构化 JSON 输出：判断 + 依据 + 数据来源。
- 防幻觉约束：所有数值 / 事件结论必须锚定工具返回的数据快照，查不到明说「无法核实」，禁止编造。

### 2.2 不包含（Out of Scope，留待迭代）
- 多空辩论节点（TradingAgents 式 max_debate_rounds）。
- 真实 A 股数据源接入（akshare / tushare）。
- 反思日志持久化、checkpoint 断点恢复的人机交互。
- 前端代码改动（MVP 阶段后端先自测，前端接通为下一迭代）。
- 鉴权 / 多用户 / 数据库。

## 3. 用户故事

1. 作为用户，我填入 URL / Key / 协议 / 模型名，点「连通测试」，看到成功 / 失败与原因，确认模型可用。
2. 作为用户，我输入一条传闻文本（或从 5 条样例选一条），点「核查」，得到结构化结果：判断（可信 / 存疑 / 无法核实）+ 每条断言的依据 + 引用的数据来源。
3. 作为用户，传闻涉及多家公司时，结果里每家公司都被单独查证，不遗漏。

## 4. 功能需求

| ID | 需求 | 优先级 |
|----|------|--------|
| FR1 | 提供 LLM 连通测试接口，用用户配置发起一次最小调用并返回状态 | P0 |
| FR2 | 提供待核查传闻列表接口（5 条，来自本地数据） | P0 |
| FR3 | 提供核查接口，入参为传闻文本 + LLM 配置，出参为结构化核查结果 | P0 |
| FR4 | 核查流程须识别传闻涉及的全部公司（含间接指代，如「上个月上市的储能新股」） | P0 |
| FR5 | 核查流程须把传闻分解为可核查的原子断言（价格 / 事件 / 传播） | P0 |
| FR6 | 每条断言须调对应工具取证，数值类断言锚定行情快照，事件类锚定公告 / 资讯 | P0 |
| FR7 | 输出三分类判断 + 逐条依据 + 数据来源引用 | P0 |
| FR8 | 数据中查不到的信息须标记「无法核实」，不得编造 | P0 |

## 5. 接口契约（HTTP / JSON）

所有接口前缀 `/api`。请求 / 响应均为 JSON。LLM 配置由前端每次随请求传入（后端不落盘 Key）。

### 5.1 LLM 配置（请求体内嵌）

```
LLMConfig {
  base_url:   string   // 如 https://api.openai.com/v1
  api_key:    string
  protocol:   "openai_chat" | "openai_responses" | "anthropic"
  model:      string   // 如 gpt-4o、claude-...、deepseek-chat
  temperature?: number // 默认 0（可复现优先）
}
```

### 5.2 POST /api/llm/test —— 连通测试
- 请求：`{ llm: LLMConfig }`
- 响应 200：`{ ok: true, model: "...", reply: "..." }`
- 响应 4xx/5xx：`{ ok: false, error: "...", detail: "..." }`
- 行为：用给定配置发起一次「ping」调用（如 `reply "ok"`），验证可达 + 鉴权 + 协议正确。

### 5.3 GET /api/rumors —— 待核查传闻列表
- 响应 200：`{ rumors: [{ id: 1, text: "..." }, ...] }`
- 数据来源：本地虚构数据（5 条）。

### 5.4 POST /api/rumor/check —— 核查传闻
- 请求：`{ rumor_text: string, llm: LLMConfig }`
- 响应 200：`RumorCheckResult`（见 §7）
- 响应 5xx：`{ error: "...", detail: "..." }`
- 行为：同步执行核查流水线，返回完整结构化结果。

### 5.5 GET /api/health —— 健康检查
- 响应 200：`{ status: "ok" }`

## 6. 核查流水线设计（LangGraph）

参考 TradingAgents「分析师分组 → 裁决」简化为三节点直线流水线（辩论节点留待迭代）。状态对象 `CheckState` 在节点间传递。

```
[planner] ──> [evidence] ──> [judge] ──> END
```

### 6.1 CheckState（流水线状态）
- `rumor_text: str`
- `llm_config: LLMConfig`
- `companies: list[CompanyRef]`（planner 产出）
- `claims: list[Claim]`（planner 产出，原子断言）
- `snapshot: dict`（evidence 产出，按公司聚合的行情/公告/资讯原始数据）
- `verifications: list[Verification]`（judge 产出，逐条断言核查）
- `result: RumorCheckResult | None`（judge 产出最终汇总）

### 6.2 节点职责
1. **planner（规划）**：调 LLM，从传闻中识别涉及的公司（含间接指代，需在 prompt 里提供候选公司清单辅助消歧）+ 分解为原子断言（标注断言类型：price / event / spread + 涉及公司 + 期望值/事件描述）。输出结构化 JSON。
2. **evidence（取证）**：对每个识别出的公司，调用 `get_quote` / `get_announcements` / `get_news`，聚合为数据快照。**纯工具调用，不调 LLM，不做算术之外的推断**（参考 FinRobot/AlphaAnalyst）。
3. **judge（裁决）**：把数据快照 + 断言注入 prompt，调 LLM 逐条判断 支持 / 反驳 / 无法证实，并给出依据（引用快照中的字段值或公告/资讯原文片段）与数据来源；再汇总为整体判断（可信 / 存疑 / 无法核实）。**所有数值引用只能来自快照**（TradingAgents 价格锚定）。

### 6.3 判断三分类映射规则（裁决输出）
- **可信（credible）**：传闻的各原子断言均被工具数据支持。
- **存疑（questionable）**：部分断言被支持、部分被反驳，或数据与传闻存在出入（含「传闻与公告相反」这类被反驳情形）。
- **无法核实（unverifiable）**：相关数据完全缺失（工具返回空 / 公司查无）。
- 依据须为结构化条目，每条引用具体数据来源（quote / announcement / news + 字段或原文片段）。

## 7. 数据结构（Pydantic，见 backend/schemas.py）

```
CompanyRef { name: str, code: str | None }

ClaimType = "price" | "event" | "spread"
Claim { id: str, text: str, company: str, type: ClaimType,
        expected: str | None }   # 期望值/事件描述

EvidenceSource = "quote" | "announcement" | "news"
Evidence { company: str, source: EvidenceSource, payload: dict }

Verdict = "supports" | "refutes" | "unverifiable"
Verification { claim_id: str, verdict: Verdict, reasoning: str,
               source: EvidenceSource | None, source_ref: str | None }

FinalVerdict = "credible" | "questionable" | "unverifiable"
RumorCheckResult {
  rumor_text: str,
  companies: list[CompanyRef],
  claims: list[Claim],
  verifications: list[Verification],
  final_verdict: FinalVerdict,
  basis: str,                  # 给人看的综合依据
  sources: list[str],          # 引用的数据来源标识
  data_date: str | None        # 快照日期
}
```

## 8. LLM 协议适配（见 backend/llm/protocols.py）

统一入口 `call_llm(messages, tools, llm_config) -> message`，按 `protocol` 分发：

| protocol | 端点 | 请求体特征 | 工具调用字段 |
|---|---|---|---|
| openai_chat | `{base_url}/chat/completions` | `{model, messages, tools, temperature}` | `message.tool_calls` |
| openai_responses | `{base_url}/responses` | `{model, input, tools, temperature}` | `output[].tool_calls` |
| anthropic | `{base_url}/messages` | `{model, messages, tools, system, max_tokens}` | `content[].type=="tool_use"` |

- base_url 归一化：openai 协议去掉末尾 `/`；anthropic 用 `{base_url}/v1/messages` 形式（兼容用户填 `/v1` 或完整 URL）。
- 错误统一抛 `LLMError(status, detail)`，由路由层转 HTTP。
- MVP 阶段 tool calling 在 planner / judge 节点按需使用；evidence 节点不调 LLM。

## 9. 非功能需求

- **代码规范**：单文件不超过 3000 行（AGENT.md C3），超则按职责拆分；类型注解齐全；模块按 §五.2 划分。
- **依赖管理**：`pyproject.toml` 为真相源，`uv sync` 可装；不提交 Key。
- **可复现**：默认 `temperature=0`。
- **可运行**：`uv run uvicorn app:app --reload` 能起，`GET /api/health` 返回 ok。
- **交付物**：可运行代码 + README（怎么跑 / 设计思路 / 已知缺陷）+ AI 协作过程记录。

## 10. 迭代路线（MVP 之后）

1. 接通前端 `frontend/`（模型配置面板 / 连通测试 / 核查入口 / 结果可视化）。
2. 引入辩论节点：支持方 vs 质疑方多轮辩论后裁决（TradingAgents 式）。
3. 反思日志：核查历史落盘 + 下次同主题注入。
4. 真实数据源：数据层接 akshare，多源降级。
5. checkpoint 断点恢复与人工审批（对齐 `frontend/AGENT.md` 的 Approval Queue）。
6. 双模型分工（deep_think / quick_think）控成本。
