"""Offline unit tests (no PowerContext server required).

Run:  python tests/test_unit.py
These verify pure logic: session encoding, entry grouping, deterministic
checklist (never invents progress), token redaction, and honest failure
mapping when the server is unreachable.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import continuation as C
from config import redact
from powercontext_client import PowerContextClient, PowerContextUnavailable


ISO_A = "2026-11-14T09:00:00+08:00"
ISO_B = "2026-11-15T09:30:00+08:00"


class TestEncode(unittest.TestCase):
    def test_skips_empty_fields(self):
        writes = C.encode_session(ISO_A, {"progress": "做了A", "attempt": "", "problem": "", "next": "换电池"})
        kinds = [w["kind"] for w in writes]
        self.assertEqual(kinds, ["progress", "next"])
        self.assertTrue(writes[0]["text"].startswith(ISO_A + C.SEP))
        self.assertIn("做了A", writes[0]["text"])


class TestGroup(unittest.TestCase):
    def _entries(self):
        return [
            {"artifact": {"family": "atomic-memory", "artifact_id": "art1", "revision": 1},
             "kind": "progress", "text": ISO_A + C.SEP + "A组完成", "state": "active"},
            {"artifact": {"family": "atomic-memory", "artifact_id": "art2", "revision": 1},
             "kind": "next", "text": ISO_A + C.SEP + "换电池后补采", "state": "active"},
            {"artifact": {"family": "atomic-memory", "artifact_id": "art3", "revision": 1},
             "kind": "problem", "text": ISO_A + C.SEP + "B组传感器故障", "state": "active"},
        ]

    def test_group_and_order(self):
        sessions = C.group_entries(self._entries())
        self.assertEqual(len(sessions), 1)
        s = sessions[0]
        self.assertEqual(s["session"], ISO_A)
        self.assertEqual(s["fields"]["progress"], "A组完成")
        self.assertEqual(s["fields"]["next"], "换电池后补采")
        self.assertEqual(s["citations"][0]["artifact_id"], "art1")

    def test_newest_first(self):
        entries = self._entries() + [
            {"artifact": {"family": "atomic-memory", "artifact_id": "art9", "revision": 1},
             "kind": "next", "text": ISO_B + C.SEP + "已补采完成", "state": "active"}]
        sessions = C.group_entries(entries)
        self.assertEqual(sessions[0]["session"], ISO_B)


class TestChecklist(unittest.TestCase):
    def test_no_history(self):
        cl = C.build_checklist("目标", [])
        self.assertFalse(cl["has_history"])
        self.assertEqual(cl["items"], [])

    def test_next_and_problem_and_goal(self):
        sessions = C.group_entries(TestGroup()._entries())
        cl = C.build_checklist("比较两种浇水方案", sessions)
        texts = [i["text"] for i in cl["items"]]
        joined = "\n".join(texts)
        self.assertTrue(any(i["source"] == "project" for i in cl["items"]))
        self.assertIn("换电池后补采", joined)
        self.assertIn("待解决：B组传感器故障", joined)
        # 已完成项被标为"勿重复"，不会被当成下一步行动
        done = [i for i in cl["items"] if i["source"] == "progress"]
        self.assertTrue(done[0]["text"].startswith("上次已完成"))
        # 每条 next 带来源引用
        nxt = [i for i in cl["items"] if i["source"] == "next"][0]
        self.assertEqual(nxt["cite"]["artifact_id"], "art2")

    def test_does_not_claim_b_group_done(self):
        # 关键验收语义：记录里没说 B 组完成，清单不得出现"B组已完成"
        sessions = C.group_entries(TestGroup()._entries())
        cl = C.build_checklist("目标", sessions)
        joined = "\n".join(i["text"] for i in cl["items"])
        self.assertNotIn("B组已完成", joined)
        self.assertNotIn("B 组已完成", joined)


class TestSecurity(unittest.TestCase):
    def test_redact_bearer(self):
        s = "outbound Authorization:Bearer super-secret-token end"
        self.assertNotIn("super-secret-token", redact(s))
        self.assertIn("[REDACTED]", redact(s))


class TestClientFailure(unittest.TestCase):
    def test_unreachable_raises_unavailable_not_success(self):
        # 指向一个几乎必然关闭的端口：必须抛"不可用"，而不是伪造成功
        c = PowerContextClient("http://127.0.0.1:1", token="x")
        with self.assertRaises(PowerContextUnavailable):
            c.create_scope("t", "s", "idem")

    def test_error_message_has_no_token(self):
        c = PowerContextClient("http://127.0.0.1:1", token="SECRET-TOKEN")
        try:
            c.list_entries("scp_x")
        except PowerContextUnavailable as e:
            self.assertNotIn("SECRET-TOKEN", str(e))


if __name__ == "__main__":
    unittest.main(verbosity=2)
