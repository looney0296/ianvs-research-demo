"""Demonstrate close-to-next-open allocation on fictional prices."""
from dataclasses import dataclass
from math import isfinite
from typing import Sequence


@dataclass(frozen=True)
class Bar:
    session: str
    opening: float
    close: float


@dataclass(frozen=True)
class Fill:
    session: str
    opening: float
    target: float
    notional: float
    fee: float


@dataclass(frozen=True)
class Result:
    fills: tuple[Fill, ...]
    closing_equity: tuple[float, ...]


def simulate(
    bars: Sequence[Bar],
    close_targets: Sequence[float | None],
    initial_cash: float = 10_000.0,
    fee_bps: float = 6.0,
) -> Result:
    """Apply targets on the next open; None means no rebalance requested."""
    if not bars or len(bars) != len(close_targets):
        raise ValueError("provide one close target (or None) per session")
    if not isfinite(initial_cash) or initial_cash <= 0 or not 0 <= fee_bps < 10_000:
        raise ValueError("initial cash must be positive and fee bps in [0, 10000)")
    if any(not isfinite(p) or p <= 0 for b in bars for p in (b.opening, b.close)):
        raise ValueError("prices must be positive and finite")
    if any(t is not None and not 0 <= t <= 1 for t in close_targets):
        raise ValueError("targets must be between 0 and 1")
    if any(a.session >= b.session for a, b in zip(bars, bars[1:])):
        raise ValueError("sessions must be ordered, unique ISO dates")

    cash, shares, pending = initial_cash, 0.0, None
    fee_rate = fee_bps / 10_000
    fills, marks = [], []
    for bar, target_at_close in zip(bars, close_targets):
        if pending is not None:
            risky = shares * bar.opening
            gap = pending * (cash + risky) - risky
            if abs(gap) > 1e-9:
                # Solve risky + notional = target * (equity - fee).
                direction = 1 if gap > 0 else -1
                notional = gap / (1 + direction * pending * fee_rate)
                fee = abs(notional) * fee_rate
                cash -= notional + fee
                shares += notional / bar.opening
                fills.append(Fill(bar.session, bar.opening, pending, notional, fee))
        marks.append(cash + shares * bar.close)
        pending = target_at_close
    return Result(tuple(fills), tuple(marks))


if __name__ == "__main__":
    prices = (Bar("2026-01-05", 100, 96), Bar("2026-01-06", 93, 98),
              Bar("2026-01-07", 101, 103), Bar("2026-01-08", 100, 99))
    schedules = {"Binary": (1.0, None, 0.0, None),
                 "Staged": (0.5, 0.75, 0.25, 0.0)}
    for label, targets in schedules.items():
        result = simulate(prices, targets)
        print(f"{label}:")
        for fill in result.fills:
            print(f"  {fill.session} @ {fill.opening:.2f}: "
                  f"target {fill.target:.0%}, fee ${fill.fee:.2f}")
        print(f"  Final equity: ${result.closing_equity[-1]:,.2f}")
