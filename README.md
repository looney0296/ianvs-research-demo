# IANVS Research Demo

A small, offline example inspired by IANVS, an independent systematic ETF research project. It compares binary and staged target allocations on the same fictional price path and isolates when a signal becomes a fill.

**Signals are supplied after the close.** A target from session \(t\) can trade only at the open of session \(t+1\). Existing shares are marked at that open before rebalancing. Transaction costs are 6 basis points on the dollars traded, for buys and sells alike. If no new target was supplied, the demo keeps the current shares. The final close signal never fills because there is no following session.

The example uses one synthetic risky asset and non-interest-bearing cash. The included targets are illustrative inputs, not production strategy rules. There is no broker connection, market data feed, slippage model, or order submission. The synthetic output does not reproduce or validate the project's historical backtests.

## Run

Requires Python 3.10 or later. No packages or network access are needed.

```sh
python demo.py
python -m unittest -v
```

Output reports each simulated fill (date, opening price, target weight, and fee), followed by final equity for each of the two illustrative schedules. The tests isolate the timing rule, terminal signal handling, position sizing, and fee calculation.
