import unittest

from demo import Bar, simulate


class SimulationTests(unittest.TestCase):
    def setUp(self):
        self.bars = (Bar("2026-01-05", 100, 98), Bar("2026-01-06", 95, 99),
                     Bar("2026-01-07", 102, 104))

    def test_signal_trades_next_open_only(self):
        result = simulate(self.bars, (1, None, None))
        self.assertEqual(len(result.fills), 1)
        self.assertEqual((result.fills[0].session, result.fills[0].opening),
                         ("2026-01-06", 95))
        self.assertEqual(result.closing_equity[0], 10_000)

    def test_terminal_signal_has_no_fill(self):
        self.assertEqual(simulate(self.bars, (None, None, 1)).fills, ())

    def test_staged_weights_use_post_cost_equity(self):
        result = simulate(self.bars, (0.5, 0.25, None))
        buy, sell = result.fills
        self.assertAlmostEqual(buy.notional / (10_000 - buy.fee), 0.5)
        risky = buy.notional / 95 * 102
        cash = 10_000 - buy.notional - buy.fee
        self.assertAlmostEqual((risky + sell.notional) / (risky + cash - sell.fee), 0.25)
        self.assertLess(sell.notional, 0)

    def test_fee_charged_on_both_buy_and_sell(self):
        result = simulate(self.bars, (1, 0, None))
        for fill in result.fills:
            self.assertAlmostEqual(fill.fee, abs(fill.notional) * 0.0006)
        self.assertGreater(result.fills[1].fee, 0)

    def test_rejects_wrong_number_of_signals(self):
        with self.assertRaises(ValueError):
            simulate(self.bars, (None,))
