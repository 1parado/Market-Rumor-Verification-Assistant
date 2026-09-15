"""
编程题A-传闻核查.py 的单元测试
============================================================
全部 mock LLM（call_llm / requests.post），不联网、不消耗 token，
只验证代码本身的逻辑质量与边界行为。

运行：python3 test_传闻核查.py -v
============================================================
"""
import importlib.util
import json
import os
import unittest
from unittest.mock import patch

import requests

_HERE = os.path.dirname(os.path.abspath(__file__))


def _load_module():
    """目标文件名含连字符无法直接 import，用 importlib 按路径加载。"""
    spec = importlib.util.spec_from_file_location(
        "rumor_check", os.path.join(_HERE, "编程题A-传闻核查.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


rc = _load_module()


# ---------- 构造 mock 响应的工具函数 ----------
def _tool_msg(name, args):
    """模拟一次 LLM 强制工具调用返回。"""
    return {"tool_calls": [{"function": {
        "name": name, "arguments": json.dumps(args, ensure_ascii=False)}}]}


def _resp(status_code=200, body=None):
    m = unittest.mock.Mock()
    m.status_code = status_code
    if body is not None:
        m.json.return_value = body
    if status_code >= 400:
        m.raise_for_status.side_effect = requests.HTTPError(f"HTTP {status_code}")
    else:
        m.raise_for_status.return_value = None
    m.text = json.dumps(body or {}, ensure_ascii=False)
    return m


def _plan_args(companies, claims):
    return {"companies": companies, "claims": claims}


def _verify_args(verifications, final_verdict, basis):
    return {"verifications": verifications, "final_verdict": final_verdict, "basis": basis}


# 蓝湾生物「新药失败」传闻的一套标准 mock（plan + verify 两阶段）
_BLUEBAY_PLAN = _plan_args(
    [{"name": "蓝湾生物", "code": "688321"}],
    [{"id": "c1", "text": "蓝湾生物新药三期临床失败", "company": "蓝湾生物", "type": "event"}],
)
_BLUEBAY_VERIFY = _verify_args(
    [{"claim_id": "c1", "verdict": "refutes",
      "reasoning": "公告显示试验达到主要终点，与传闻相反",
      "source": "announcement", "source_ref": "2026-08-06 蓝湾生物公告"}],
    "questionable", "传闻与公告内容相反，判定存疑。")


# =====================================================================
# call_llm：重试 / 异常 / 响应解析
# =====================================================================
class TestCallLLM(unittest.TestCase):
    def _patch_sleep(self):
        return patch.object(rc.time, "sleep")

    def test_success_returns_message(self):
        body = {"choices": [{"message": {"content": "ok"}}]}
        with patch.object(rc.requests, "post", return_value=_resp(200, body)) as p:
            msg = rc.call_llm([{"role": "user", "content": "hi"}])
        self.assertEqual(msg["content"], "ok")
        self.assertEqual(p.call_count, 1)

    def test_payload_contains_model_tools_and_choice(self):
        body = {"choices": [{"message": {"content": ""}}]}
        with patch.object(rc.requests, "post", return_value=_resp(200, body)) as p:
            rc.call_llm([{"role": "user", "content": "x"}],
                        tools=[{"t": 1}], tool_choice={"type": "function"})
        payload = p.call_args.kwargs["json"]
        self.assertEqual(payload["model"], rc.MODEL)
        self.assertEqual(payload["messages"], [{"role": "user", "content": "x"}])
        self.assertEqual(payload["tools"], [{"t": 1}])
        self.assertEqual(payload["tool_choice"], {"type": "function"})

    def test_retry_on_429_then_success(self):
        responses = [_resp(429, {}), _resp(200, {"choices": [{"message": {"content": "ok"}}]})]
        with patch.object(rc.requests, "post", side_effect=responses) as p, \
             self._patch_sleep() as s:
            msg = rc.call_llm([{"role": "user", "content": "hi"}])
        self.assertEqual(msg["content"], "ok")
        self.assertEqual(p.call_count, 2)
        s.assert_called_once_with(rc._RETRY_DELAYS[0])

    def test_retry_on_500_then_success(self):
        responses = [_resp(503, {}), _resp(200, {"choices": [{"message": {"content": "ok"}}]})]
        with patch.object(rc.requests, "post", side_effect=responses):
            rc.call_llm([{"role": "user", "content": "hi"}])

    def test_retry_exhausted_raises_llm_error(self):
        with patch.object(rc.requests, "post", return_value=_resp(429, {})), \
             self._patch_sleep():
            with self.assertRaises(rc.LLMError):
                rc.call_llm([{"role": "user", "content": "hi"}])

    def test_client_error_not_retried(self):
        with patch.object(rc.requests, "post", return_value=_resp(401, {})) as p:
            with self.assertRaises(requests.HTTPError):
                rc.call_llm([{"role": "user", "content": "hi"}])
        self.assertEqual(p.call_count, 1)   # 配置错误不应重试

    def test_network_error_retried_then_success(self):
        body = {"choices": [{"message": {"content": "ok"}}]}
        responses = [requests.ConnectionError("boom"),
                     requests.Timeout("slow"),
                     _resp(200, body)]
        with patch.object(rc.requests, "post", side_effect=responses), \
             self._patch_sleep():
            self.assertEqual(rc.call_llm([{"role": "user", "content": "hi"}])["content"], "ok")

    def test_bad_response_shape_raises(self):
        with patch.object(rc.requests, "post", return_value=_resp(200, {"error": "x"})):
            with self.assertRaises(rc.LLMError):
                rc.call_llm([{"role": "user", "content": "hi"}])

    def test_bad_json_body_raises(self):
        m = _resp(200, {})
        m.json.side_effect = ValueError("not json")
        with patch.object(rc.requests, "post", return_value=m):
            with self.assertRaises(rc.LLMError):
                rc.call_llm([{"role": "user", "content": "hi"}])


# =====================================================================
# _force_tool：工具调用解析的边界
# =====================================================================
class TestForceTool(unittest.TestCase):
    def test_valid_tool_call_parsed(self):
        with patch.object(rc, "call_llm",
                          return_value=_tool_msg("plan_rumor", {"a": 1})):
            self.assertEqual(rc._force_tool([], {"t": 1}, "plan_rumor"), {"a": 1})

    def test_invalid_json_returns_none(self):
        msg = {"tool_calls": [{"function": {"name": "f", "arguments": "{bad json"}}]}
        with patch.object(rc, "call_llm", return_value=msg):
            self.assertIsNone(rc._force_tool([], {}, "f"))

    def test_non_object_json_returns_none(self):
        msg = {"tool_calls": [{"function": {"name": "f", "arguments": "[1, 2]"}}]}
        with patch.object(rc, "call_llm", return_value=msg):
            self.assertIsNone(rc._force_tool([], {}, "f"))

    def test_null_json_returns_none(self):
        msg = {"tool_calls": [{"function": {"name": "f", "arguments": "null"}}]}
        with patch.object(rc, "call_llm", return_value=msg):
            self.assertIsNone(rc._force_tool([], {}, "f"))

    def test_no_tool_calls_returns_none(self):
        with patch.object(rc, "call_llm", return_value={"content": "纯文本"}):
            self.assertIsNone(rc._force_tool([], {}, "f"))

    def test_wrong_tool_name_returns_none(self):
        with patch.object(rc, "call_llm", return_value=_tool_msg("other", {"a": 1})):
            self.assertIsNone(rc._force_tool([], {}, "f"))

    def test_multiple_calls_picks_matching_name(self):
        msg = {"tool_calls": [
            {"function": {"name": "other", "arguments": "{\"x\":1}"}},
            {"function": {"name": "f", "arguments": "{\"y\":2}"}},
        ]}
        with patch.object(rc, "call_llm", return_value=msg):
            self.assertEqual(rc._force_tool([], {}, "f"), {"y": 2})

    def test_malformed_entries_skipped(self):
        msg = {"tool_calls": ["junk", None,
                              {"function": {"name": "f", "arguments": "{\"ok\":true}"}}]}
        with patch.object(rc, "call_llm", return_value=msg):
            self.assertEqual(rc._force_tool([], {}, "f"), {"ok": True})

    def test_llm_error_returns_none(self):
        with patch.object(rc, "call_llm", side_effect=rc.LLMError("限流")):
            self.assertIsNone(rc._force_tool([], {}, "f"))


# =====================================================================
# _derive_final：最终判定兜底规则
# =====================================================================
class TestDeriveFinal(unittest.TestCase):
    def test_valid_final_passthrough(self):
        for v in ("credible", "questionable", "unverifiable"):
            self.assertEqual(rc._derive_final({"final_verdict": v, "verifications": []}), v)

    def test_invalid_final_derived_from_verifications(self):
        v = {"final_verdict": "maybe", "verifications": [{"verdict": "supports"}]}
        self.assertEqual(rc._derive_final(v), "credible")

    def test_missing_final_all_supports(self):
        self.assertEqual(rc._derive_final(
            {"verifications": [{"verdict": "supports"}, {"verdict": "supports"}]}), "credible")

    def test_any_refutes_is_questionable(self):
        v = {"verifications": [{"verdict": "supports"}, {"verdict": "refutes"}]}
        self.assertEqual(rc._derive_final(v), "questionable")

    def test_supports_plus_unverifiable_is_unverifiable(self):
        v = {"verifications": [{"verdict": "supports"}, {"verdict": "unverifiable"}]}
        self.assertEqual(rc._derive_final(v), "unverifiable")

    def test_all_unverifiable(self):
        self.assertEqual(rc._derive_final(
            {"verifications": [{"verdict": "unverifiable"}]}), "unverifiable")

    def test_empty_verifications(self):
        self.assertEqual(rc._derive_final({"verifications": []}), "unverifiable")

    def test_none_and_empty_verdict(self):
        self.assertEqual(rc._derive_final(None), "unverifiable")
        self.assertEqual(rc._derive_final({}), "unverifiable")

    def test_non_dict_entries_ignored(self):
        v = {"verifications": ["junk", 42, {"verdict": "supports"}]}
        self.assertEqual(rc._derive_final(v), "credible")


# =====================================================================
# check_rumor：全流程（mock 两阶段 LLM 返回）
# =====================================================================
class TestCheckRumor(unittest.TestCase):
    def _run(self, llm_returns):
        """依次 mock call_llm 的返回，跑一遍 check_rumor(蓝湾生物传闻)。"""
        rumor = "朋友圈说蓝湾生物的新药三期临床失败了，股价要崩。"
        with patch.object(rc, "call_llm", side_effect=llm_returns) as m:
            result = rc.check_rumor(rumor)
        return result, m

    # ---- 正常路径 ----
    def test_happy_path_structured_output(self):
        result, _ = self._run([_tool_msg("plan_rumor", _BLUEBAY_PLAN),
                               _tool_msg("verify_rumor", _BLUEBAY_VERIFY)])
        self.assertEqual(set(result), {"传闻", "判断", "依据", "逐条核查", "数据来源"})
        self.assertEqual(result["判断"], "questionable")
        self.assertEqual(result["依据"], "传闻与公告内容相反，判定存疑。")
        row = result["逐条核查"][0]
        self.assertEqual(row["断言"], "蓝湾生物新药三期临床失败")
        self.assertEqual(row["判定"], "反驳")
        self.assertIn("公告", row["理由"])
        self.assertEqual(row["出处"], "announcement 2026-08-06 蓝湾生物公告")
        self.assertEqual(result["数据来源"], ["2026-08-06 蓝湾生物公告"])
        self.assertEqual(result["传闻"], "朋友圈说蓝湾生物的新药三期临床失败了，股价要崩。")

    def test_exactly_two_llm_calls_plan_then_verify(self):
        _, m = self._run([_tool_msg("plan_rumor", _BLUEBAY_PLAN),
                          _tool_msg("verify_rumor", _BLUEBAY_VERIFY)])
        self.assertEqual(m.call_count, 2)

    def test_plan_prompt_contains_candidates_and_rumor(self):
        _, m = self._run([_tool_msg("plan_rumor", _BLUEBAY_PLAN),
                          _tool_msg("verify_rumor", _BLUEBAY_VERIFY)])
        plan_msgs = m.call_args_list[0].args[0]
        system = plan_msgs[0]["content"]
        user = plan_msgs[1]["content"]
        self.assertIn("候选公司清单", system)
        for company in rc._QUOTES:          # 6 家候选公司全部列出
            self.assertIn(company, system)
        self.assertIn("禁止编造", system)
        self.assertIn("蓝湾生物", user)

    def test_verify_prompt_contains_snapshot_and_claims(self):
        _, m = self._run([_tool_msg("plan_rumor", _BLUEBAY_PLAN),
                          _tool_msg("verify_rumor", _BLUEBAY_VERIFY)])
        verify_msgs = m.call_args_list[1].args[0]
        user = verify_msgs[1]["content"]
        self.assertIn("【蓝湾生物】行情", user)            # 行情进了快照
        self.assertIn("三期临床试验结果", user)            # 公告进了快照
        self.assertIn("[c1](event", user)                 # 断言列表带类型
        self.assertIn("数据快照", user)
        self.assertIn("禁止编造", verify_msgs[0]["content"])

    def test_multi_company_rumor_queries_each(self):
        plan = _plan_args(
            [{"name": "青云数科"}, {"name": "澜星电子"}],
            [{"id": "c1", "text": "青云数科大跌", "company": "青云数科", "type": "price"},
             {"id": "c2", "text": "澜星电子大跌", "company": "澜星电子", "type": "price"}])
        verify = _verify_args(
            [{"claim_id": "c1", "verdict": "supports", "reasoning": "资讯领跌",
              "source": "news", "source_ref": "2026-08-07 计算板块资讯"},
             {"claim_id": "c2", "verdict": "unverifiable", "reasoning": "快照无数据",
              "source": "news", "source_ref": ""}],
            "questionable", "一家成立一家无数据。")
        result, m = self._run([_tool_msg("plan_rumor", plan),
                               _tool_msg("verify_rumor", verify)])
        user = m.call_args_list[1].args[0][1]["content"]
        self.assertIn("【青云数科】行情", user)
        self.assertIn("【澜星电子】行情", user)
        self.assertEqual(len(result["逐条核查"]), 2)
        self.assertEqual(result["逐条核查"][1]["判定"], "无法核实")
        self.assertEqual(result["数据来源"], ["2026-08-07 计算板块资讯"])

    # ---- 阶段失败降级 ----
    def test_both_stages_fail_falls_back_unverifiable(self):
        result, _ = self._run([rc.LLMError("限流"), rc.LLMError("限流")])
        self.assertEqual(result["判断"], "unverifiable")
        self.assertEqual(result["依据"], rc._FALLBACK_BASIS)
        self.assertEqual(result["逐条核查"], [])
        self.assertEqual(result["数据来源"], [])

    def test_verify_stage_none_falls_back(self):
        """plan 成功、verify 返回不匹配的工具名 → 兜底 unverifiable。"""
        result, _ = self._run([_tool_msg("plan_rumor", _BLUEBAY_PLAN),
                               _tool_msg("other_tool", {"x": 1})])
        self.assertEqual(result["判断"], "unverifiable")
        self.assertEqual(result["逐条核查"], [])

    def test_verify_missing_final_derives_from_rows(self):
        verify = {"verifications": [{"claim_id": "c1", "verdict": "refutes",
                                     "reasoning": "相反"}], "basis": "b"}
        result, _ = self._run([_tool_msg("plan_rumor", _BLUEBAY_PLAN),
                               _tool_msg("verify_rumor", verify)])
        self.assertEqual(result["判断"], "questionable")

    # ---- 边界输入 ----
    def test_empty_rumor_short_circuits(self):
        with patch.object(rc, "call_llm") as m:
            for text in ("", "   ", None):
                result = rc.check_rumor(text)
                self.assertEqual(result["判断"], "unverifiable")
                self.assertEqual(result["逐条核查"], [])
            m.assert_not_called()           # 空传闻不应消耗任何 LLM 调用

    def test_malformed_plan_tolerated(self):
        plan = {"companies": [{}, {"name": "  "}, {"code": "x"}, {"name": "青云数科"}],
                "claims": ["junk", {"text": "缺 id"}, None,
                           {"id": "c1", "text": "青云数科大跌", "company": "青云数科",
                            "type": "price"}]}
        verify = _verify_args(
            [{"claim_id": "c1", "verdict": "supports", "reasoning": "资讯领跌",
              "source": "news", "source_ref": "ref-1"}],
            "credible", "ok")
        result, m = self._run([_tool_msg("plan_rumor", plan),
                               _tool_msg("verify_rumor", verify)])
        self.assertEqual(result["判断"], "credible")       # 没崩，正常出结果
        user = m.call_args_list[1].args[0][1]["content"]
        self.assertEqual(user.count("【青云数科】行情"), 1)  # 坏条目被滤掉，只查一次
        self.assertEqual(len(result["逐条核查"]), 1)

    def test_duplicate_companies_deduped_in_snapshot(self):
        plan = _plan_args([{"name": "恒润科技"}, {"name": "恒润科技"}],
                          [{"id": "c1", "text": "涨停", "company": "恒润科技", "type": "price"}])
        verify = _verify_args([{"claim_id": "c1", "verdict": "supports",
                                "reasoning": "资讯", "source": "news", "source_ref": "r"}],
                              "credible", "b")
        _, m = self._run([_tool_msg("plan_rumor", plan),
                          _tool_msg("verify_rumor", verify)])
        user = m.call_args_list[1].args[0][1]["content"]
        self.assertEqual(user.count("【恒润科技】行情"), 1)

    def test_unknown_company_yields_empty_snapshot(self):
        plan = _plan_args([{"name": "不存在的公司"}],
                          [{"id": "c1", "text": "x", "company": "不存在的公司", "type": "event"}])
        verify = _verify_args([{"claim_id": "c1", "verdict": "unverifiable",
                                "reasoning": "无数据", "source": "news", "source_ref": ""}],
                              "unverifiable", "无数据")
        _, m = self._run([_tool_msg("plan_rumor", plan),
                          _tool_msg("verify_rumor", verify)])
        user = m.call_args_list[1].args[0][1]["content"]
        self.assertIn("（无任何数据）", user)

    def test_empty_plan(self):
        verify = _verify_args([], "unverifiable", "没有断言")
        _, m = self._run([_tool_msg("plan_rumor", {"companies": [], "claims": []}),
                          _tool_msg("verify_rumor", verify)])
        user = m.call_args_list[1].args[0][1]["content"]
        self.assertIn("（无任何数据）", user)
        self.assertIn("（未能分解出断言）", user)

    def test_plan_returns_none_falls_back(self):
        """plan 阶段返回非法 JSON → None → 空规划 → 全流程不崩，仍出结构化结果。"""
        msg = {"tool_calls": [{"function": {"name": "plan_rumor", "arguments": "{oops"}}]}
        verify = _verify_args([], "unverifiable", "快照无数据")
        result, m = self._run([msg, _tool_msg("verify_rumor", verify)])
        self.assertEqual(result["判断"], "unverifiable")
        self.assertEqual(set(result), {"传闻", "判断", "依据", "逐条核查", "数据来源"})
        self.assertIn("（无任何数据）", m.call_args_list[1].args[0][1]["content"])

    def test_verification_rows_filtered_and_fallbacks(self):
        verify = _verify_args(
            ["junk", None,
             {"claim_id": "cX", "verdict": "weird-verdict", "reasoning": "r1"},   # 未知 claim + 非法 verdict
             {"claim_id": "c1", "verdict": "supports", "reasoning": "r2",
              "source": "", "source_ref": ""}],                                    # 空出处
            "bogus_final", "b")
        result, _ = self._run([_tool_msg("plan_rumor", _BLUEBAY_PLAN),
                               _tool_msg("verify_rumor", verify)])
        self.assertEqual(len(result["逐条核查"]), 2)   # junk/None 被滤掉，剩 2 条 dict
        self.assertEqual(result["逐条核查"][0]["断言"], "cX")     # 未知 id 原样回退
        self.assertEqual(result["逐条核查"][0]["判定"], "无法核实")  # 非法 verdict 归无法核实
        self.assertEqual(result["逐条核查"][1]["出处"], "")        # 空出处不产生多余空格
        self.assertEqual(result["判断"], "unverifiable")           # 非法 final 走兜底

    def test_data_sources_sorted_and_deduped(self):
        verify = _verify_args(
            [{"claim_id": "c1", "verdict": "supports", "reasoning": "a",
              "source": "quote", "source_ref": "b-ref"},
             {"claim_id": "c1", "verdict": "supports", "reasoning": "b",
              "source": "news", "source_ref": "a-ref"},
             {"claim_id": "c1", "verdict": "supports", "reasoning": "c",
              "source": "news", "source_ref": "b-ref"}],
            "credible", "b")
        result, _ = self._run([_tool_msg("plan_rumor", _BLUEBAY_PLAN),
                               _tool_msg("verify_rumor", verify)])
        self.assertEqual(result["数据来源"], ["a-ref", "b-ref"])

    def test_verdict_cn_mapping(self):
        for verdict, cn in (("supports", "支持"), ("refutes", "反驳"),
                            ("unverifiable", "无法核实"), ("???", "无法核实")):
            verify = _verify_args([{"claim_id": "c1", "verdict": verdict,
                                    "reasoning": ""}], "unverifiable", "b")
            result, _ = self._run([_tool_msg("plan_rumor", _BLUEBAY_PLAN),
                                   _tool_msg("verify_rumor", verify)])
            self.assertEqual(result["逐条核查"][0]["判定"], cn)


# =====================================================================
# 本地工具函数 / 数据完整性
# =====================================================================
class TestToolsAndData(unittest.TestCase):
    def test_get_quote_known_and_unknown(self):
        q = rc.get_quote("恒润科技")
        self.assertEqual(q["code"], "301566")
        self.assertIsNone(rc.get_quote("贵州茅台"))

    def test_get_announcements_unknown_returns_empty_list(self):
        self.assertEqual(rc.get_announcements("不存在的公司"), [])
        self.assertEqual(rc.get_announcements("青云数科"), [])   # 有行情但无公告

    def test_get_news_unknown_returns_empty_list(self):
        self.assertEqual(rc.get_news("不存在的公司"), [])
        self.assertEqual(rc.get_news("澜星电子"), [])

    def test_all_quote_companies_have_consistent_keys(self):
        for name, q in rc._QUOTES.items():
            self.assertEqual(set(q), {"code", "price", "change_pct", "date"}, name)
            self.assertRegex(q["code"], r"^\d{6}$", name)
            self.assertIsInstance(q["price"], (int, float), name)

    def test_rumors_count(self):
        self.assertEqual(len(rc.RUMORS), 5)

    def test_no_real_api_key_in_source(self):
        with open(os.path.join(_HERE, "编程题A-传闻核查.py"), encoding="utf-8") as f:
            src = f.read()
        self.assertNotRegex(src, r"sk-[A-Za-z0-9]{20,}")
        self.assertIn("<你自己的 key>", src)   # 默认值必须是占位符


if __name__ == "__main__":
    unittest.main(verbosity=2)
