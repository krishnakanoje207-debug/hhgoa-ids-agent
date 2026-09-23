"""Live smoke test of the agent's TigerGraph MCP path. Run: set HHG_LIVE=1, python -m unittest tests.test_mcp_live"""
import os
import random
import time
import unittest

LIVE = os.environ.get("HHG_LIVE") == "1"
CASE, CARD = "TEST-MCP-1", "C04597-K2"


@unittest.skipUnless(LIVE, "set HHG_LIVE=1 to run against Savanna")
class TestMCPLive(unittest.TestCase):
    def setUp(self):
        from hhg import mcp_tools
        self.m = mcp_tools
        self.m.reset_log()

    def query(self, name, params, keys):
        """Installed query result, or the 'not valid <Type> vertex' error while data is not loaded yet."""
        try:
            r = self.m.run_query(name, params)
        except self.m.MCPError as e:
            self.assertIn("is not valid", str(e))
            return None
        self.assertTrue(set(keys) <= set(r), r)
        return r

    def test_smoke(self):
        m = self.m
        self.assertEqual(set(m.list_tools()), {f"tigergraph__{t}" for t in m.ALLOWED_TOOLS})
        self.assertEqual(m.call("get_graph_schema")["graph_name"], "FraudGraph")
        with self.assertRaises(m.MCPError):  # withheld at dispatch, not just unlisted
            m.call("delete_node", vertex_type="AgentCase", vertex_id="NO-SUCH-ID")

        self.query("customer_cases", {"customer_id": "C04597"}, ["cards", "cases"])
        self.query("card_history", {"card_id": CARD, "t_from": "2016-07-01 00:00:00",
                                    "t_to": "2016-12-31 23:59:59"}, ["txns"])

        try:
            m.call("get_node", vertex_type="Card", vertex_id=CARD)
            card_existed = True
        except m.MCPError:
            card_existed = False
        try:
            m.upsert_case({"id": CASE, "case_id": "HHG-TEST", "created_at": "2026-09-23 10:00:00", "status": "open",
                           "verdict": "uncertain", "pattern": "none", "probability": 0.5, "exposure": 12.5,
                           "summary": "mcp smoke test", "answer_json": "{}"}, [("ON_CARD", CARD)])
            got = m.call("get_node", vertex_type="AgentCase", vertex_id=CASE)
            self.assertEqual(got["attributes"]["summary"], "mcp smoke test")
            nb = m.call("get_neighbors", vertex_type="AgentCase", vertex_id=CASE)
            self.assertIn(CARD, [n["v_id"] for n in nb["neighbors"]])
            vec = [random.random() for _ in range(384)]
            m.upsert_case_embedding(CASE, vec)
            for _ in range(24):  # the vector index updates asynchronously (~70 s on Savanna)
                if CASE in m.run_query("similar_cases", {"qv": vec, "k": 1})["distances"]:
                    break
                time.sleep(5)
            self.assertIn(CASE, m.run_query("similar_cases", {"qv": vec, "k": 1})["distances"])
        finally:
            from hhg import config, tg
            g = config.TG_GRAPH
            tg._send("DELETE", f"/restpp/graph/{g}/vertices/AgentCase/{CASE}")
            if not card_existed:  # the edge upsert created an empty Card; remove it
                tg._send("DELETE", f"/restpp/graph/{g}/vertices/Card/{CARD}")

        self.assertEqual(m.calls, len(m.LOG))
        self.assertTrue(all({"tool", "args", "ms", "ok"} <= set(e) for e in m.LOG))


if __name__ == "__main__":
    unittest.main()
