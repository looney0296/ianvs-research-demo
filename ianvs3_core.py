"""Selected IANVS3 engine functions, adapted for offline, public use.

The decision, sizing and state-transition bodies are extracted from the engine.
Market history and quotes are injected; the Policy defaults are illustrative.
This module does not connect to a broker or submit an order.
"""
from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass
from datetime import date
from typing import Any, Mapping

import pandas as pd

IANVS3_META_KEY = "ianvs3_official"
IANVS3_BUY_ACTIONS = {"IANVS3_GC", "IANVS3_GC_FILL", "IANVS3_DIP1", "IANVS3_DIP2"}
IANVS3_SELL_ACTIONS = {"IANVS3_TP1", "IANVS3_TP2", "IANVS3_TP3", "IANVS3_DC"}


@dataclass(frozen=True)
class Policy:
    """Example parameters, not the private strategy configuration."""

    fast_window: int = 3
    slow_window: int = 9
    rsi_window: int = 5
    peak_window: int = 15
    trend_entry_gap: float = 0.02
    trend_exit_gap: float = -0.02
    first_profit_multiple: float = 1.20
    second_profit_multiple: float = 1.55
    final_profit_multiple: float = 1.90
    first_profit_fraction: float = 0.40
    second_profit_fraction: float = 0.30
    stop_buy_drawdown: float = -0.32
    first_dip_drawdown: float = -0.07
    second_dip_drawdown: float = -0.16
    dip_target: float = 0.25
    dip_target_rsi_bonus: float = 0.35
    dip_target_deep_rsi_bonus: float = 0.42
    dip_add: float = 0.20
    dip_add_rsi_bonus: float = 0.30
    dip_add_deep_rsi_bonus: float = 0.38
    rsi_bonus: float = 38
    rsi_deep_bonus: float = 28



def _safe_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _safe_int(value: Any) -> int:
    parsed = _safe_float(value)
    if parsed is None:
        return 0
    return int(parsed)


def _simple_rsi(values: list[float], period: int) -> list[float | None]:
    out: list[float | None] = [None] * len(values)
    gains: list[float] = []
    losses: list[float] = []
    for idx in range(1, len(values)):
        change = values[idx] - values[idx - 1]
        gains.append(max(change, 0.0))
        losses.append(max(-change, 0.0))
        if idx < period:
            continue
        window_gains = gains[idx - period : idx]
        window_losses = losses[idx - period : idx]
        avg_gain = sum(window_gains) / period
        avg_loss = sum(window_losses) / period
        out[idx] = 100.0 if avg_loss == 0.0 else 100.0 - (100.0 / (1.0 + (avg_gain / avg_loss)))
    return out


def build_position_snapshot(broker_state: dict) -> dict:
    holdings = broker_state.get("holdings") if isinstance(broker_state.get("holdings"), dict) else {}
    risk = holdings.get("RISK") if isinstance(holdings.get("RISK"), dict) else {}
    defensive = holdings.get("DEFENSIVE") if isinstance(holdings.get("DEFENSIVE"), dict) else {}
    return {
        "captured_at": broker_state.get("captured_at"),
        "regime": broker_state.get("regime"),
        "risk_qty": _safe_int(risk.get("quantity")),
        "defensive_qty": _safe_int(defensive.get("quantity")),
        "cash": _safe_float(broker_state.get("cash")) or 0.0,
        "total_equity": _safe_float(broker_state.get("total_equity")) or 0.0,
    }


def normalize_cycle_state(*, snapshot: dict, broker_state: dict) -> dict:
    meta = snapshot.get("meta") if isinstance(snapshot.get("meta"), dict) else {}
    raw = meta.get(IANVS3_META_KEY) if isinstance(meta.get(IANVS3_META_KEY), dict) else {}
    holdings = broker_state.get("holdings") if isinstance(broker_state.get("holdings"), dict) else {}
    risk = holdings.get("RISK") if isinstance(holdings.get("RISK"), dict) else {}
    risk_qty = _safe_int(risk.get("quantity"))
    cost_basis = _safe_float(risk.get("cost_basis")) or 0.0
    normalized = {
        "basis_price": _safe_float(raw.get("basis_price")) or 0.0,
        "base_shares": _safe_float(raw.get("base_shares")) or 0.0,
        "dip1_used": bool(raw.get("dip1_used")),
        "dip2_used": bool(raw.get("dip2_used")),
        "tp1_used": bool(raw.get("tp1_used")),
        "tp2_used": bool(raw.get("tp2_used")),
        "last_confirmed_action": raw.get("last_confirmed_action"),
        "last_signal_note": raw.get("last_signal_note"),
        "last_confirmed_position": raw.get("last_confirmed_position")
        if isinstance(raw.get("last_confirmed_position"), dict)
        else build_position_snapshot(broker_state),
    }
    if risk_qty <= 0:
        normalized["basis_price"] = 0.0
        normalized["base_shares"] = 0.0
        return normalized
    if normalized["basis_price"] <= 0:
        normalized["basis_price"] = cost_basis
    if normalized["base_shares"] <= 0:
        normalized["base_shares"] = float(risk_qty)
    return normalized


