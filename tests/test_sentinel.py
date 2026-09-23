"""Sentinel alert building with a mocked graph. Run: PYTHONPATH=src python -m unittest tests.test_sentinel"""
import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import sentinel  # noqa: E402

RING_DEV = "SM-G935F Build/NRD90M | Android 7.0 | chrome 62.0 for android | 1920x1080"
COMMON_DEV = "Windows | Windows 10 | chrome 63.0 | 1920x1080"
PACK_CARD = "C13487-K1"  # in dataset/case_pack.csv


def v(vid, **attrs):
    return {"v_id": vid, "v_type": "X", "attributes": attrs}


def ring_card(cid, last, txns, anon=True, n_new=1):
    return v(cid, **{"@n": len(txns), "@n_new": n_new, "@amt": 100.0, "@first": "2016-12-02 10:00:00",
                     "@last": last, "@txns": txns, "@proxy": ["IP_PROXY:ANONYMOUS"] if anon else [""], "@cases": []})


def txn(tid, ts, score, amount=50.0):
    return v(tid, id=tid, ts=ts, amount=amount, channel="online", model_score=score)


class FakeGraph:
    """Answers run_query by query name; records every call."""

    def __init__(self, scan_devices=(), neighbors=None, near=(), history=None):
        self.scan_devices, self.neighbors, self.near, self.history = list(scan_devices), neighbors or {}, list(near), history or {}
        self.calls = []

    def __call__(self, name, params=None):
        self.calls.append((name, params))
        if name == "device_ring_scan":
            return {"devices": self.scan_devices}
        if name == "device_neighbors":
            return self.neighbors[params["device_id"]]
        if name == "near_threshold_scan":
            return {"cards": self.near}
        if name == "card_history":
            rows = self.history.get(params["card_id"], [])
            return {"txns": [r for r in rows if params["t_from"] <= r["attributes"]["ts"] <= params["t_to"]]}
        raise AssertionError(name)


def ring_graph():
    ring = [ring_card("C00001-K1", "2016-12-05 09:00:00", ["9001"]),
            ring_card("C00002-K1", "2016-12-06 10:00:00", ["9002", "9003"]),
            ring_card(PACK_CARD, "2016-12-07 11:00:00", ["9004"])]  # latest, but in the case pack
    return FakeGraph(
        scan_devices=[v(COMMON_DEV, **{"@new_cards": [f"C{i:05d}-K1" for i in range(100, 300)], "@proxies": [""]}),
                      v(RING_DEV, **{"@new_cards": ["C00001-K1", "C00002-K1", PACK_CARD],
                                     "@proxies": ["IP_PROXY:ANONYMOUS"]})],
        neighbors={RING_DEV: {"ever_txns": 5, "ever_cards": 4, "cards": ring}},
        history={"C00002-K1": [txn("9002", "2016-12-06 09:30:00", 0.9), txn("9003", "2016-12-06 10:00:00", 0.95)]})


class WindowsTest(unittest.TestCase):
    def test_rolling_windows_cover_period(self):
        w = sentinel.windows()
        self.assertEqual(w[0][0], sentinel.START)
        self.assertEqual(w[-1][1], sentinel.END)
        self.assertTrue(all((b - a).days < 30 for a, b in w))
        self.assertTrue(all(w[i + 1][0] <= w[i][1] for i in range(len(w) - 1)))  # overlapping, no gaps


class RingTest(unittest.TestCase):
    def test_common_profile_dropped_ring_confirmed(self):
        g = ring_graph()
        with mock.patch.object(sentinel.mcp_tools, "run_query", g):
            devs = sentinel.ring_candidates()
            self.assertEqual([d["id"] for d in devs], [RING_DEV])  # 200-card profile is a population, not a ring
            alerts = sentinel.ring_alerts(devs, sentinel.case_pack_cards())
        self.assertEqual(len(alerts), 1)
        a = alerts[0]
        self.assertEqual(a["card_id"], "C00002-K1")  # most recent ring card that is not in the case pack
        self.assertEqual(a["flagged_txn_id"], "9003")
        self.assertIn(PACK_CARD, a["trigger_text"])
        self.assertIn(RING_DEV, a["trigger_text"])
        row = sentinel.case_row(a, 1)
        self.assertEqual(row, {"case_id": "SEN-001", "opened_at": "2016-12-06 12:00:00",
                               "trigger_type": "analyst_request", "trigger_text": a["trigger_text"],
                               "flagged_txn_id": "9003", "card_id": "C00002-K1", "customer_id": "C00002",
                               "risk_score": ""})

    def test_widely_used_profile_is_not_a_ring(self):
        g = ring_graph()
        g.neighbors[RING_DEV]["ever_cards"] = 500  # 3 new cards out of 500 ever: common device
        with mock.patch.object(sentinel.mcp_tools, "run_query", g):
            self.assertEqual(sentinel.ring_alerts(sentinel.ring_candidates(), set()), [])

    def test_anonymous_devices_probed_first(self):
        plain = v("P", **{"@new_cards": ["A", "B", "C", "D", "E"], "@proxies": [""]})
        anon = v("Q", **{"@new_cards": ["F", "G", "H"], "@proxies": ["IP_PROXY:ANONYMOUS"]})
        with mock.patch.object(sentinel.mcp_tools, "run_query", FakeGraph(scan_devices=[plain, anon])):
            self.assertEqual([d["id"] for d in sentinel.ring_candidates()], ["Q", "P"])


