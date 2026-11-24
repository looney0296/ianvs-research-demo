"""Original IANVS3 regression fixtures, with offline dependency injection."""
import unittest

from ianvs3_core import advance_cycle_state_after_execution, build_execution_plan



def test_advance_cycle_state_after_buy_uses_post_trade_position():
    state = advance_cycle_state_after_execution(
        previous_state={
            "basis_price": 0.0,
            "base_shares": 0.0,
            "dip1_used": False,
            "dip2_used": False,
            "tp1_used": False,
            "tp2_used": False,
            "last_confirmed_position": {"risk_qty": 0},
        },
        action="IANVS3_GC",
        action_note="gc buy",
        broker_state_after={
            "holdings": {"RISK": {"quantity": 200, "price": 40.0, "cost_basis": 45.0}},
            "cash": 100.0,
            "total_equity": 8_100.0,
            "regime": "RISK_ON",
        },
    )

    assert state["basis_price"] == 45.0
    assert state["base_shares"] == 200.0
    assert state["last_confirmed_position"]["risk_qty"] == 200


def test_advance_cycle_state_after_dip_buy_uses_added_position_qty():
    state = advance_cycle_state_after_execution(
        previous_state={
            "basis_price": 50.0,
            "base_shares": 100.0,
            "dip1_used": False,
            "dip2_used": False,
            "tp1_used": False,
            "tp2_used": False,
            "last_confirmed_position": {"risk_qty": 100},
        },
        action="IANVS3_DIP1",
        action_note="dip buy",
        broker_state_after={
            "holdings": {"RISK": {"quantity": 150, "price": 44.0, "cost_basis": 48.0}},
            "cash": 250.0,
            "total_equity": 6_850.0,
            "regime": "RISK_ON",
        },
    )

    assert state["basis_price"] == 48.0
    assert state["base_shares"] == 150.0
    assert state["dip1_used"] is True
    assert state["last_confirmed_position"]["risk_qty"] == 150


def test_target_weight_funds_risk_purchase():
    quotes = {
            ("RISK", "buy"): 50.0,
            ("RISK", "sell"): 49.5,
            ("DEFENSIVE", "buy"): 100.0,
            ("DEFENSIVE", "sell"): 100.0,
        }

    plan = build_execution_plan(
        quotes=quotes,
        reserve_bps=20.0,
        broker_state={
            "holdings": {"DEFENSIVE": {"quantity": 100, "price": 100.0, "cost_basis": 100.0}},
            "cash": 1_000.0,
            "total_equity": 11_000.0,
            "regime": "RISK_OFF",
        },
        intent={
            "action": "IANVS3_DIP1",
            "execution_directives": {"target_weight": 0.40},
        },
    )

    # Selling 34 covers the share price but leaves no room for execution costs.
    assert plan["sell_ops"] == [{"ticker": "DEFENSIVE", "qty": 35}]
    assert plan["buy_ops"] == [{"ticker": "RISK", "qty": 88}]


def test_sell_plan_freezes_defensive_quantity():
    quotes = {
            ("RISK", "buy"): 50.0,
            ("RISK", "sell"): 50.0,
            ("DEFENSIVE", "buy"): 100.0,
            ("DEFENSIVE", "sell"): 100.0,
        }
    plan = build_execution_plan(
        quotes=quotes,
        reserve_bps=20.0,
        broker_state={
            "holdings": {"RISK": {"quantity": 20, "price": 50.0}},
            "cash": 10.0,
            "total_equity": 1_010.0,
        },
        intent={"action": "IANVS3_DC", "execution_directives": {"shares_to_sell": 20}},
    )

    assert plan["sell_ops"] == [{"ticker": "RISK", "qty": 20}]
    assert plan["buy_ops"] == [{"ticker": "DEFENSIVE", "qty": 10}]

def load_tests(loader, standard_tests, pattern):
    return unittest.TestSuite(
        unittest.FunctionTestCase(case)
        for name, case in sorted(globals().items())
        if name.startswith("test_") and callable(case)
    )