def position_matches_snapshot(
    *,
    broker_state: dict,
    position_snapshot: dict | None,
    share_tolerance: int,
    cash_tolerance: float,
) -> tuple[bool, list[str]]:
    if not isinstance(position_snapshot, dict):
        return False, ["last_confirmed_position missing"]
    observed = build_position_snapshot(broker_state)
    mismatches: list[str] = []
    for key in ("risk_qty", "defensive_qty"):
        if abs(int(observed.get(key) or 0) - int(position_snapshot.get(key) or 0)) > share_tolerance:
            mismatches.append(f"{key}: observed={observed.get(key)} expected={position_snapshot.get(key)}")
    observed_cash = float(observed.get("cash") or 0.0)
    expected_cash = float(position_snapshot.get("cash") or 0.0)
    if abs(observed_cash - expected_cash) > cash_tolerance:
        mismatches.append(f"cash: observed={observed_cash} expected={expected_cash}")
    return (not mismatches), mismatches


def compute_close_decision(*, reference_df: pd.DataFrame, risk_df: pd.DataFrame,
                           snapshot: dict, broker_state: dict, us_market_date: date,
                           policy: Policy) -> dict:
    """Use sorted OHLC frames indexed by session date; no data is fetched."""
    if not all(frame.index.is_monotonic_increasing and frame.index.is_unique
               for frame in (reference_df, risk_df)):
        raise ValueError("daily bars must be sorted and unique")
    common_index = reference_df.index.intersection(risk_df.index)
    reference_df = reference_df.loc[common_index].copy()
    risk_df = risk_df.loc[common_index].copy()
    min_bars = max(policy.fast_window + 1, policy.slow_window + 1,
                   policy.rsi_window + 1, policy.peak_window)
    if len(common_index) < min_bars:
        raise RuntimeError(
            f"Signal calculation requires at least {min_bars} aligned REFERENCE/RISK daily bars. "
            f"Got {len(common_index)}."
        )
    expected_last_date = pd.Timestamp(us_market_date)
    reference_last_date = reference_df.index[-1]
    risk_last_date = risk_df.index[-1]
    if reference_last_date != expected_last_date or risk_last_date != expected_last_date:
        raise RuntimeError(
            "IANVS3 daily bars are stale or misaligned: "
            f"expected={us_market_date.isoformat()} "
            f"REFERENCE={reference_last_date.date().isoformat()} RISK={risk_last_date.date().isoformat()}"
        )

    digest_payload = pd.concat(
        {
            "REFERENCE": reference_df[["Oprc", "Hprc", "Lprc", "Prpr"]],
            "RISK": risk_df[["Oprc", "Hprc", "Lprc", "Prpr"]],
        },
        names=["ticker", "date"],
    ).to_csv(float_format="%.10g")
    data_hash = hashlib.sha256(digest_payload.encode("utf-8")).hexdigest()

    risk_df["FAST_MA"] = risk_df["Prpr"].rolling(window=policy.fast_window).mean()
    risk_df["SLOW_MA"] = risk_df["Prpr"].rolling(window=policy.slow_window).mean()
    risk_df["TREND_GAP"] = (risk_df["FAST_MA"] / risk_df["SLOW_MA"]) - 1.0
    risk_df["RSI"] = _simple_rsi(risk_df["Prpr"].tolist(), policy.rsi_window)
    reference_df["REFERENCE_ROLLING_HIGH"] = reference_df["Hprc"].rolling(window=policy.peak_window).max()

    latest = risk_df.iloc[-1]
    previous_gap = _safe_float(risk_df.iloc[-2]["TREND_GAP"]) if len(risk_df) >= 2 else None
    reference_latest = reference_df.iloc[-1]
    reference_high = _safe_float(reference_latest["REFERENCE_ROLLING_HIGH"])
    reference_close = _safe_float(reference_latest["Prpr"]) or 0.0
    qdd = ((reference_close / reference_high) - 1.0) if reference_high and reference_high > 0 else None
    rsi = _safe_float(latest["RSI"])
    trend_gap = _safe_float(latest["TREND_GAP"])
    close_price = _safe_float(latest["Prpr"]) or 0.0

    cycle = normalize_cycle_state(snapshot=snapshot, broker_state=broker_state)
    holdings = broker_state.get("holdings") if isinstance(broker_state.get("holdings"), dict) else {}
    risk = holdings.get("RISK") if isinstance(holdings.get("RISK"), dict) else {}
    defensive = holdings.get("DEFENSIVE") if isinstance(holdings.get("DEFENSIVE"), dict) else {}
    shares = _safe_int(risk.get("quantity"))
    defensive_shares = _safe_int(defensive.get("quantity"))
    total_equity = _safe_float(broker_state.get("total_equity")) or 0.0
    risk_market_value = (_safe_float(risk.get("price")) or close_price) * shares
    has_cash_buffer = risk_market_value < max(total_equity - 1.0, 0.0)

    gc_event = (
        trend_gap is not None
        and previous_gap is not None
        and previous_gap < policy.trend_entry_gap
        and trend_gap >= policy.trend_entry_gap
    )
    dc_event = (
        trend_gap is not None
        and previous_gap is not None
        and previous_gap > policy.trend_exit_gap
        and trend_gap <= policy.trend_exit_gap
    )

    action = None
    signal = "neutral"
    action_note = "No next-open action."
    directives: dict[str, Any] = {}
    target_regime = "RISK_ON" if shares > 0 else "RISK_OFF"

    if shares > 0 and dc_event:
        action = "IANVS3_DC"
        signal = "ianvs3_dc"
        action_note = "signal on close, execute next open; full reset"
        directives = {"shares_to_sell": shares, "reset_cycle": True}
        target_regime = "RISK_OFF"
    elif shares > 0 and cycle["tp2_used"] and cycle["basis_price"] > 0 and close_price > cycle["basis_price"] * policy.final_profit_multiple:
        action = "IANVS3_TP3"
        signal = "ianvs3_tp3"
        action_note = "signal on close, execute next open; final exit"
        directives = {"shares_to_sell": shares}
        target_regime = "RISK_OFF"
    elif shares > 0 and (not cycle["tp1_used"]) and cycle["basis_price"] > 0 and close_price > cycle["basis_price"] * policy.first_profit_multiple:
        action = "IANVS3_TP1"
        signal = "ianvs3_tp1"
        action_note = "signal on close, execute next open; sell first fraction of base quantity"
        directives = {"shares_to_sell": min(shares, max(int(math.floor(cycle["base_shares"] * policy.first_profit_fraction)), 1))}
        target_regime = "RISK_ON"
    elif shares > 0 and cycle["tp1_used"] and (not cycle["tp2_used"]) and cycle["basis_price"] > 0 and close_price > cycle["basis_price"] * policy.second_profit_multiple:
        action = "IANVS3_TP2"
        signal = "ianvs3_tp2"
        action_note = "signal on close, execute next open; sell second fraction of base quantity"
        directives = {"shares_to_sell": min(shares, max(int(math.floor(cycle["base_shares"] * policy.second_profit_fraction)), 1))}
        target_regime = "RISK_ON"
    else:
        stop_buy_zone = qdd is not None and qdd <= policy.stop_buy_drawdown
        dip1_trigger = qdd is not None and qdd <= policy.first_dip_drawdown and (not cycle["dip1_used"]) and (not stop_buy_zone)
        dip2_trigger = (
            qdd is not None
            and qdd <= policy.second_dip_drawdown
            and shares > 0
            and cycle["dip1_used"]
            and (not cycle["dip2_used"])
            and (not stop_buy_zone)
        )
        if shares == 0 and gc_event:
            action = "IANVS3_GC"
            signal = "ianvs3_gc"
            action_note = "signal on close, execute next open; flat to full"
            directives = {"target_weight": 1.0}
            target_regime = "RISK_ON"
        elif dip1_trigger:
            target = policy.dip_target
            action_note = "signal on close, execute next open; base dip1"
            if rsi is not None and rsi <= policy.rsi_bonus:
                target = policy.dip_target_rsi_bonus
                action_note = "signal on close, execute next open; dip1 with RSI bonus"
            if rsi is not None and rsi <= policy.rsi_deep_bonus:
                target = policy.dip_target_deep_rsi_bonus
                action_note = "signal on close, execute next open; dip1 with deep RSI bonus"
            action = "IANVS3_DIP1"
            signal = "ianvs3_dip1"
            directives = {"target_weight": target}
            target_regime = "RISK_ON"
        elif dip2_trigger:
            add_weight = policy.dip_add
            action_note = "signal on close, execute next open; add base dip2 tranche sized off current equity"
            if rsi is not None and rsi <= policy.rsi_bonus:
                add_weight = policy.dip_add_rsi_bonus
                action_note = "signal on close, execute next open; add dip2 tranche with RSI bonus"
            if rsi is not None and rsi <= policy.rsi_deep_bonus:
                add_weight = policy.dip_add_deep_rsi_bonus
                action_note = "signal on close, execute next open; add dip2 tranche with deep RSI bonus"
            action = "IANVS3_DIP2"
            signal = "ianvs3_dip2"
            directives = {"add_weight": add_weight}
            target_regime = "RISK_ON"
        elif shares > 0 and has_cash_buffer and gc_event:
            action = "IANVS3_GC_FILL"
            signal = "ianvs3_gc_fill"
            action_note = "signal on close, execute next open; partial to full; TP coupons unchanged"
            directives = {"target_weight": 1.0}
            target_regime = "RISK_ON"

    details = (
        f"REFERENCE drawdown={qdd:.4f} | RISK RSI={rsi:.2f} | trend gap={trend_gap:.4f} | "
        f"RISK close={close_price:.2f} | action={action or 'none'}"
        if qdd is not None and rsi is not None and trend_gap is not None
        else f"action={action or 'none'}"
    )
    return {
        "signal": signal,
        "details": details,
        "target_regime": target_regime,
        "action": action,
        "action_note": action_note,
        "execution_directives": directives,
        "indicator_snapshot": {
            "reference_drawdown": qdd,
            "risk_rsi": rsi,
            "trend_gap": trend_gap,
            "close_price": close_price,
            "shares": shares,
            "defensive_shares": defensive_shares,
            "reference_last_bar_date": reference_last_date.date().isoformat(),
            "risk_last_bar_date": risk_last_date.date().isoformat(),
            "aligned_bar_count": len(common_index),
            "daily_data_sha256": data_hash,
        },
    }


