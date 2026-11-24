"""Run the published IANVS3 excerpts with fictional daily bars and quotes."""
from datetime import date

import pandas as pd

from ianvs3_core import (IANVS3_META_KEY, Policy, advance_cycle_state_after_execution,
                         build_execution_plan, compute_close_decision)

SIGNAL_DAY = date(2026, 1, 9)
OPEN_DAY = date(2026, 1, 12)
QUOTES = {("RISK", "buy"): 50.0, ("RISK", "sell"): 49.5,
          ("DEFENSIVE", "buy"): 100.0, ("DEFENSIVE", "sell"): 100.0}


def bars(values, *, session=SIGNAL_DAY, highs=None):
    index = pd.bdate_range(end=session, periods=len(values))
    return pd.DataFrame({"Oprc": values, "Hprc": highs if highs is not None else values,
                         "Lprc": values, "Prpr": values}, index=index)


def example_inputs():
    return (bars([100.0] * 19 + [90.0], highs=[100.0] * 20),
            bars([66.0] * 14 + [63.0, 60.0, 57.0, 54.0, 51.0, 48.0]))


def plan_for_session(*, intent, signal_date, next_session, session, account, quotes, reserve_bps):
    """The public harness takes the intended session as an explicit input."""
    if session != next_session or session <= signal_date:
        raise ValueError("execution is allowed only on the scheduled next session")
    return build_execution_plan(quotes=quotes, broker_state=account,
                                intent=intent, reserve_bps=reserve_bps)


def main():
    reference, risk = example_inputs()
    cycle = {}
    account = {"holdings": {"DEFENSIVE": {"quantity": 100, "price": 100}},
               "cash": 1_000, "total_equity": 11_000}
    intent = compute_close_decision(
        reference_df=reference, risk_df=risk, snapshot={"meta": {IANVS3_META_KEY: cycle}},
        broker_state=account, us_market_date=SIGNAL_DAY, policy=Policy(),
    )
    plan = plan_for_session(intent=intent, signal_date=SIGNAL_DAY, next_session=OPEN_DAY,
                            session=OPEN_DAY, account=account, quotes=QUOTES, reserve_bps=20)
    print(f"{SIGNAL_DAY} close: {intent['action']} {intent['execution_directives']}")
    print(f"{OPEN_DAY} open plan: {plan['sell_ops']} → {plan['buy_ops']}")
    print(f"Cycle before confirmation: {cycle}")
    # Independently supplied fictional account snapshot, not an order or a fill report.
    after = {"holdings": {"RISK": {"quantity": 92, "cost_basis": 50.1},
                          "DEFENSIVE": {"quantity": 63, "price": 100}},
             "cash": 88.0, "total_equity": 10_988.0, "regime": "RISK_ON"}
    confirmed = advance_cycle_state_after_execution(
        previous_state=cycle, action=intent["action"], action_note=intent["action_note"],
        broker_state_after=after,
    )
    print(f"Cycle after synthetic confirmation: dip1_used={confirmed['dip1_used']}, "
          f"base_shares={confirmed['base_shares']:.0f}, basis={confirmed['basis_price']:.2f}")


if __name__ == "__main__":
    main()
