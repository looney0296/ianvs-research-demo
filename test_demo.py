from dataclasses import replace
from datetime import date
import unittest

from demo import Action, Close, Cycle, Intent, Position, Quotes, confirm, decide, plan_open

CLOSE = date(2026, 1, 9)
OPEN = date(2026, 1, 12)
FRAME = Close(CLOSE, CLOSE, CLOSE, 100, -0.10, 0, 0)
QUOTES = Quotes(50, 49.5, 100, 100)


class SignalTests(unittest.TestCase):
    def test_stale_reference_bar_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "stale"):
            decide(replace(FRAME, reference_session=date(2026, 1, 8)),
                   OPEN, Position(0, 100, 1000), Cycle())

    def test_exit_has_priority_over_profit_and_dips(self):
        frame = replace(FRAME, risk_close=250, previous_gap=0, trend_gap=-0.03)
        decision = decide(frame, OPEN, Position(18, 100, 0), Cycle(100, 18))
        self.assertEqual((decision.action, decision.size), (Action.TREND_RESET, 18))

    def test_second_dip_needs_confirmation_and_stop_zone_blocks_add(self):
        frame = replace(FRAME, reference_drawdown=-0.18)
        pos = Position(20, 60, 0)
        state = Cycle(100, 20)
        self.assertEqual(decide(frame, OPEN, pos, state).action, Action.FIRST_DIP)
        confirmed = confirm(state, Action.FIRST_DIP, 20, 100)
        self.assertEqual(decide(frame, OPEN, pos, confirmed).action, Action.ADD_TRANCHE)
        self.assertIsNone(decide(replace(frame, reference_drawdown=-0.40),
                                 OPEN, pos, confirmed))

    def test_profit_quantity_uses_confirmed_base_and_is_capped(self):
        frame = replace(FRAME, risk_close=130)
        self.assertEqual(decide(frame, OPEN, Position(11, 6, 0), Cycle(100, 20)).size, 8)
        self.assertEqual(decide(frame, OPEN, Position(3, 6, 0), Cycle(100, 20)).size, 3)

    def test_harvest_confirmation_and_reset(self):
        state = Cycle(100, 20, True, True)
        updated = confirm(state, Action.FIRST_HARVEST, 12, 100)
        self.assertTrue(updated.first_harvest)
        self.assertEqual(updated.base_shares, 20)
        self.assertEqual(confirm(updated, Action.TREND_RESET, 0, 0), Cycle())


class PlanningTests(unittest.TestCase):
    def test_cannot_plan_same_day_or_after_designated_session(self):
        order = Intent(CLOSE, OPEN, Action.FIRST_DIP, 0.25)
        for wrong_day in (CLOSE, date(2026, 1, 13)):
            with self.assertRaises(ValueError):
                plan_open(order, wrong_day, Position(0, 100, 1000), QUOTES, 10)

    def test_execution_reserve_requires_extra_defensive_share(self):
        pos = Position(0, 100, 1000)
        order = Intent(CLOSE, OPEN, Action.FIRST_DIP, 0.40)
        free = plan_open(order, OPEN, pos, QUOTES, 0)
        reserved = plan_open(order, OPEN, pos, QUOTES, 20)
        self.assertEqual((free.sell_defensive, reserved.sell_defensive, reserved.buy_risk),
                         (34, 35, 88))

    def test_add_tranche_is_not_a_target_weight(self):
        pos = Position(30, 100, 1000)
        target = plan_open(Intent(CLOSE, OPEN, Action.FIRST_DIP, 0.30), OPEN, pos, QUOTES, 10)
        add = plan_open(Intent(CLOSE, OPEN, Action.ADD_TRANCHE, 0.30), OPEN, pos, QUOTES, 10)
        self.assertGreater(add.buy_risk, target.buy_risk)

    def test_funding_limits_whole_share_order(self):
        order = Intent(CLOSE, OPEN, Action.TREND_ENTRY, 1)
        plan = plan_open(order, OPEN, Position(0, 0, 99), QUOTES, 10)
        self.assertEqual((plan.buy_risk, plan.sell_defensive), (1, 0))

    def test_full_exit_sizes_defensive_leg(self):
        order = Intent(CLOSE, OPEN, Action.TREND_RESET, 20)
        plan = plan_open(order, OPEN, Position(20, 0, 10), Quotes(50, 50, 100, 100), 20)
        self.assertEqual((plan.sell_risk, plan.buy_defensive), (20, 10))
