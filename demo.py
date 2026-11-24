"""Offline adaptation of IANVS3's staged signals and next-open planning."""
from dataclasses import dataclass, replace
from datetime import date
from enum import Enum, auto
from math import ceil, floor


class Action(Enum):
    TREND_ENTRY = auto()
    FIRST_DIP = auto()
    ADD_TRANCHE = auto()
    TREND_TOP_UP = auto()
    FIRST_HARVEST = auto()
    SECOND_HARVEST = auto()
    FINAL_HARVEST = auto()
    TREND_RESET = auto()


@dataclass(frozen=True)
class Policy:
    """Illustrative thresholds and sizes; not the private configuration."""

    early_dip: float = -0.07
    deep_dip: float = -0.16
    stop_buy: float = -0.32
    entry_gap: float = 0.02
    exit_gap: float = -0.02
    first_return: float = 0.20
    second_return: float = 0.55
    final_return: float = 0.90
    first_weight: float = 0.25
    add_weight: float = 0.20
    first_sale: float = 0.40
    second_sale: float = 0.30


@dataclass(frozen=True)
class Cycle:
    basis: float = 0.0
    base_shares: int = 0
    first_dip: bool = False
    second_dip: bool = False
    first_harvest: bool = False
    second_harvest: bool = False


@dataclass(frozen=True)
class Close:
    session: date
    risk_session: date
    reference_session: date
    risk_close: float
    reference_drawdown: float
    previous_gap: float
    trend_gap: float


@dataclass(frozen=True)
class Intent:
    signal_session: date
    execution_session: date
    action: Action
    size: float


@dataclass(frozen=True)
class Position:
    risk: int
    defensive: int
    cash: float


@dataclass(frozen=True)
class Quotes:
    risk_buy: float
    risk_sell: float
    defensive_buy: float
    defensive_sell: float


@dataclass(frozen=True)
class Plan:
    sell_risk: int = 0
    sell_defensive: int = 0
    buy_risk: int = 0
    buy_defensive: int = 0


BUYS = {Action.TREND_ENTRY, Action.FIRST_DIP, Action.ADD_TRANCHE, Action.TREND_TOP_UP}


def decide(frame: Close, next_session: date, position: Position, cycle: Cycle,
           policy: Policy = Policy()) -> Intent | None:
    """Consume already-calculated indicators, without changing cycle state."""
    if frame.session != frame.risk_session or frame.session != frame.reference_session:
        raise ValueError("stale or misaligned daily bars")
    if next_session <= frame.session:
        raise ValueError("execution session must follow the close signal")

    def intent(action: Action, size: float) -> Intent:
        return Intent(frame.session, next_session, action, size)

    entry = frame.previous_gap < policy.entry_gap <= frame.trend_gap
    exit_ = frame.previous_gap > policy.exit_gap >= frame.trend_gap
    gain = frame.risk_close / cycle.basis - 1 if cycle.basis > 0 else 0
    held = position.risk
    if held:
        if exit_:
            return intent(Action.TREND_RESET, held)
        if cycle.second_harvest and gain > policy.final_return:
            return intent(Action.FINAL_HARVEST, held)
        if not cycle.first_harvest and gain > policy.first_return:
            return intent(Action.FIRST_HARVEST, min(held, max(1, floor(cycle.base_shares * policy.first_sale))))
        if cycle.first_harvest and not cycle.second_harvest and gain > policy.second_return:
            return intent(Action.SECOND_HARVEST, min(held, max(1, floor(cycle.base_shares * policy.second_sale))))
    if not held and entry:
        return intent(Action.TREND_ENTRY, 1.0)
    if frame.reference_drawdown > policy.stop_buy:
        if frame.reference_drawdown <= policy.early_dip and not cycle.first_dip:
            return intent(Action.FIRST_DIP, policy.first_weight)
        if (frame.reference_drawdown <= policy.deep_dip and held
                and cycle.first_dip and not cycle.second_dip):
            return intent(Action.ADD_TRANCHE, policy.add_weight)
    if held and entry and (position.defensive or position.cash > 1):
        return intent(Action.TREND_TOP_UP, 1.0)
    return None


