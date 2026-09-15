"""裁决节点：基于数据快照逐条核查断言 + 汇总最终判断。

把数据快照注入 prompt，调 LLM 用工具调用强制结构化输出。
所有数值引用只能来自快照（TradingAgents 价格锚定）。
"""
from __future__ import annotations

from data.local_data import DATA_DATE
from llm import chat
from schemas import CheckState, Claim, Evidence, LLMConfig, RumorCheckResult, Verification

_VERIFY_TOOL = {
    "type": "function",
    "function": {
        "name": "verify_rumor",
        "description": "基于数据快照对每条断言给出判断并汇总",
        "parameters": {
            "type": "object",
            "properties": {
                "verifications": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "claim_id": {"type": "string"},
                            "verdict": {"type": "string", "enum": ["supports", "refutes", "unverifiable"]},
                            "reasoning": {"type": "string"},
                            "source": {"type": "string", "enum": ["quote", "announcement", "news"]},
                            "source_ref": {"type": "string"},
                            "confidence": {"type": "integer", "description": "该条判断的置信度 0-100"},
                        },
                        "required": ["claim_id", "verdict", "reasoning"],
                    },
                },
                "final_verdict": {"type": "string", "enum": ["credible", "questionable", "unverifiable"]},
                "basis": {"type": "string"},
                "confidence": {"type": "integer", "description": "整体判断的置信度 0-100"},
            },
            "required": ["verifications", "final_verdict", "basis"],
        },
    },
}


def judge_rumor(state: CheckState) -> dict:
    """judge 节点：输出 {verifications, result}。"""
    llm_config: LLMConfig = state["llm_config"]
    claims: list[Claim] = state.get("claims", [])
    evidence: list[Evidence] = state.get("evidence", [])

    if not claims:
        result = _build_result(state, claims, [], "unverifiable", "未能从传闻中分解出可核查断言。", [])
        return {"verifications": [], "result": result}

    snapshot_text = _format_snapshot(evidence)
    system = (
        "你是市场传闻核查裁决员。基于下方数据快照对每条断言逐条判断，再汇总整体判断。\n\n"
        "规则：\n"
        "1. 所有判断必须基于数据快照；快照中没有的信息一律标 unverifiable，禁止编造。\n"
        "2. 数值引用只能来自快照字段值，不得自行计算或臆测。\n"
        "3. verdict：supports（快照支持断言）/ refutes（快照与断言相反）/ unverifiable（快照无相关信息）。\n"
        "4. final_verdict：credible（全部 supports）/ questionable（部分支持部分反驳，或与快照有出入）"
        "/ unverifiable（相关数据缺失）。\n"
        "5. reasoning 必须引用快照中的具体字段值或公告/资讯原文片段；source 与 source_ref 指明出处。\n"
        "6. confidence 为 0-100 整数，表示判断把握程度：多个独立来源一致→高分（80-95）；"
        "单一来源→中等（60-75）；数据缺失或来源相互矛盾→低分（10-40）。每条断言和整体各给一个。\n"
    )
    claims_text = "\n".join(
        f"- [{c.id}]({c.type}, 公司={c.company}): {c.text}" + (f"（期望：{c.expected}）" if c.expected else "")
        for c in claims
    )
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": f"传闻：{state['rumor_text']}\n\n待核查断言：\n{claims_text}\n\n数据快照：\n{snapshot_text}"},
    ]
    resp = chat(
        messages,
        llm_config,
        tools=[_VERIFY_TOOL],
        tool_choice={"type": "function", "function": {"name": "verify_rumor"}},
    )
    if not resp.tool_calls:
        result = _build_result(state, claims, [], "unverifiable", "模型未返回结构化核查结果。", [])
        return {"verifications": [], "result": result}

    args = resp.tool_calls[0].arguments
    verifications = [Verification(**v) for v in args.get("verifications", [])]
    sources = sorted({v.source_ref for v in verifications if v.source_ref})
    confidence = args.get("confidence")
    try:
        confidence = max(0, min(100, int(confidence))) if confidence is not None else None
    except (TypeError, ValueError):
        confidence = None
    result = _build_result(
        state, claims, verifications, args.get("final_verdict", "unverifiable"), args.get("basis", ""), sources,
        confidence,
    )
    return {"verifications": verifications, "result": result}


def _build_result(state, claims, verifications, final_verdict, basis, sources, confidence=None) -> RumorCheckResult:
    return RumorCheckResult(
        rumor_text=state["rumor_text"],
        companies=state.get("companies", []),
        claims=claims,
        verifications=verifications,
        final_verdict=final_verdict,
        basis=basis,
        confidence=confidence,
        sources=sources,
        data_date=DATA_DATE,
    )


def _format_snapshot(evidence: list[Evidence]) -> str:
    """把证据按公司+来源格式化为文本快照，供 LLM 锚定。"""
    by_company: dict[str, list[Evidence]] = {}
    for e in evidence:
        by_company.setdefault(e.company, []).append(e)
    lines: list[str] = []
    for company, evs in by_company.items():
        lines.append(f"【{company}】")
        for e in evs:
            if e.source == "quote":
                p = e.payload
                lines.append(
                    f"  - 行情：代码={p.get('code')} 价格={p.get('price')} 涨跌幅={p.get('change_pct')}% 日期={p.get('date')}"
                )
            elif e.source == "announcement":
                lines.append(f"  - 公告：{e.payload.get('text')}")
            elif e.source == "news":
                lines.append(f"  - 资讯：{e.payload.get('text')}")
    return "\n".join(lines) or "（无数据）"