def build_execution_plan(*, quotes: Mapping[tuple[str, str], float],
                         broker_state: dict, intent: dict, reserve_bps: float) -> dict:
    """Return planned share quantities only; prices are supplied by the caller."""
    if not 0 <= reserve_bps < 10_000:
        raise ValueError("reserve_bps must be in [0, 10000)")
    holdings = broker_state.get("holdings") if isinstance(broker_state.get("holdings"), dict) else {}
    risk_qty = _safe_int((holdings.get("RISK") or {}).get("quantity"))
    defensive_qty = _safe_int((holdings.get("DEFENSIVE") or {}).get("quantity"))
    cash = _safe_float(broker_state.get("cash")) or 0.0
    action = str(intent.get("action") or "")
    directives = intent.get("execution_directives") if isinstance(intent.get("execution_directives"), dict) else {}

    risk_buy = _safe_float(quotes.get(("RISK", "buy")))
    risk_sell = _safe_float(quotes.get(("RISK", "sell"))) or risk_buy
    defensive_buy = _safe_float(quotes.get(("DEFENSIVE", "buy")))
    defensive_sell = _safe_float(quotes.get(("DEFENSIVE", "sell"))) or defensive_buy
    if action in IANVS3_BUY_ACTIONS and (not risk_buy or not defensive_sell):
        raise RuntimeError("IANVS3 buy-side execution requires RISK buy quote and DEFENSIVE sell quote.")
    if action in IANVS3_SELL_ACTIONS and (not risk_sell or not defensive_buy):
        raise RuntimeError("IANVS3 sell-side execution requires RISK sell quote and DEFENSIVE buy quote.")

    equity = cash + (risk_qty * float(risk_sell or 0.0)) + (defensive_qty * float(defensive_sell or 0.0))
    current_risk_value = risk_qty * float(risk_sell or 0.0)
    reserve = reserve_bps / 10_000.0
    buy_unit_cost = float(risk_buy or 0.0) * (1.0 + reserve)
    sell_unit_proceeds = float(defensive_sell or 0.0) * (1.0 - reserve)

    if action in {"IANVS3_GC", "IANVS3_GC_FILL", "IANVS3_DIP1"}:
        target_weight = float(directives.get("target_weight") or 0.0)
        target_value = equity * target_weight
        desired_value = max(target_value - current_risk_value, 0.0)
        buy_qty = int(desired_value / float(risk_buy or 0.0))
        sell_defensive_qty = 0
        if buy_qty > 0:
            need_cash = buy_qty * buy_unit_cost
            if need_cash > cash and sell_unit_proceeds > 0:
                sell_defensive_qty = min(int(math.ceil((need_cash - cash) / sell_unit_proceeds)), defensive_qty)
            available_cash = cash + sell_defensive_qty * sell_unit_proceeds
            buy_qty = min(buy_qty, int(available_cash / buy_unit_cost))
        return {
            "sell_ops": ([{"ticker": "DEFENSIVE", "qty": sell_defensive_qty}] if sell_defensive_qty > 0 else []),
            "buy_ops": ([{"ticker": "RISK", "qty": buy_qty}] if buy_qty > 0 else []),
            "pricing": {"risk_buy": risk_buy, "defensive_sell": defensive_sell},
        }

    if action == "IANVS3_DIP2":
        add_weight = float(directives.get("add_weight") or 0.0)
        desired_value = max(equity * add_weight, 0.0)
        buy_qty = int(desired_value / float(risk_buy or 0.0))
        sell_defensive_qty = 0
        if buy_qty > 0:
            need_cash = buy_qty * buy_unit_cost
            if need_cash > cash and sell_unit_proceeds > 0:
                sell_defensive_qty = min(int(math.ceil((need_cash - cash) / sell_unit_proceeds)), defensive_qty)
            available_cash = cash + sell_defensive_qty * sell_unit_proceeds
            buy_qty = min(buy_qty, int(available_cash / buy_unit_cost))
        return {
            "sell_ops": ([{"ticker": "DEFENSIVE", "qty": sell_defensive_qty}] if sell_defensive_qty > 0 else []),
            "buy_ops": ([{"ticker": "RISK", "qty": buy_qty}] if buy_qty > 0 else []),
            "pricing": {"risk_buy": risk_buy, "defensive_sell": defensive_sell},
        }

    if action in IANVS3_SELL_ACTIONS:
        raw_sell_qty = directives.get("shares_to_sell")
        sell_qty = min(risk_qty, max(int(math.floor(float(raw_sell_qty or 0.0))), 0))
        if sell_qty <= 0 and risk_qty > 0 and action in {"IANVS3_TP1", "IANVS3_TP2"}:
            sell_qty = 1
        available_after_sell = cash + (sell_qty * float(risk_sell or 0.0)) * (1.0 - reserve)
        buy_defensive_qty = (
            int(available_after_sell / (float(defensive_buy) * (1.0 + reserve_bps / 10_000.0)))
            if sell_qty > 0 and defensive_buy
            else 0
        )
        return {
            "sell_ops": ([{"ticker": "RISK", "qty": sell_qty}] if sell_qty > 0 else []),
            "buy_ops": ([{"ticker": "DEFENSIVE", "qty": buy_defensive_qty}] if buy_defensive_qty > 0 else []),
            "pricing": {"risk_sell": risk_sell, "defensive_buy": defensive_buy},
        }

    return {"sell_ops": [], "buy_ops": [], "pricing": {}}


