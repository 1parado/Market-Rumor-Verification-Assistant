金融/证券/交易领域开源 LLM Agent 项目调研笔记
调研日期：2026-09-15 调研目的：为「股市传闻核查助手」（Python，A 股场景，Agent 调用行情/公告/资讯工具核查传闻并输出判断）寻找可借鉴的架构与做法。 调研方式：GitHub 仓库 README 抓取 + GitHub API（star/fork/最近 push 时间均为 2026-09-15 实时数据）+ 官网/PyPI 抓取。所有 star 数与维护状态来自 GitHub API；功能描述来自各项目 README 原文。

一、逐项目调研
1. TradingAgents（TauricResearch/TradingAgents）
来源：https://github.com/TauricResearch/TradingAgents （star/fork 等来自 GitHub API）
基本数据：106,376 stars / 20,339 forks / 343 open issues；创建于 2024-12-28；最近 push 2026-09-15（非常活跃，当天仍有提交）；Python；Apache-2.0；配套论文 arXiv:2412.20138。

项目定位与功能：多 Agent LLM 交易研究框架，"mirrors the dynamics of real-world trading firms"——模拟真实交易公司组织架构，部署分析师、研究员、交易员、风控团队协作评估市场并做交易决策，仅供研究用途。

技术栈：

语言：Python 3.12
Agent 框架：LangGraph（README 明确 "We built TradingAgents with LangGraph to ensure flexibility and modularity"），支持 checkpoint 断点恢复
LLM 接入：极广，OpenAI/Anthropic/Gemini/Grok/DeepSeek/Qwen（DashScope 双端点）/GLM（智谱）/MiniMax/Kimi/OpenRouter/Groq/Bedrock/Ollama 等，以及任意 OpenAI 兼容端点（vLLM、LM Studio、llama.cpp）
数据源：Yahoo Finance（覆盖任意市场，含 A 股 600519.SS）、Alpha Vantage、FRED 宏观、Polymarket、新闻头条、StockTwits、Reddit。代码中 dataflows/ 目录有独立模块：y_finance.py、alpha_vantage_*.py、fred.py、polymarket.py、reddit.py、stocktwits.py、yfinance_news.py，还有 market_data_validator.py（数据校验器）
架构特点（源码目录 tradingagents/agents/ 分为 analysts/、researchers/、managers/、risk_mgmt/、trader/）：

分析师团队：基本面（财务指标/内在价值/风险信号）、情绪（新闻+StockTwits+Reddit 聚合）、新闻（全球新闻+宏观指标）、技术分析师（MACD/RSI 等指标）
研究员辩论：多空双方通过 structured debates 辩论，max_debate_rounds 可配置多轮
交易员 → 风控团队（波动率/流动性）→ 组合经理（最终批准/否决）
双模型分工：deep_think_llm（复杂推理）与 quick_think_llm（快速任务）
结构化输出：v0.2.4 起 Research Manager、Trader、Portfolio Manager 均为结构化输出 Agent（Pydantic schema）
反思机制：每次运行结果追加到 ~/.tradingagents/memory/trading_memory.md，下次运行同 ticker 时取回实际收益（含相对 SPY 的 alpha），生成反思段落注入 PM 提示词
防幻觉设计（对传闻核查最有参考价值）：v0.4.0 引入「价格锚定」——公司身份从 ticker 确定性解析，市场分析师将价格声明锚定在已验证的数据快照上，修复了模型张冠李戴或编造价格的问题；v0.3.1 修复 Alpha Vantage 前视偏差（look-ahead bias），v0.4.0 做时点（point-in-time）数据修复
优势：金融多 Agent 框架中星标最高、架构最完整清晰；LLM 供应商抽象彻底；工程化程度高（Docker、CLI、checkpoint、配置系统齐全）；把「防幻觉/数据锚定」当作正式 issue 修，说明团队重视正确性。 劣势：偏「交易决策」，不是「事实核查」；输出是投资判断而非证据链；数据源以美股为主（A 股仅 Yahoo 日线可用）；LLM 非确定性（README 自己承认需要 temperature=0 且仍不保证可复现）。 可借鉴点：① 分析师分组→辩论→裁决的流水线结构可直接映射为「行情核查→公告核查→资讯核查→综合裁决」；② 多空辩论机制改为「支持方 vs 质疑方」辩论来判断传闻真伪；③ 价格锚定/数据快照做法：先由工具取回权威数据快照，再让 LLM 只基于快照做判断；④ 反思/决策日志（trading_memory.md）可改造为「核查历史记录」；⑤ 双模型分工省钱。

