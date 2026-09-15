# AI 协作过程记录

项目：市场传闻核查助手（核真 Veritas） · 2026-09-15
协作方式：人类提出需求与反馈，AI（WorkBuddy / Claude）实现、调试、验证；关键决策由人类确认。

## 一、从原型到全栈的迭代过程

1. **AI 原生工作台原型**：先用 mock 数据做了深色三栏工作台（Activity Stream / Approval Queue / Plan-Execute / 置信度梯度等概念验证），确立状态色规范（可信绿 / 存疑橙 / 无法核实灰 / 待审批蓝）。
2. **宣传页**：`frontend/` 改造为 GitHub Pages 宣传页（原工作台保留为 demo），配置 GitHub Actions 自动部署。
3. **真实前端**：`front/` 按参考截图重做为「居中胶囊输入」首页，先原生 JS 后**迁移 Vue 3 + Vite**；期间修复了 CSS 选择器因 Vue 模板缺 id 而失效、`[hidden]` 被 flex 类覆盖等迁移坑。
4. **后端演进**：FastAPI + LangGraph 三节点流水线 → SSE 流式（step 实时进度事件）→ SQLite 持久化（配置/运行/事件/会话四表）→ token 计量（tiktoken）→ 真实网络搜索（Perplexity 式来源带回）。

## 二、关键设计决策（AI 提议 + 人类确认）

| 决策 | 理由 |
|---|---|
| 快照锚定防幻觉 | judge 的数值引用只能来自 evidence 快照，查不到标 unverifiable —— 对应硬性要求 1/2 |
| planner 限候选公司清单 | 防止 LLM 编造公司；间接指代（「上个月上市的储能新股」）靠候选提示消歧 —— 对应要求 3 |
| 强制工具调用输出结构化 | tool_choice 强制 + JSON Schema，比自由文本可靠 |
| 配置单一数据源 | App 持有 cfg，弹窗经 prop 直接变更；修复了两份副本互相覆盖导致配置丢失的 bug |
| token 计量按 run_id 注册收集器 | SSE 生成器跨 yield 换线程，contextvar 会丢；注册表方案跨线程可靠 |
| 结论导向页面重构 | 首屏给结论 + 断言/过程折叠展开，从「过程导向」改为「先答案后溯源」 |

## 三、踩坑与修复记录（节选）

- **`Illegal header value b'Bearer '`**：空 API Key 时 httpx 拼出非法头。修复：调用前校验，空 Key 返回语义化中文错误。
- **模型列表拉取成功但不展示**：原生 `<datalist>` 在 Edge/Chrome 几乎不可见 → 改为真 `<select>` 下拉。
- **sqlite `ON CONFLICT` 更新路径 `lastrowid` 不可靠** → 按唯一键回查。
- **`/chat` 返回整行 dict 而非文本** → 前端显示 `[object Object]`，改为返回 content 字符串。
- **SSE contextvar 失效**：生成器每次 yield 换线程池线程，contextvar 副本丢弃 → 见上表注册表方案。
- **暗色模式字体不清**：视觉升级层在文件尾部用 `:root` 追加浅色 token，同特异性下覆盖了暗色主题值 → token 全部合并回顶部唯一主题块，硬编码浅色改 `var(--card-tint)`。
- **单脚本 `check_rumor` 三连坑**：① 未传 `tool_choice` 部分模型不走工具；② 提供商 429 限流 → 加退避重试；③ `final_verdict` 偶发缺失/verifications 混入字符串 → 枚举兜底 + 类型防御，并从逐条判定推导最终结论。
- **依赖地狱**：`uv add` 重解析把 `websockets` 升到 16.x（删除 `websockets/client.py`）致 langgraph_sdk 崩溃 → 固定 `websockets<16`。

## 四、最终验证

- `python3 编程题A-传闻核查.py`：5 条 RUMORS 全部输出结构化结果（credible / questionable / questionable / unverifiable / questionable），第 4 条「国资重组」快照无相关信息 → 诚实「无法核实」。
- 全栈链路：SSE 事件序列 `start → step → node ×3 → done`，结论/置信度/token 用量落库，历史可回放，会话可追问。
- 提交前检查：仓库无 API Key（脚本为占位符，SQLite 已 gitignore）。