def advance_cycle_state_after_execution(
    *,
    previous_state: dict,
    action: str,
    action_note: str | None,
    broker_state_after: dict,
) -> dict:
    next_state = normalize_cycle_state(snapshot={"meta": {IANVS3_META_KEY: previous_state}}, broker_state=broker_state_after)
    position_after = build_position_snapshot(broker_state_after)
    risk_qty_after = int((position_after or {}).get("risk_qty") or 0)
    next_state["last_confirmed_position"] = position_after
    next_state["last_confirmed_action"] = action
    next_state["last_signal_note"] = action_note

    holdings = broker_state_after.get("holdings") if isinstance(broker_state_after.get("holdings"), dict) else {}
    risk = holdings.get("RISK") if isinstance(holdings.get("RISK"), dict) else {}
    broker_cost_basis = _safe_float(risk.get("cost_basis")) or 0.0

    if action in IANVS3_BUY_ACTIONS and risk_qty_after > 0:
        next_state["basis_price"] = broker_cost_basis or next_state["basis_price"]
        next_state["base_shares"] = float(risk_qty_after)
        if action == "IANVS3_DIP1":
            next_state["dip1_used"] = True
        if action == "IANVS3_DIP2":
            next_state["dip2_used"] = True
        return next_state

    if action == "IANVS3_TP1":
        next_state["tp1_used"] = True
    elif action == "IANVS3_TP2":
        next_state["tp2_used"] = True
    elif action == "IANVS3_DC":
        next_state["basis_price"] = 0.0
        next_state["base_shares"] = 0.0
        next_state["dip1_used"] = False
        next_state["dip2_used"] = False
        next_state["tp1_used"] = False
        next_state["tp2_used"] = False
        return next_state

    if risk_qty_after <= 0:
        next_state["basis_price"] = 0.0
        next_state["base_shares"] = 0.0
    return next_state