2. FinRobot（AI4Finance-Foundation/FinRobot）
来源：https://github.com/AI4Finance-Foundation/FinRobot
基本数据：7,992 stars / 1,354 forks / 75 open issues；创建于 2024-02-27；最近 push 2026-09-11（活跃）；主语言 Jupyter Notebook（实际是 Python 全栈项目）；Apache-2.0；白皮书 arXiv:2405.14767。

项目定位：开源金融 AI Agent 平台，定位为超越 FinGPT 单模型方案的「全栈」平台（LLM + RL + 量化分析），用于投资研究自动化、算法交易策略、风险评估。已发展出商业版 FinRobot Pro（finrobot.ai）。

技术栈：

Python 后端（FastAPI、SQLite）+ React 19/Vite 6/Tauri 桌面端，约 18.4 万行
Agent 框架经历三代：V0 用 AutoGen（仓库内的多 Agent 版本）→ V1 用 OpenAI Agents SDK（finrobot_equity，开源）→ V2 用 PydanticAI（线上版，未开源）→ V3 DeepSeek-Harness（开发中）
数据源：7 个带自动故障转移的提供商——FMP、Finnhub、yfinance、SEC EDGAR、Adanos（零售情绪）、NewsAggregator、FX；含 FinNLP 子模块
架构特点：

四层框架：金融 AI Agent 层（含金融思维链 CoT 提示）→ 金融 LLM 算子层 → LLMOps/DataOps 层 → 多源 LLM 基础模型层
Agent 工作流三段式：Perception（解析多模态金融数据）→ Brain（LLM + 金融 CoT 生成结构化指令）→ Action（执行/报告/告警）
Desktop 版 9 Agent 编排：1 个 Lead Agent 负责路由编排 + 5 个角色子 Agent（数据→分析→建模→综合→报告流水线）+ 3 个辩论 Agent（多头↔空头→裁判）；7 条分析流水线（公司研究、DCF、可比公司、LBO、DDM、财报、IC 备忘录）
核心设计原则（README 原文，对核查助手极重要）："strict separation between deterministic financial computation and LLM-based narration"——所有财务数字由纯 Python 算子计算（30 个算子 + 7 个协调器），LLM 只做推理、综合、解释、撰写。"Numbers are code-calculated."
结构化输出：13 章研究报告、IC 备忘录、证据链接、数值溯源、CSV 中间产物、多页 HTML/PDF
优势：「确定性计算与 LLM 叙述严格分离」原则成熟；报告质量高（证据链接+数值溯源）；数据源故障转移设计好；从开源到商业化的路径验证了架构。 劣势：仓库主体停留在 AutoGen V0 时代，最新架构（V2/V3）不开源；代码以 notebook 教程为主，工程可用性一般；数据中心在美股。 可借鉴点：① 「数字由代码计算，LLM 不碰算术」——核查助手里涨跌幅、市盈率对比等数值应从 akshare 返回值直接取，不让 LLM 算；② 数据源自动故障转移（多 provider 降级，A 股可用 akshare→东财→新浪降级）；③ Lead Agent 路由 + 专项子 Agent 的「编排者-执行者」模式；④ 报告的证据链接与数值溯源字段设计。

3. FinGPT（AI4Finance-Foundation/FinGPT）
来源：https://github.com/AI4Finance-Foundation/FinGPT
基本数据：21,250 stars / 3,013 forks / 52 open issues；创建于 2023-02-11；最近 push 2026-09-14；MIT。注意：README 的 What's New 最新条目停留在 2023 年 11 月，仓库本体实质上处于低维护状态（提交多为文档/维护性质），但 HuggingFace 模型资产仍在被广泛使用。

项目定位：开源金融大语言模型（不是 Agent 框架）——通过 LoRA 轻量微调（成本 < $300/次 vs BloombergGPT 的 $300 万）提供金融情感分析、预测、关系抽取、NER、金融问答等能力。

技术栈：Python（pip install fingpt），transformers + peft + PyTorch；基座含 Llama-2/3、ChatGLM2-6B、Qwen-7B 等；数据集（HuggingFace）：fingpt-sentiment-train（76.8K）、fingpt-finred（关系抽取）、fingpt-headline（新闻标题分类）、fingpt-ner、fingpt-fiqa_qa、fingpt-fineval（中文金融选择题 1.06K）等。五层架构：数据源层→数据工程层→LLMs 层→任务层→应用层。

