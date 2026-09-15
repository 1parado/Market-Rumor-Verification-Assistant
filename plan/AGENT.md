# AGENT.md — 核真 Veritas · 项目设计目标与约束

> 本文件是「核真 Veritas · 市场传闻核查助手」项目级的**最高约束**，记录设计目标、硬性约束、架构方向与关键决策。
> 与 `frontend/AGENT.md`（前端视觉与交互准则）互补：本文件管「做什么、用什么、怎么拆」，前端文件管「怎么画、怎么交互」。
> 任何后端代码、流水线、模块拆分、部署方案的实现都必须先通过本文件检查；与需求冲突时，先在此修订原则，再动代码。

---

## 一、项目概述

**核真 Veritas** 是一个市场传闻核查助手：用户在 Web 界面转发一条股市传闻，后端 Agent 调用工具（查行情 / 公告 / 资讯）查证，输出「可信 / 存疑 / 无法核实」的判断、依据与数据来源。

- **核查内核**参考 [TradingAgents](https://github.com/TauricResearch/TradingAgents) 的设计方式（分析师分组 → 辩论 → 裁决 + 数据锚定防幻觉）。
- **产品形态**参考 DeepSeek Harness 类工作台（用户自带模型配置的 WebUI），前端已有实现见 `frontend/`（index.html / app.js / styles.css）。
- **交付定位**：同花顺笔试编程题 A，待核查 5 条传闻（见 `编程题A.md` / `编程题A-传闻核查.py`）。

---

## 二、设计目标

### 2.1 功能目标
1. 输入一条股市传闻文本，输出结构化核查结果。
2. 调用三类工具查证：行情（价格 / 涨跌幅 / 日期）、公告、资讯。
3. 判断三分类：**可信 / 存疑 / 无法核实**。
4. 每条结论必须附**依据**与**引用的数据来源**（可复核）。
5. 一条传闻涉及多家公司时，**逐家查证**。
6. 工具数据里查不到的信息，明确标「无法核实」，**禁止编造**。

### 2.2 产品目标
1. WebUI 形态，类似 DeepSeek Harness 工作台（安静、克制、留白充足的 Agent 控制台，详见 `frontend/AGENT.md`）。
2. 用户自带模型配置（URL / Key / 协议），不绑定特定厂商。
3. 支持**模型连通测试**，通过后即可用于核查。
4. 前端可部署到 **GitHub Pages**。

---

## 三、约束条件（硬性）

| # | 约束 | 说明 |
|---|---|---|
| C1 | 包管理 | 本地使用 **uv** 管理 Python 依赖，`pyproject.toml` 为依赖真相源 |
| C2 | 后端语言 | **Python** 编写后端代码 |
| C3 | 单文件行数上限 | **一个代码文件不超过 3000 行**；超过必须按职责拆分 |
| C4 | 产品形态 | WebUI，类似 DeepSeek Harness 工作台 |
| C5 | 部署 | 前端可部署到 **GitHub Pages** |
| C6 | 模型接入 | 用户在前端输入 **URL / Key / 协议** 即可拉取模型 |
| C7 | 协议支持 | 支持 OpenAI 两种协议 + Anthropic 协议（具体指代见 §六.1） |
| C8 | 连通测试 | 支持模型连通测试，通过后才能发起核查 |
| C9 | 核查入口 | 通过该 WebUI 进行市场传闻核查 |

---

## 四、参考：TradingAgents 可借鉴的设计方式

来源：`plan/金融证券交易领域开源 LLM Agent 项目调研笔记.md`（2026-09-15 GitHub 实时数据，TradingAgents 10.6 万★，当天仍有提交）。

1. **分析师分组 → 辩论 → 裁决**流水线（源码 `tradingagents/agents/` 分 `analysts/`、`researchers/`、`managers/`、`risk_mgmt/`、`trader/`）。简化为 **3+1**：行情核查 Agent、公告核查 Agent、资讯核查 Agent + 裁决 Agent。传闻核查天然带「辩论」结构——支持证据 vs 反驳证据。
2. **价格锚定 / 数据快照**（v0.4.0 引入，修复模型张冠李戴/编造价格）：先由工具取回已验证数据快照注入 prompt，LLM 只基于快照做判断。这是核查「禁止编造」约束的核心实现手段。
3. **双模型分工**（`deep_think_llm` / `quick_think_llm`）：复杂推理用强模型，简单任务用快模型，控制成本。
4. **结构化输出**（v0.2.4 起 Research Manager / Trader / Portfolio Manager 均为 Pydantic schema Agent）：核查结果机器可读。
5. **反思日志**（`~/.tradingagents/memory/trading_memory.md`）：每次结果留痕，可改造为「核查历史记录」。
6. **多源 LLM 抽象**：原生支持 OpenAI / DeepSeek / Qwen / GLM 等及任意 OpenAI 兼容端点——契合 C6「用户自带 URL/Key」需求。
7. **框架**：LangGraph 编排 + checkpoint 断点恢复。**本项目采用 LangGraph**（见 §六.3 已确认）。

---

## 五、架构方向（由约束推导）

### 5.1 前后端分离（C5 ↔ C2 的固有限制）

GitHub Pages 只能托管**静态资源**，无法运行 Python 后端。故采用前后端分离：

- **前端**（静态，部署 GitHub Pages）：模型配置面板（URL/Key/协议）、连通测试、核查输入、结果可视化、活动流 / 审批。已有基础见 `frontend/`，工具插件（`get_quote` / `get_announcements` / `get_news`）已对齐题目。
- **后端**（Python + FastAPI，本地 `uv run` 起服务或用户自部署）：核查编排流水线、LLM 调用、数据工具。
- **通信**：前端通过 HTTP 调后端；前端可配置后端 endpoint（默认 `http://localhost:8000`）。
- **Key 流转**：用户 Key 存浏览器 localStorage，调后端时透传；后端用其调 LLM。连通测试走**后端代理**，规避浏览器跨域（CORS）与 Key 直接暴露。

### 5.2 模块划分（满足 C3 单文件 ≤ 3000 行）

参考 TradingAgents 目录结构，后端建议如下拆分，每个文件按职责单一原则控制行数，远低于上限：

```
backend/
  app.py                # FastAPI 入口与路由
  config.py             # 配置加载
  llm/
    client.py           # 统一 LLM 调用（协议适配）
    protocols.py        # OpenAI Chat / Responses / Anthropic 适配
  agents/
    planner.py          # 核查规划（断言分解、公司识别）
    quote_agent.py      # 行情核查
    announce_agent.py   # 公告核查
    news_agent.py       # 资讯核查
    judge.py            # 裁决（辩论汇总）
  tools/
    quote.py            # get_quote
    announcements.py    # get_announcements
    news.py             # get_news
    calculator.py       # 数值计算（LLM 不碰算术，参考 FinRobot/AlphaAnalyst）
  data/
    snapshot.py         # 数据快照 / 锚定
  schemas.py            # Pydantic 结构化输出模型
  pipeline.py           # 流水线编排（分析师 → 辩论 → 裁决）
```

任一文件接近 3000 行即触发拆分；流水线各阶段（规划 / 取证 / 裁决）天然是拆分边界。

### 5.3 数据源
- 笔试交付阶段**仅使用**题目已提供的本地虚构数据（`编程题A-传闻核查.py` 的 `_QUOTES` / `_ANNOUNCEMENTS` / `_NEWS`，已确认）。
- 数据层抽象为统一接口（`get_quote` / `get_announcements` / `get_news`），未来可接 akshare（A 股真实数据）而不动 Agent（参考 OpenBB「connect once, consume everywhere」）。

### 5.4 前端分层（已确认调整）

- **frontend/** — 部署到 GitHub Pages 的**宣传展示页**，用 mock 数据展示产品形态与工作流视觉，不接通真实后端。保留三栏 Agent 控制台视觉，仅供展示。
- **front/** — **真实接通前端**，以 `编程题A-传闻核查.py` 的要求为主。简洁聚焦，不复制宣传页的多栏复杂布局，只包含：① 传闻输入框 ② Agent 流式输出过程（planner → evidence → judge 实时推送）③ 输出结果（可信/存疑/无法核实 + 依据 + 来源）④ 核查报告文档 ⑤ 结果可视化。
- 真实数据接通以 `编程题A-传闻核查.py`（`check_rumor`）要求为准：结构化判断 + 逐条依据 + 数据来源，多家公司逐家查证，查不到明说「无法核实」，禁止编造。
- 后端为 `front/` 提供 SSE 流式接口 `/api/rumor/check/stream`，推送各节点过程；同步接口 `/api/rumor/check` 保留。

---

## 六、关键决策（已确认）

1. **OpenAI 两种协议**：① Chat Completions（`/v1/chat/completions`）② Responses（`/v1/responses`），外加 Anthropic Messages（`/v1/messages`）。`llm/protocols.py` 适配这三套。
2. **部署形态**：前端静态站点部署 GitHub Pages；后端 Python + FastAPI，本地 `uv run` 起服务、用户自部署。前后端分离，前端通过 HTTP 调后端并支持配置后端 endpoint。
3. **框架选型**：采用 **LangGraph** 编排核查流水线（贴合 TradingAgents 设计方式，支持 checkpoint 断点恢复）。
4. **数据源**：笔试交付阶段**仅使用题目本地虚构数据**（`_QUOTES` / `_ANNOUNCEMENTS` / `_NEWS`）；数据层抽象为统一接口，未来可接 akshare。
