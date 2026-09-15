"""核查流水线编排（LangGraph）。

三节点直线流水线：planner → evidence → judge，对应 PRD §6。
LangGraph 用 StateGraph + CheckState（TypedDict）；节点返回 dict 子集更新状态。
"""
from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from agents.evidence import gather_evidence
from agents.judge import judge_rumor
from agents.planner import plan_rumor
from data.local_data import DATA_DATE
from schemas import CheckState, LLMConfig, RumorCheckResult


def build_graph():
    """编译核查流水线图。"""
    g = StateGraph(CheckState)
    g.add_node("planner", plan_rumor)
    g.add_node("evidence", gather_evidence)
    g.add_node("judge", judge_rumor)
    g.add_edge(START, "planner")
    g.add_edge("planner", "evidence")
    g.add_edge("evidence", "judge")
    g.add_edge("judge", END)
    return g.compile()


def run_check(rumor_text: str, llm_config: LLMConfig) -> RumorCheckResult:
    """同步执行核查流水线，返回结构化结果。"""
    graph = build_graph()
    final_state = graph.invoke({"rumor_text": rumor_text, "llm_config": llm_config})
    result = final_state.get("result")
    if isinstance(result, RumorCheckResult):
        return result
    # 兜底：流水线异常未产出 result
    return RumorCheckResult(
        rumor_text=rumor_text,
        final_verdict="unverifiable",
        basis="核查流水线未能产出结果。",
        data_date=DATA_DATE,
    )