架构特点：单模型微调路线（非多 Agent）；FinGPT-Forecaster 输入 ticker + 日期 + 回溯新闻周数，输出公司分析与下周股价预测；v3.3 情感模型在 FPB/FiQA-SA/TFNS 上超过 GPT-4。

优势：金融情感分析低成本 SOTA；中文相关资产（ChatGLM2/Qwen 基座 + 中文评测集）对 A 股场景友好。 劣势：模型项目而非 Agent 项目；本体维护停滞；Forecaster 只在道指 30 上训练过，A 股需自行微调。 可借鉴点：① 若想给核查助手加「传闻情绪/口径分类」小模型，FinGPT 的 LoRA 微调数据格式（sentiment/headline/NER 数据集）是现成模板——传闻核查本质上是「新闻标题/陈述分类 + NER（公司名、指标、日期）+ 关系抽取（公司-事件-数值）」，FinGPT 的数据集体系直接对应这些子任务；② 中文金融评测集 fingpt-fineval 可用来评估中文金融理解能力。

4. virattt/ai-hedge-fund
来源：https://github.com/virattt/ai-hedge-fund （当前 README 与 2025-05 历史版本 README commit 5d5c2b75f2 均已核实）
基本数据：63,387 stars / 11,117 forks / 162 open issues；创建于 2024-11-29；最近 push 2026-09-03（活跃）；Python + Poetry；MIT；以 aihf 包发布到 PyPI。

项目定位：AI 对冲基金概念验证（"proof of concept for an AI-powered hedge fund"），不执行真实交易，仅教育与研究。项目正处于大重构：转向「persistent, always-on AI hedge fund」，投资 Agent 被重塑为可插拔、可回测的 alpha models（代码目录 hedge_fund/strategies/ 下现为 YAML 策略文件：deep-value、earnings-drift、fundamental-ls、inflections）。

技术栈：Python（Poetry/pyproject）；LLM 支持 Anthropic、OpenAI、DeepSeek、Google、xAI、Kimi；数据源为 Financial Datasets API（financialdatasets.ai，价格/基本面/财报）；密钥自动管理（首次使用时请求并存入 ~/.hedge-fund/.env）。

架构特点（经典版，2025-05 README，已核实原文）——17 个角色协作：

11 个名投资人 persona Agent：Damodaran（估值）、Ben Graham（价值/安全边际）、Bill Ackman（激进）、Cathie Wood（成长）、Charlie Munger、Michael Burry（深度价值逆向）、Peter Lynch（十倍股）、Phil Fisher（scuttlebutt 调研）、Jhunjhunwala、Druckenmiller（宏观不对称）、Warren Buffett
4 个信号 Agent：Valuation（内在价值）、Sentiment、Fundamentals、Technicals，各自产出交易信号
Risk Manager（风险指标+仓位限制）、Portfolio Manager（最终决策+生成订单）
新版机制：以 mandate（基金任务书：strategies, staff, risk, capital, cadence）为核心组织；--backtest 回测并对比基准净值曲线；非交互模式跑完整个基金周期后 "The full cycle record prints to stdout as JSON"（完整周期记录以 JSON 结构化输出），人类可读摘要在 stderr；基金持久化为 ~/.hedge-fund/mandates/ 文件
优势：明星项目、教学价值极高；persona 化 Agent 提示词写法经典（每个投资人有独立系统提示与决策逻辑）；结构化 JSON 输出 + 回测闭环完整。 劣势：重构期代码结构变动大；数据源绑定 Financial Datasets（收费 API，美股为主）；无 A 股支持；persona 模拟有表演成分，严谨性弱于 TradingAgents。 可借鉴点：① 「多视角 persona + 信号汇总」可以改造成「乐观解读 Agent / 严苛质疑 Agent / 中性事实 Agent」各自对传闻给出独立判断再汇总；② 完整周期 JSON 记录输出（机器可读+人类摘要分离到 stdout/stderr）的做法很适合核查报告输出设计；③ --show-reasoning 把每个 Agent 的推理过程打印出来的可解释性设计。

