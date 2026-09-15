"""核查工具层。

按证据类型分类（行情/公告/资讯/计算器），面向 Agent 的结构化返回。
对应 PRD §6.2 evidence 节点。
"""
from tools.announcements import get_announcements
from tools.calculator import exceeds_drop_threshold, exceeds_rise_threshold, is_limit_down, is_limit_up
from tools.news import get_news
from tools.quote import get_quote

__all__ = [
    "get_quote",
    "get_announcements",
    "get_news",
    "is_limit_up",
    "is_limit_down",
    "exceeds_drop_threshold",
    "exceeds_rise_threshold",
]
