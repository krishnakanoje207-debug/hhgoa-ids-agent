"""analytics.assess on small synthetic cards (default calibration, no calibration.json)."""
import unittest
from datetime import date

from hhg import analytics

CAL = analytics.load_calibration("does/not/exist.json")
RING = "SM-G935F Build/NRD90M | Android 7.0 | chrome 62.0 for android | 1920x1080"
HOME = "iOS Device | iOS 11.1 | safari 11.0 | 2436x1125"


def tx(i, ts, amount, ms=0.1, ch="online", dev="", st="", proxy=""):
    return {"id": i, "ts": ts, "amount": amount, "product": "W", "channel": ch, "risk": 0.5, "addr1": "204.0",
            "addr2": "87.0", "dist1": 0, "p_email": "gmail.com", "r_email": "", "m_flags": "", "c1": 1, "c13": 1,
            "d1": 0, "d15": 0, "model_score": ms, "device": dev, "dev_status": st, "proxy": proxy}


def ring_ctx(own_txns):
    others = [{"id": f"C0000{k}-K1", "n_new": 1, "txns": [f"900000{k}"], "proxy": ["IP_PROXY:ANONYMOUS"], "cases": []}
              for k in range(3)]
    return {"device_id": RING, "ever_cards": 20, "cards": [{"id": "C11111-K1", "n_new": 1, "txns": own_txns,
                                                            "proxy": [], "cases": []}] + others}


class RingTest(unittest.TestCase):
    TXNS = [tx("1000001", "2016-12-01 10:00:00", 40.0, dev=HOME, st="Found"),
            tx("1000002", "2016-12-09 09:00:00", 80.0, ms=0.95, dev=HOME, st="Found"),  # high score, not on ring
            tx("1000003", "2016-12-09 10:00:00", 30.0, ms=0.0, dev=RING, st="New", proxy="IP_PROXY:ANONYMOUS"),
            tx("1000004", "2016-12-09 11:00:00", 55.0, ms=0.0, dev=RING, st="New", proxy="IP_PROXY:ANONYMOUS"),
            tx("1000005", "2016-12-09 12:00:00", 60.0, ms=0.3, dev=RING, st="New", proxy="IP_PROXY:ANONYMOUS"),
            tx("1000006", "2016-12-11 12:00:00", 70.0, ms=0.0, dev=RING, st="New")]  # after opening

    def test_ring_episode_is_card_txns_on_ring_device(self):
        ctx = ring_ctx(["1000003", "1000004", "1000005"])
        a = analytics.assess(self.TXNS, "1000005", "2016-12-10 00:00:00", "risk_score", device_ctx=ctx, cal=CAL)
        self.assertEqual(a["episode"]["affected_txn_ids"], ["1000003", "1000004", "1000005"])
        self.assertEqual(a["pattern"], "undocumented")
        self.assertFalse(a["signals"]["new_phone_signature"])
        self.assertTrue(a["signals"]["ring"])
        self.assertEqual(a["connected_card_ids"], ["C00000-K1", "C00001-K1", "C00002-K1"])

    def test_ring_detail_has_anon_cards(self):
        cards, detail = analytics._ring(ring_ctx(["1000003"]), {"1000003"})
        self.assertEqual(len(cards), 3)
        self.assertEqual(detail["anon_cards"], 3)