5. OpenBB（OpenBB-finance/OpenBB）及其 AI/Agent 能力
来源：https://github.com/OpenBB-finance/OpenBB 、https://raw.githubusercontent.com/OpenBB-finance/OpenBB/develop/README.md 、https://github.com/OpenBB-finance/agents-for-openbb
基本数据：73,020 stars / 7,553 forks / 115 open issues；创建于 2020-12-20；最近 push 2026-09-14（活跃）；Python；AGPLv3（注意许可传染性）。

项目定位与功能：从「开源 Bloomberg 终端」演化为 ODP（Open Data Platform）——帮助数据工程师把专有/授权/公共数据源整合到 AI 副驾与研究仪表盘等下游应用的开放工具集，理念 "connect once, consume everywhere"（一次连接，处处使用）。

技术栈与架构：

Python 包 openbb，统一 API：obb.equity.price.historical("AAPL") → to_dataframe()
一份数据、多个消费终端：Python（量化）、OpenBB Workspace（分析师企业级 UI，pro.openbb.co）、Excel、MCP 服务器（AI Agent）、REST API（FastAPI/Uvicorn，openbb-api 起在 127.0.0.1:6900）
数据接入通过可扩展后端集成（backends-for-openbb 仓库），支持自建数据后端
AI/Agent 能力：agents-for-openbb 仓库提供 OpenBB Workspace 自定义 Agent 集成，依赖 OpenBB AI SDK（openbb-ai）；示例覆盖：检索原始 widget 数据、流式输出 reasoning steps（推理步骤）、生成带 citations（引用）的回复、图表、表格、PDF 处理与 PDF 内引用、MCP 工具接入；生产级参考实现为 Agent Rita（TypeScript + Bun）
优势：数据基础设施层设计业界标杆；「同一数据层服务人类与 Agent」的分层思想成熟；Agent 输出中推理步骤流式展示 + 引用（citations）是第一公民能力；MCP 原生支持。 劣势：AGPLv3 许可对商用不友好；体量大，个人项目借鉴理念即可；本身不提供 A 股后端（需自建）。 可借鉴点：① 「数据平台层 + Agent 消费层」分离：核查助手中把 akshare/tushare 封装成统一数据层（一个 get_quote/get_announcement/get_news 接口族），Agent 只依赖抽象接口——未来换数据源不动 Agent；② OpenBB Agent 的 citations 机制（每个回复附数据来源引用）正是传闻核查报告的核心需求；③ reasoning steps 流式输出提高可解释性。

6. AI4Finance-Foundation 生态其他项目（简要）
来源：GitHub org API（orgs/AI4Finance-Foundation/repos，2026-09-15）
项目	Stars	定位与状态
FinRL	16,285	金融强化学习开山框架，三层架构（市场环境/DRL Agent/应用），支持 14 个数据源（含 Tushare、A股），train-test-trade 流水线；迭代缓慢（正式版停在 0.3.5/2022），官方称活跃开发已转向 FinRL-X，最近 push 2026-07
FinRL-Trading（FinRL-X）	3,699	面向生产的 AI-Native 模块化量化基础设施（FinRL 的下一代）
FinRL-Meta	1,939	动态数据集与市场环境
FinNLP	1,485	金融 NLP 数据管道（FinGPT 的数据层），2024-07 后未再更新
FinRL_DeepSeek	137	LLM+风险敏感 RL 交易（arXiv:2502.07393）
FinRAG	62	金融 RAG，2024-08 后未再更新
ElegantRL	4,364	大规模并行 RL 框架
FinGPT-Earnings-Call-LLM-Agent	18	财报电话会 Agent，2024-04 后停更
小结：该生态是「模型/RL 派」，与 Agent 工程派（TradingAgents、ai-hedge-fund）互补。对核查助手直接可借的主要是 FinGPT 的数据集格式；FinRL 系列与本项目关系不大。

7. 补充搜索发现的新项目
搜索关键词："stock analysis LLM agent github"、"financial agent framework open source"、"akshare agent"、"financial rumor detection"（GitHub API 搜索，2026-09-15）。

