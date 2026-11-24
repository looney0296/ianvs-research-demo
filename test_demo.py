from datetime import date
import unittest

from demo import OPEN_DAY, QUOTES, SIGNAL_DAY, bars, example_inputs, plan_for_session
from ianvs3_core import IANVS3_META_KEY, Policy, compute_close_decision


class CloseDecisions(unittest.TestCase):
    def setUp(self):
        self.reference, self.risk = example_inputs()
        self.account = {"holdings": {}, "cash": 10_000, "total_equity": 10_000}
        self.cycle = {}

    def decision(self, reference=None, risk=None):
        return compute_close_decision(
            reference_df=self.reference if reference is None else reference,
            risk_df=self.risk if risk is None else risk,
            snapshot={"meta": {IANVS3_META_KEY: self.cycle}}, broker_state=self.account,
            us_market_date=SIGNAL_DAY, policy=Policy(),
        )

    def test_deep_rsi_adjusts_first_dip_weight_without_mutating_state(self):
        result = self.decision()
        self.assertEqual(result["action"], "IANVS3_DIP1")
        self.assertEqual(result["execution_directives"]["target_weight"], Policy().dip_target_deep_rsi_bonus)
        self.assertEqual(self.cycle, {})

    def test_stop_buy_zone_blocks_second_dip(self):
        self.cycle.update(dip1_used=True, basis_price=66, base_shares=10)
        self.account = {"holdings": {"RISK": {"quantity": 10, "price": 48, "cost_basis": 66}},
                        "cash": 500, "total_equity": 980}
        reference = bars([100.0] * 19 + [55.0], highs=[100.0] * 20)
        self.assertIsNone(self.decision(reference=reference)["action"])

    def test_stale_input_is_rejected(self):
        with self.assertRaisesRegex(RuntimeError, "stale or misaligned"):
            self.decision(reference=self.reference.iloc[:-1])

    def test_short_aligned_history_is_rejected(self):
        with self.assertRaisesRegex(RuntimeError, "aligned"):
            self.decision(reference=self.reference.iloc[-3:])

    def test_same_day_and_late_execution_are_blocked(self):
        for wrong_day in (SIGNAL_DAY, date(2026, 1, 13)):
            with self.subTest(wrong_day=wrong_day), self.assertRaisesRegex(ValueError, "next session"):
                plan_for_session(intent=self.decision(), signal_date=SIGNAL_DAY, next_session=OPEN_DAY,
                                 session=wrong_day, account=self.account, quotes=QUOTES, reserve_bps=20)


if __name__ == "__main__":
    unittest.main()
