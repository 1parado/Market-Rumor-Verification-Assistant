"""IM 消息 → 核查流水线 → 纯文本结论。

@机器人触发的消息剥离 @mention 后，调 pipeline.run_check 跑一轮核查，
把 RumorCheckResult 渲染为飞书纯文本摘要返回给 bridge 回复。
IM 触发的核查不落库（即问即答），如需追溯后续再扩展。
"""
from __future__ import annotations

from llm import LLMError
from pipeline import run_check
from schemas import LLMConfig, RumorCheckResult

_V_MAP = {"credible": "可信", "questionable": "存疑", "unverifiable": "无法核实"}
_T_MAP = {"supports": "支持", "refutes": "反驳", "unverifiable": "无法核实"}


def handle_im_message(text: str, llm_config: LLMConfig) -> str:
    """跑一轮核查，返回结论纯文本。失败返回错误提示文本。"""
    try:
        result = run_check(text, llm_config)
    except LLMError as exc:
        return f"⚠️ 核查失败（LLM 调用 status={exc.status}）：{exc.detail}"
    except Exception as exc:  # noqa: BLE001 - 流水线内部异常兜底
        return f"⚠️ 核查失败：{exc}"
    return _render_summary(result)


def _render_summary(r: RumorCheckResult) -> str:
    """把核查结果渲染为飞书纯文本摘要。"""
    claims = {c.id: c.text for c in r.claims}
    lines = [
        f"【核真结论】{_V_MAP.get(r.final_verdict, '无法核实')}",
        f"传闻：{r.rumor_text}",
    ]
    if r.basis:
        lines.append(f"依据：{r.basis}")
    if r.verifications:
        lines.append("逐条核查：")
        for v in r.verifications:
            lines.append(
                f"· [{claims.get(v.claim_id, v.claim_id)}] — "
                f"{_T_MAP.get(v.verdict, '无法核实')}：{v.reasoning}"
            )
    if r.data_date:
        lines.append(f"数据日期：{r.data_date}")
    return "\n".join(lines)