7.1 liangdabiao/easy_investment_Agent_crewai（A 股多 Agent，最直接的同类参考）
来源：https://github.com/liangdabiao/easy_investment_Agent_crewai ；632 stars / 119 forks；最近 push 2026-05；MIT
定位：「基于AKShare和CrewAI的A股智能分析平台，通过多Agent协作提供专业的A股投资分析」
技术栈：数据层 AKShare（实时行情、历史K线、财务报表、资金流向、行业板块、市场情绪）+ CrewAI 编排 + LangChain 接 LLM（默认 Ollama 本地 llama3.1，可切 GPT-4）；配置式定义 Agent（config/agents.yaml 角色定义、config/tasks.yaml 任务与输出格式定义）
4 个 Agent：A股市场分析师（技术面/政策面/资金面）、财务报表专家（财务比率/趋势/同业对比）、市场情绪研究员（资金流向/新闻情绪）、A股投资顾问（综合+策略+风控）；配套 4 类工具：A股数据工具、财务分析工具、市场情绪工具、计算器工具（安全数学计算）
A 股特色：政策影响分析、涨跌停分析、散户情绪、资金轮动、北向资金；支持 600519.SH / 000001.SZ / 00700.HK
可借鉴点：这是「akshare + 多 Agent」最直接的落地样本——工具层按「行情/财务/情绪」分类、agents.yaml/tasks.yaml 的配置式 Agent 定义（任务输出格式写进 YAML，天然结构化）、计算器工具兜底数学运算。
7.2 huweihua123/stock-mcp（A 股金融数据 MCP 服务器）
来源：https://github.com/huweihua123/stock-mcp ；176 stars；最近 push 2026-03；MIT
定位：「开源金融数据 MCP / HTTP 服务，面向 AI Agent、量化脚本和普通后端集成」，MCP 接口给 Claude Desktop/Cursor/各类 Agent，HTTP API 给普通后端
技术栈：Python + FastAPI + FastMCP；Redis + Postgres；Docker Compose；国内源直连 Tushare、Akshare、Baostock，海外源 yfinance/Finnhub/Alpha Vantage/FRED/EDGAR 走代理；四层插件化架构（runtime / capabilities / providers / transports）
能力分组：市场数据（A股/美股/ETF/指数行情、K线、多源回退）、技术分析、基本面研究、基于 Tavily 的统一新闻检索、资金流筹码、公告与文档（SEC filings + A股公告处理 + 文档 chunk/markdown/结构化提取）；HTTP 路由 /api/v1/market|technical|fundamental|money-flow|news|filings/*
Agent 友好设计：「MCP artifact 减载，避免把大 blob 直接塞进模型上下文」；code-export 接口导出 CSV/JSON 给代码执行型 Agent
可借鉴点：① 它把 A 股三大免费源（akshare/tushare/baostock）+ 新闻检索 + 公告处理统一成一个面向 Agent 的服务，与核查助手的数据层需求几乎重合，可作为封装范本；② artifact 减载思路（大结果落盘/转引用，不塞上下文）对处理长公告文本很有用；③ 新闻检索独立成工具的做法。
7.3 TNT-Likely/PanWatch（盯盘侠，A 股 TradingAgents 落地）
来源：https://github.com/TNT-Likely/PanWatch ；918 stars / 205 forks；最近 push 2026-09（活跃）；MIT
定位：自托管 AI 盯盘助手，A 股/港股/美股实时监控 + 持仓管理 + 全渠道推送（Telegram/企业微信/钉钉/飞书）
技术栈：FastAPI/SQLAlchemy/APScheduler + React 18；直接集成 TradingAgents 的 9-Agent 流水线（4 分析师→多空辩论→风控→PM），默认 deepseek-chat，单次分析约 $0.05；Topics 含 akshare；新闻 Agent 抓取财经新闻并用 AI 筛选与持仓相关信息
可借鉴点：证明了 TradingAgents 架构可以低成本嫁接到 A 股数据源上（DeepSeek + akshare），且单次成本可控制在美分级；其新闻筛选 Agent 的思路接近「传闻与标的关联判断」。
7.4 kbhujbal/AlphaAnalyst（引用校验/防幻觉做得最好的小项目）
来源：https://github.com/kbhujbal/AlphaAnalyst-open-source-autonomous-equity-research-agent ；47 stars；Apache-2.0；最近 push 2026-04
定位：开源自主股票研究 Agent，输入 ticker 生成分析师级 memo（DCF、可比估值、新闻情绪、财报电话会语气、多空论点）
技术栈：FastAPI 编排器 + Redis 进度 + Postgres/pgvector RAG（Voyage 嵌入）+ Next.js 14；LiteLLM 调 Claude + GPT-4o；数据源 SEC EDGAR/Polygon/FMP/Finnhub/MarketAux/Google News/FRED
防幻觉与引用校验（README 原文，与传闻核查需求高度契合）：
"the LLM is a writer, not a knower (numbers come from APIs)"
综合器会 "downgrades any section whose numerical claims aren't tagged to a real source"（数值声明未标注真实来源的章节被降级处理）
"decimal.Decimal everywhere; no LLM ever touches an arithmetic operator"（所有计算用 Decimal，LLM 不碰算术）
评估套件检验「数值声明可回溯到 10-K 页面、引用非伪造」，退化则报错
Devil's Advocate Agent 强制使用不同模型家族（GPT-4o）与主流程（Claude）对抗
可借鉴点：这是本次调研中与「核查」需求最对口的项目——数值溯源降级机制、引用真伪校验、跨模型家族魔鬼代言人三件套可以直接移植到传闻核查：传闻中的每个数值断言必须能在工具返回数据中找到出处，找不到就标记「无法证实」并降级置信度。
7.5 其他
jason8745/llm-agent-trader（485 stars）：FastAPI + Next.js + Azure OpenAI GPT-4 的 LLM 回测系统，yfinance 数据，架构图清晰（前端→网关→LLM 流式回测引擎→SQLite 记录），近期活跃。来源：https://github.com/jason8745/llm-agent-trader
HKUSTDial/DeepEar（283 stars）：深度研究与金融信号追踪开源框架（中英双语）。来源：GitHub 搜索
重要发现（负面结果）：搜索 "financial rumor detection / fact-check financial news / stock news verification LLM" 只找到 0-star 级别的玩具项目（如 792424327/verifai、VedantVH/FinGuard-AI、cdmanh1108 的越南语数字推理事实核查）。「股市传闻核查/金融事实核查」方向目前没有成熟的成熟开源 Agent 项目——该需求属于空白，你的项目有差异化空间，但也意味着没有现成范式可抄，需要从上[上文]项目的「证据校验」组件中拼装方法。
8. 中国 A 股数据源生态
库	Stars	维护状态	能提供的数据	备注
akshare (akfamily/akshare)	22,580	极活跃（8 open issues，push 2026-09-09，持续发版）	行情（A 股日线 stock_zh_a_hist/美股/ETF/期货/期权/可转债）、财务、资金流、宏观；数据来自东财/新浪/金十/各交易所等数十个站点	MIT；文档 https://akshare.akfamily.xyz/ ；内置离线接口注册表：ak.search() 按关键词查接口、ak.interface_info() 查参数/输出列，README 原文称 "especially handy for LLM-driven programs"——官方已为 LLM 场景优化
tushare (waditu/tushare)	15,401	GitHub 仓库基本停更（README 更新日志停在 2018 年底，最后 push 2024-03；重心已全面转向 tushare.pro 平台）	Pro 平台覆盖行情/财报/公告/资讯/宏观，README/官网提及「资讯数据」「Skills、MCP 等 AI 对接能力」「Python SDK + Restful HTTP」	Pro 采用 token + 积分分级权限（具体接口权限需查官网权限中心，本次抓取首页未列明细）；免费额度有限
baostock	（官网 JS 渲染无法抓取，PyPI 数据为准）	2026 年恢复更新（0.9.1 2026-04 → 0.9.3 2026-07，此前 2019-2024 长期停更）	A 股历史 K 线（日/分钟）、复权（前/后/不复权）、换手率、ST 标记、估值指标 peTTM/pbMRQ/psTTM/pcfNcfTTM；返回 pandas DataFrame	免注册即用（login()），自建数据服务器；BSD；局限：无实时行情、无新闻公告类数据（PyPI 描述仅示例行行情）
efinance (Micro-sheep/efinance)	4,051	低频维护（push 2026-07，但仅 89 commits，153 open issues 未关闭，README 示例停在 2021-2022）	东财系数据：股票 K 线/实时行情/龙虎榜/季度业绩/资金流、基金净值与持仓、可转债、期货	MIT；接口命名直观（get_quote_history 支持中文股票名）；限流问题多，README 建议遇限流换 TickFlow
来源：https://github.com/akfamily/akshare 、https://github.com/waditu/tushare 、https://tushare.pro/ 、https://pypi.org/project/baostock/ （baostock 官网 www.baostock.com 为 JS 渲染，静态抓取失败，未能核实其官网最新公告，数据能力以 PyPI 包描述为准）、https://github.com/Micro-sheep/efinance

选型建议（对核查助手）：主源用 akshare（活跃、覆盖广、对 LLM 友好的接口检索）；公告/资讯的规范化结构化数据可考虑 tushare Pro（需 token，注意积分门槛，可在报告中说明）；baostock 作为历史行情+估值指标的备用免费源；efinance 仅作补充（维护风险）。注意：这些免费库都依赖爬取公开页面，接口随时可能因源站改版失效（akshare README 明示部分接口可能被移除），所以数据层必须做多源降级。

二、总结
2.1 金融 Agent 项目的常见架构模式
综合上述项目，可归纳出七种被反复使用的模式：

「分析师团队 → 辩论 → 裁决」流水线（TradingAgents、ai-hedge-fund、FinRobot、PanWatch 都用）：多个专项 Agent 各自产出分析 → 多空/正反辩论（可配置轮数）→ 交易员/PM/RM 最终裁决。这是金融多 Agent 的事实标准。
Persona 化角色（ai-hedge-fund 的 11 个名投资人）：用人物设定约束 Agent 的关注点与决策风格，提高视角多样性。
确定性计算与 LLM 叙述严格分离（FinRobot "Numbers are code-calculated"、AlphaAnalyst "no LLM ever touches an arithmetic operator"）：财务数字/指标由纯 Python 计算，LLM 只解释和综合。这是所有严谨项目的共识。
防幻觉三件套（TradingAgents 的价格锚定/数据快照、AlphaAnalyst 的引用校验+数值溯源降级、OpenBB/FinRobot 的 citations/证据链接）：把 LLM 的断言锚定在工具取回的已验证数据上，无出处的断言降级处理。
结构化输出（TradingAgents 的 Pydantic schema Agent、ai-hedge-fund 的 JSON cycle record、FinRobot 的分章报告、CrewAI 的 tasks.yaml 输出格式定义）：最终产物机器可读。
数据层与 Agent 层解耦（OpenBB ODP 的 "connect once, consume everywhere"、stock-mcp 的 providers 插件层、FinRobot 的多源故障转移）：Agent 只见统一接口，数据源可插拔、可降级。
反思与审计（TradingAgents 的 trading_memory.md 决策日志 + 下轮注入反思、OpenBB 的 reasoning steps 流式展示）：让每次判断留痕、可复盘。
框架选择：LangGraph（TradingAgents）> CrewAI（A 股社区项目）> AutoGen（FinRobot V0，渐被淘汰）> OpenAI Agents SDK（FinRobot V1）> PydanticAI；新兴趋势是 MCP 协议作为 Agent-数据的标准接口（OpenBB、Tushare、stock-mcp 都已支持）。也有项目不依赖框架、用 FastAPI 手写编排（AlphaAnalyst、PanWatch）。

2.2 A 股数据源现状
akshare 一家独大（22.6k stars、极活跃、官方支持 LLM 场景），覆盖行情/财务/资金流/宏观，新闻公告类接口可查其 Data Dict；tushare Pro 数据最规范（含公告、资讯、MCP 接入）但有 token/积分门槛，GitHub 老仓库已停更；baostock 2026 年恢复更新，适合做历史行情+估值备用源；efinance 维护偏弱。
共同风险：免费库皆为公开页面爬取，接口稳定性无 SLA，多源降级是必须项（stock-mcp、openclaw-data-china-stock 等项目都内置了降级链）。
2.3 对「股市传闻核查助手」的借鉴意义
结合你的场景（Python、A 股、虚构公司数据已由题目提供、Agent 调行情/公告/资讯工具输出判断），建议吸收以下六点：

架构：简化版「分析师团队 + 正反辩论 + 裁决」。不必上 9 个 Agent，3+1 即可：行情核查 Agent、公告核查 Agent、资讯核查 Agent + 一个裁决 Agent。传闻核查天然自带「辩论」结构——支持证据 vs 反驳证据，可参考 TradingAgents 的多空辩论（max_debate_rounds）实现。
工具设计：按证据类型分类 + 统一数据层。
参照 easy_investment_Agent_crewai 的工具分类（行情/财务/情绪/计算器）和 stock-mcp 的路由分组（market/news/filings），把工具设计为 get_quote（行情快照）、search_announcements（公告检索）、search_news（资讯检索）、外加一个计算器工具（涨跌幅、涨跌停价等由代码算，LLM 不做算术——FinRobot/AlphaAnalyst 原则）。
数据层做多源降级（akshare 主源 + 备源），Agent 只依赖抽象接口（OpenBB 思想）。
判断框架：断言分解 + 逐条溯源 + 无据降级。这是本次调研最有价值的发现（主要来自 AlphaAnalyst）：
先把传闻拆成可核查的原子断言（公司 X、事件 Y、数值 Z、时间 T——可参考 FinGPT 的 NER/关系抽取数据集格式）；
每条断言去对应工具取证（数值断言 → 行情/财务快照；事件断言 → 公告；传播断言 → 新闻）；
每条结论必须绑定证据（工具返回的字段值/公告原文片段），无出处的断言标记「无法证实」并降低整体置信度（AlphaAnalyst 的 downgrade 机制）；
最终裁决输出结构化 JSON（判断：属实/不实/部分属实/无法证实 + 置信度 + 证据列表 + 反证列表 + 数据快照时间），机器可读（ai-hedge-fund 的 JSON cycle record 模式）。
防幻觉：数据锚定。采用 TradingAgents v0.4.0 的做法：先从工具取回已验证的数据快照（行情价格、公告文本），把快照注入提示词，要求 LLM 的所有数值引用只能来自快照——从机制上杜绝编造价格。
可解释性：推理留痕。输出中保留每个核查 Agent 的中间结论（ai-hedge-fund 的 --show-reasoning、OpenBB 的 reasoning steps），核查报告本身就是要给人看证据链的。
成本控制：双模型分工（TradingAgents 的 deep_think/quick_think）；PanWatch 验证了 DeepSeek 级别模型 + 单次分析 $0.05 的可行性——核查助手用国产模型（GLM/DeepSeek/Qwen，TradingAgents 已原生支持这三家）完全够用且贴近 A 股语境。
关于赛道空白：GitHub 上目前没有成熟的「股市传闻核查」开源 Agent 项目（搜索仅见 0-star 玩具项目），你可以放心借鉴上述项目的组件化做法而不必担心撞车；同时也没有现成范式，核心的「传闻→断言分解→逐条取证→置信度裁决」链路需要你自行组合 TradingAgents 的辩论/锚定机制与 AlphaAnalyst 的溯源校验机制来实现。

附：信息来源清单
TradingAgents：https://github.com/TauricResearch/TradingAgents （GitHub API：106,376 stars，push 2026-09-15）
FinRobot：https://github.com/AI4Finance-Foundation/FinRobot （7,992 stars，push 2026-09-11）
FinGPT：https://github.com/AI4Finance-Foundation/FinGPT （21,250 stars，push 2026-09-14，README 更新停于 2023-11）
ai-hedge-fund：https://github.com/virattt/ai-hedge-fund （63,387 stars，push 2026-09-03；旧版 agent 名单核实自 2025-05-31 commit 5d5c2b75f2 的 README）
OpenBB：https://github.com/OpenBB-finance/OpenBB （73,020 stars，push 2026-09-14）；Agent 集成：https://github.com/OpenBB-finance/agents-for-openbb
AI4Finance 生态：https://github.com/AI4Finance-Foundation （组织仓库列表 API）
easy_investment_Agent_crewai：https://github.com/liangdabiao/easy_investment_Agent_crewai （632 stars）
stock-mcp：https://github.com/huweihua123/stock-mcp （176 stars）
PanWatch：https://github.com/TNT-Likely/PanWatch （918 stars）
AlphaAnalyst：https://github.com/kbhujbal/AlphaAnalyst-open-source-autonomous-equity-research-agent （47 stars）
llm-agent-trader：https://github.com/jason8745/llm-agent-trader （485 stars）
akshare：https://github.com/akfamily/akshare ，文档 https://akshare.akfamily.xyz/
tushare：https://github.com/waditu/tushare ，Pro 平台 https://tushare.pro/
baostock：https://pypi.org/project/baostock/ （官网 www.baostock.com 为 JS 渲染，未能抓取正文）
efinance：https://github.com/Micro-sheep/efinance
未核实/存疑项说明：① baostock 官网文档未能抓取（JS 渲染），其分钟线/财务/宏观数据能力仅从 PyPI 包描述推断，未获官网原文证实；② tushare Pro 的积分-接口权限对应细则未抓取到（官网首页未列，需注册后查看权限中心）；③ FinRobot V2/V3 架构细节未开源，仅有 README 描述；④ star 数为 2026-09-15 快照，会随时间变化。