# IANVS3 Staged Allocation Demo

A public adaptation of the IANVS3 strategy state machine and next-open execution planner. It shows how a closing signal becomes a whole-share plan across a risk ETF and a defensive ETF, and when the strategy is allowed to advance to its next stage.

## How IANVS evolved

| Version | Design change | Why it mattered |
| --- | --- | --- |
| **IANVS 1 · Signal prototype** | Used daily and weekly moving-average breakouts for entries and a shorter trend filter to veto some exits. | Turned a trading idea into explicit entry and exit rules. |
| **IANVS 2 · Execution and recovery** | Separated the close decision from the next-open execution intent. Added snapshot and event-journal recovery, broker reconciliation, and a replay guard for ambiguous executions. | After an interruption, the engine checks what happened before it can submit the same intent again. |
| **IANVS 3 · Staged allocation** | Replaced binary risk exposure with staged entries and profit-taking. The first entry targets a weight, the second adds a tranche, and confirmed positions drive later state transitions. | Makes changing position size and tracking which stages have completed explicit. This is the part implemented in the runnable demo below. |

## What the code demonstrates

| Stage | Behavior |
| --- | --- |
| Close | Reject stale or misaligned inputs. Evaluate trend exits before profit-taking and new entries. A first dip targets a portfolio weight; a second dip adds a tranche sized from current equity. |
| Next open | Use fresh bid-side and ask-side quote inputs. Sell enough defensive shares to fund the intended purchase plus a cost reserve, then cap the purchase at affordable whole shares. |
| Confirmation | Planning alone does not consume a dip or profit-taking stage. Advance the cycle after confirmation, using observed post-trade shares and cost basis. A trend exit resets the cycle. |

## Run

Python 3.10+, standard library only. No credentials or network access.

```sh
python demo.py
python -m unittest -v
```

The example evaluates Friday's close and creates a plan for Monday's open: sell **18 defensive shares** to fund **55 risk shares**. It prints the unchanged cycle after planning and then advances it after a simulated confirmation. Tests cover timing, stale data, action priority, tranche sizing, and state transitions.

## Validation and scope

The order-planning implementation was checked against the original private IANVS3 planner on 2,400 synthetic combinations across target-weight entry, additive entry, and full exit; the order quantities matched in those cases. The private-source comparison isn't part of this public repository. Its public unit tests run independently.

The demo takes precomputed close indicators and an explicit next-session date. Thresholds and prices are illustrative, and the public policy omits the original indicator calculations and sizing overlays. It does not include a calendar or market data feed, broker integration, order submission, fill recovery, or historical performance estimates.
