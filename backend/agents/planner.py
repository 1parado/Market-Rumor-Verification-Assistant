"""规划节点：识别传闻涉及的公司 + 分解原子断言。

参考 TradingAgents 的规划环节，用工具调用强制结构化输出。
提供候选公司清单辅助消歧间接指代（如「上个月上市的储能新股」→ 新湾储能）。
"""
from __future__ import annotations

from data.local_data import CANDIDATE_COMPANIES
from llm import chat
from schemas import CheckState, Claim, CompanyRef, LLMConfig

_PLAN_TOOL = {
    "type": "function",
    "function": {
        "name": "plan_rumor",
        "description": "把股市传闻分解为可核查的原子断言，并识别涉及的公司",
        "parameters": {
            "type": "object",
            "properties": {
                "companies": {
                    "type": "array",
                    "items": {"type": "object", "properties": {"name": {"type": "string"}, "code": {"type": "string"}}},
                    "description": "传闻涉及的公司（含间接指代解析结果）",
                },
                "claims": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "string"},
                            "text": {"type": "string"},
                            "company": {"type": "string"},
                            "type": {"type": "string", "enum": ["price", "event", "spread"]},
                            "expected": {"type": "string"},
                        },
                        "required": ["id", "text", "company", "type"],
                    },
                    "description": "原子断言列表",
                },
            },
            "required": ["companies", "claims"],
        },
    },
}


def plan_rumor(state: CheckState) -> dict:
    """planner 节点：输出 {companies, claims}。"""
    llm_config: LLMConfig = state["llm_config"]
    candidates = "\n".join(f"- {c['name']}({c['code']}): {c['hint']}" for c in CANDIDATE_COMPANIES)
    system = (
        "你是市场传闻核查规划员。任务：把用户转发的股市传闻分解为可核查的原子断言，"
        "并识别传闻涉及的所有公司（含间接指代，如「上个月上市的储能新股」需解析为具体公司）。\n\n"
        "候选公司清单（用于消歧，只从中选取，禁止编造清单外的公司）：\n"
        f"{candidates}\n\n"
        "断言类型：price（价格/涨跌/数值）、event（事件/公告类事实）、spread（传播/资金/情绪类不可直接核实）。\n"
        "要求：每条断言绑定一家公司；传闻隐含的多家公司都要识别；不要补充传闻未提及的公司。"
    )
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": f"传闻：{state['rumor_text']}"},
    ]
    resp = chat(
        messages,
        llm_config,
        tools=[_PLAN_TOOL],
        tool_choice={"type": "function", "function": {"name": "plan_rumor"}},
    )
    if not resp.tool_calls:
        return {"companies": [], "claims": []}
    args = resp.tool_calls[0].arguments
    companies = [CompanyRef(**c) for c in args.get("companies", [])]
    claims = [Claim(**c) for c in args.get("claims", [])]
    return {"companies": companies, "claims": claims}