def plan_open(intent: Intent, session: date, position: Position,
              quotes: Quotes, reserve_bps: float) -> Plan:
    """Price whole-share legs on the designated session; never submit orders."""
    if session != intent.execution_session or session <= intent.signal_session:
        raise ValueError("not the intent's designated next session")
    if not 0 <= reserve_bps < 10_000 or min(
        quotes.risk_buy, quotes.risk_sell, quotes.defensive_buy, quotes.defensive_sell
    ) <= 0:
        raise ValueError("invalid quotes or execution reserve")
    reserve = reserve_bps / 10_000
    if intent.action in BUYS:
        held_value = position.risk * quotes.risk_sell
        equity = position.cash + held_value + position.defensive * quotes.defensive_sell
        budget = equity * intent.size
        if intent.action is not Action.ADD_TRANCHE:
            budget -= held_value
        requested = floor(max(budget, 0) / quotes.risk_buy)
        buy_cost = quotes.risk_buy * (1 + reserve)
        sell_proceeds = quotes.defensive_sell * (1 - reserve)
        shortfall = max(requested * buy_cost - position.cash, 0)
        funding_shares = min(position.defensive, ceil(shortfall / sell_proceeds))
        affordable = floor((position.cash + funding_shares * sell_proceeds) / buy_cost)
        return Plan(sell_defensive=funding_shares, buy_risk=min(requested, affordable))

    risk_to_sell = min(position.risk, max(0, floor(intent.size)))
    if position.risk and intent.action in {Action.FIRST_HARVEST, Action.SECOND_HARVEST}:
        risk_to_sell = max(1, risk_to_sell)
    if not risk_to_sell:
        return Plan()
    proceeds = position.cash + risk_to_sell * quotes.risk_sell * (1 - reserve)
    return Plan(sell_risk=risk_to_sell,
                buy_defensive=floor(proceeds / (quotes.defensive_buy * (1 + reserve))))


def confirm(cycle: Cycle, action: Action, post_trade_risk_shares: int,
            post_trade_basis: float) -> Cycle:
    """Advance only after a confirmed execution; pass an observed position."""
    if action is Action.TREND_RESET:
        return Cycle()
    if action in BUYS and post_trade_risk_shares > 0:
        return replace(cycle, basis=post_trade_basis or cycle.basis,
                       base_shares=post_trade_risk_shares,
                       first_dip=cycle.first_dip or action is Action.FIRST_DIP,
                       second_dip=cycle.second_dip or action is Action.ADD_TRANCHE)
    after = replace(cycle,
                    first_harvest=cycle.first_harvest or action is Action.FIRST_HARVEST,
                    second_harvest=cycle.second_harvest or action is Action.SECOND_HARVEST)
    return after if post_trade_risk_shares > 0 else replace(after, basis=0, base_shares=0)


if __name__ == "__main__":
    friday, monday = date(2026, 1, 9), date(2026, 1, 12)
    state = Cycle()
    start = Position(risk=0, defensive=100, cash=1_000)
    signal = decide(Close(friday, friday, friday, 48, -0.10, 0.0, 0.0),
                    monday, start, state)
    if signal is None:
        raise RuntimeError("example did not generate its expected staged entry")
    planned = plan_open(signal, monday, start, Quotes(50, 49.5, 100, 100), 10)
    print(f"{signal.signal_session} close: {signal.action.name}")
    print(f"{signal.execution_session} open: sell {planned.sell_defensive} defensive shares, "
          f"buy {planned.buy_risk} risk shares (plan only)")
    print("Cycle after planning:", state)
    print("Cycle after a simulated confirmation:",
          confirm(state, signal.action, planned.buy_risk, 50))
