"""数值判断工具。

AGENT.md 引用 FinRobot/AlphaAnalyst 原则：数字由代码计算，LLM 不碰算术。
judge 节点锚定数值断言时调用本模块，避免模型直接比较数值。
"""
from __future__ import annotations

# A 股主板/创业板涨跌停 ±10%（简化，未区分 20cm 板块）。
A_SHARE_LIMIT_PCT = 10.0


def is_limit_up(change_pct: float | None) -> bool:
    """是否触及涨停上限。"""
    return change_pct is not None and change_pct >= A_SHARE_LIMIT_PCT


def is_limit_down(change_pct: float | None) -> bool:
    """是否触及跌停下限。"""
    return change_pct is not None and change_pct <= -A_SHARE_LIMIT_PCT


def exceeds_drop_threshold(change_pct: float | None, threshold: float = 5.0) -> bool:
    """是否跌超给定阈值（默认 5 个点）。"""
    return change_pct is not None and change_pct <= -threshold


def exceeds_rise_threshold(change_pct: float | None, threshold: float = 5.0) -> bool:
    """是否涨超给定阈值（默认 5 个点）。"""
    return change_pct is not None and change_pct >= threshold