class SharedOriginTest(unittest.TestCase):
    DEV = "Windows | other | chrome 61.0 | 1280x720"
    OPENED = "2016-12-01 22:28:53"

    def other(self, i, card, ts, r_email="gmail.com"):
        return dict(tx(i, ts, 100.0, dev=self.DEV, st="New"), p_email="verizon.net", r_email=r_email, card_id=card)

    def run_case(self, others, ever_cards=5, ms=0.95):
        flag = dict(tx("3000003", "2016-12-01 17:28:53", 99.92, ms=ms, dev=self.DEV, st="New"),
                    p_email="verizon.net", r_email="gmail.com")
        ctx = {"device_id": self.DEV, "ever_cards": ever_cards, "cards": [], "recent_txns": others}
        return analytics.assess([tx("3000001", "2016-11-20 10:00:00", 40.0), flag], "3000003", self.OPENED,
                                "risk_score", device_ctx=ctx, customer_ctx={"card_id": "C07987-K2"}, cal=CAL)

    def test_fires_on_rare_device_with_same_email_pair(self):
        base = self.run_case([])
        a = self.run_case([self.other("3000002", "C11309-K1", "2016-11-29 17:45:09"),
                           self.other("3000004", "C06224-K2", "2016-12-01 18:00:57")])
        self.assertEqual(a["shared_origin"], {"kind": "device", "id": self.DEV, "card_ids": ["C06224-K2", "C11309-K1"]})
        self.assertEqual(a["connected_card_ids"], ["C06224-K2", "C11309-K1"])
        self.assertEqual(a["connected_device_profiles"], [self.DEV])
        claim = next(e for e in a["prosecution"] if "purchaser/recipient email" in e["claim"])
        self.assertEqual(claim["entity_ids"], ["C06224-K2", "C11309-K1", "3000002", "3000004"])
        self.assertTrue(claim["ref"].startswith("query:device_neighbors("))
        for k in ("fraud_probability", "verdict", "independent_evidence", "features"):
            self.assertEqual(a[k], base[k])

    def test_not_fired(self):
        ok = [self.other("3000002", "C11309-K1", "2016-11-29 17:45:09"),
              self.other("3000004", "C06224-K2", "2016-12-01 18:00:57")]
        cases = {"common device": (ok, 21, 0.95),
                 "different email pair": ([ok[0], self.other("3000004", "C06224-K2", "2016-12-01 18:00:57", "yahoo.com")], 5, 0.95),
                 "card outside 7 days": ([self.other("3000002", "C11309-K1", "2016-11-24 17:00:00"), ok[1]], 5, 0.95),
                 "after opening": ([ok[0], self.other("3000004", "C06224-K2", "2016-12-01 23:00:00")], 5, 0.95),
                 "evidence leans legitimate": (ok, 5, 0.05)}
        for name, (others, ever, ms) in cases.items():
            with self.subTest(name):
                a = self.run_case(others, ever, ms)
                self.assertIsNone(a["shared_origin"])
                self.assertEqual(a["connected_card_ids"], [])


class CardTestingShapeTest(unittest.TestCase):
    def test_closed_case_shape_without_1h_run(self):
        # online-only episode of 5 txns, one < $5 and one >= $20, but no 3 small auths within an hour
        txns = [tx("2000001", "2016-12-09 08:00:00", 3.0, ms=0.9),
                tx("2000002", "2016-12-09 10:00:00", 15.0, ms=0.9),
                tx("2000003", "2016-12-09 12:00:00", 12.0, ms=0.9),
                tx("2000004", "2016-12-09 14:00:00", 25.0, ms=0.9),
                tx("2000005", "2016-12-09 16:00:00", 60.0, ms=0.9)]
        a = analytics.assess(txns, "2000005", "2016-12-10 00:00:00", "risk_score", cal=CAL)
        self.assertFalse(a["signals"]["card_testing_sequence_1h"])
        self.assertTrue(a["card_testing"])
        self.assertEqual(a["pattern"], "card_testing")
        claim = next(e for e in a["prosecution"] if "online authorization" in e["claim"])
        self.assertIn("in one online episode", claim["claim"])
        self.assertEqual(claim["entity_ids"], ["2000001", "2000004", "2000005"])