class StructuringTest(unittest.TestCase):
    def near(self, cid, times):
        return v(cid, **{"@txns": [str(8000 + i) for i in range(len(times))], "@times": times, "@amt": 1400.0})

    def test_within_hour_only(self):
        g = FakeGraph(near=[
            self.near("C00010-K1", ["2016-11-20 10:40:00", "2016-11-20 10:00:00", "2016-11-20 10:20:00"]),
            self.near("C00011-K1", ["2016-11-20 10:00:00", "2016-11-20 12:00:00", "2016-11-20 14:00:00"]),
            self.near(PACK_CARD, ["2016-11-20 10:00:00", "2016-11-20 10:01:00", "2016-11-20 10:02:00"])])
        with mock.patch.object(sentinel.mcp_tools, "run_query", g):
            alerts = sentinel.structuring_alerts(sentinel.case_pack_cards())
        self.assertEqual([a["card_id"] for a in alerts], ["C00010-K1"])
        self.assertEqual(alerts[0]["flagged_txn_id"], "8000")  # latest by time, not by list order
        self.assertEqual(alerts[0]["last_ts"], "2016-11-20 10:40:00")
        self.assertEqual(g.calls[0][1]["lo"], 450)
        self.assertEqual(g.calls[0][1]["min_txns"], 3)


class ScoreTest(unittest.TestCase):
    def test_burst_of_high_scores(self):
        g = FakeGraph(history={
            "C00020-K1": [txn("7001", "2016-12-01 10:00:00", 0.97, 250.0), txn("7002", "2016-12-02 09:00:00", 0.92),
                          txn("7003", "2016-12-20 09:00:00", 0.95), txn("7004", "2016-12-01 08:00:00", 0.10)],
            "C00021-K1": [txn("7101", "2016-12-01 10:00:00", 0.99)],  # single high score: no alert
            "C00022-K1": [txn("7201", "2016-12-01 10:00:00", 0.50), txn("7202", "2016-12-01 11:00:00", 0.60)]})
        with mock.patch.object(sentinel.mcp_tools, "run_query", g):
            alerts = sentinel.score_alerts(["C00020-K1", "C00021-K1", "C00022-K1"])
        self.assertEqual(len(alerts), 1)
        a = alerts[0]
        self.assertEqual((a["card_id"], a["flagged_txn_id"], a["last_ts"]), ("C00020-K1", "7001", "2016-12-02 09:00:00"))
        self.assertNotIn("7003", a["trigger_text"])  # outside the 48 h burst

    def test_probe_cap(self):
        g = FakeGraph()
        with mock.patch.object(sentinel.mcp_tools, "run_query", g):
            sentinel.score_alerts([f"C{i:05d}-K1" for i in range(50)])
        self.assertEqual(len(g.calls), sentinel.SCORE_PROBES)


class SweepTest(unittest.TestCase):
    def test_sweep_order_dedupe_and_cap(self):
        g = ring_graph()
        g.near = [v("C00002-K1", **{"@txns": ["1", "2", "3"], "@amt": 1400.0,
                                    "@times": ["2016-11-20 10:00:00", "2016-11-20 10:01:00", "2016-11-20 10:02:00"]})]
        with mock.patch.object(sentinel.mcp_tools, "run_query", g):
            alerts = sentinel.sweep()
            self.assertEqual([(a["source"], a["card_id"]) for a in alerts],
                             [("device_ring", "C00002-K1")])  # already alerted card is not re-raised
            self.assertEqual(len(sentinel.sweep(max_alerts=0)), 0)
        scanned = {p["card_id"] for n, p in g.calls if n == "card_history" and p["t_from"] == "2016-11-01 00:00:00"}
        self.assertEqual(scanned, {"C00001-K1"})  # model-score pool skips case-pack and alerted cards

    def test_run_writes_outputs(self):
        answer = {"case": {"verdict": "fraud", "pattern": "undocumented", "fraud_probability": 0.9, "exposure_usd": 150.0},
                  "next_best_actions": {"final": [{"action": "CREATE_CASE", "route": "auto", "reason": "R6"}]}}
        fake_agent = types.ModuleType("hhg.agent")
        fake_agent.investigate = mock.Mock(return_value=(answer, {"steps": []}))
        alert = {"source": "structuring", "card_id": "C00010-K1", "flagged_txn_id": "8000",
                 "last_ts": "2016-11-20 10:40:00", "signal": "3 online txns", "trigger_text": "t"}
        with tempfile.TemporaryDirectory() as d, mock.patch.object(sentinel, "OUT", Path(d)), \
                mock.patch.dict(sys.modules, {"hhg.agent": fake_agent}), mock.patch("hhg.agent", fake_agent, create=True):
            sentinel.run([alert])
            row = fake_agent.investigate.call_args[0][0]
            self.assertEqual(row["opened_at"], "2016-11-20 12:40:00")
            self.assertEqual(fake_agent.investigate.call_args[1], {"write_graph": True})
            self.assertEqual(json.loads((Path(d) / "SEN-001.json").read_text()), answer)
            self.assertTrue((Path(d) / "traces" / "SEN-001.json").exists())
            summary = (Path(d) / "SUMMARY.md").read_text()
            self.assertIn("| SEN-001 | structuring | C00010-K1 | 3 online txns | fraud | undocumented | 0.90 | $150.00 | "
                          "CREATE_CASE (auto) |", summary)


if __name__ == "__main__":
    unittest.main()