class AccountHistoryTest(unittest.TestCase):
    OPENED = "2016-12-05 01:55:28"
    OPEN_DAY = date(2016, 9, 13)  # account first seen: txn date minus D1

    def acct(self, i, ts, amount=60.0, ms=0.05, addr1="444.0", shift=0, risk=0.5):
        d1 = (date.fromisoformat(ts[:10]) - self.OPEN_DAY).days + shift
        return dict(tx(i, ts, amount, ms=ms, ch="in_person"), addr1=addr1, d1=d1, risk=risk)

    def history(self, **kw):
        days = ["2016-10-11", "2016-10-18", "2016-10-26", "2016-11-08", "2016-11-19", "2016-11-26"]
        return [self.acct(f"34000{k}", f"{d} 20:00:00", **kw) for k, d in enumerate(days)]

    def run_case(self, earlier, case_txns=None, ms=0.95, risk=0.61):
        flag = self.acct("3514030", "2016-12-04 19:55:28", 77.07, ms=ms, risk=risk)
        ctx = {"card_id": "C12382-K1"}
        if case_txns is not None:
            ctx["case_txns"] = case_txns
        return analytics.assess(earlier + [flag], "3514030", self.OPENED, "risk_score", customer_ctx=ctx, cal=CAL)

    def test_clean_account_caps_probability(self):
        self.assertEqual(self.run_case(self.history())["fraud_probability"], 0.95)  # cases not read: no signal
        a = self.run_case(self.history(), {})
        self.assertTrue(a["signals"]["clean_account"])
        self.assertEqual(a["fraud_probability"], 0.15)
        claim = next(e for e in a["defence"] if "underlying account" in e["claim"])
        self.assertEqual(claim["entity_ids"], [r["id"] for r in self.history()])
        self.assertTrue(claim["ref"].startswith("query:card_history("))
        # a cleared case on one account txn also breaks the clean history
        a = self.run_case(self.history(), {"340003": ("CC-0100", "cleared", "2016-11-10 00:00:00")})
        self.assertFalse(a["signals"]["clean_account"])
        self.assertEqual(a["fraud_probability"], 0.95)

    def test_fraud_account_raises_probability(self):
        cases = {"340004": ("CC-5521", "confirmed_fraud", "2016-11-21 13:33:09")}
        a = self.run_case(self.history(), cases, ms=0.3)
        self.assertEqual(a["fraud_probability"], 0.9)
        self.assertEqual(a["signals"]["fraud_account_cases"], ["CC-5521"])
        claim = next(e for e in a["prosecution"] if "CC-5521" in e["claim"])
        self.assertEqual(claim["entity_ids"], ["CC-5521", "340004"])
        # bank risk score below 0.5: evidence only (41-68% fraud in the audit), probability unchanged
        a = self.run_case(self.history(risk=0.4), cases, ms=0.3, risk=0.4)
        self.assertEqual(a["fraud_probability"], 0.3)
        self.assertTrue(any("CC-5521" in e["claim"] for e in a["prosecution"]))

    def test_other_account_ignored(self):
        cases = {"340004": ("CC-5521", "confirmed_fraud", "2016-11-21 13:33:09")}
        for name, kw in {"other billing region": {"addr1": "433.0"}, "open date 2 days off": {"shift": 2}}.items():
            with self.subTest(name):
                a = self.run_case(self.history(**kw), cases, ms=0.3)
                self.assertEqual(a["signals"]["account_prior_txns"], 0)
                self.assertFalse(a["signals"]["clean_account"])
                self.assertEqual(a["fraud_probability"], 0.3)
        a = self.run_case(self.history(shift=1), {}, ms=0.95)  # within a day: same account
        self.assertEqual(a["fraud_probability"], 0.15)

    def test_case_opened_after_opening_ignored(self):
        a = self.run_case(self.history(), {"340004": ("CC-5521", "confirmed_fraud", "2016-12-06 00:00:00")}, ms=0.3)
        self.assertEqual(a["signals"]["fraud_account_cases"], [])
        self.assertFalse(any("CC-5521" in e["claim"] for e in a["prosecution"]))
        self.assertLessEqual(a["fraud_probability"], 0.3)


if __name__ == "__main__":
    unittest.main()
