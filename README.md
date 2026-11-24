# IANVS3 Staged Allocation Demo

A runnable extract of the IANVS3 strategy engine. The close decision, whole-share order planner, and state update are taken from the original engine, with broker I/O replaced by supplied data and quotes. The public example uses fictional prices, neutral asset names, and illustrative policy settings.

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

## Source included

- `ianvs3_core.py`: selected IANVS3 engine functions, including indicator construction and close decisions, whole-share next-open planning, and post-execution state transitions.
- `test_source.py`: four corresponding regression cases adapted from the original test suite. The original fixtures and assertions are retained apart from neutral asset names and injected quote and reserve inputs.
- `demo.py` and `test_demo.py`: a fictional end-to-end example and supplemental tests. The harness supplies the expected session rather than importing an exchange calendar.

## Run

Use Python 3.10 or later with pandas installed. The demo itself runs offline and needs no credentials.

```sh
python -m pip install pandas
python demo.py
python -m unittest -v
```

The sample creates an entry intent at Friday's close, then plans a sale of **37 defensive shares** and a purchase of **92 risk shares** for Monday's open. A separately supplied fictional post-trade snapshot advances the cycle. The example never submits orders.

## Validation and scope

Nine tests run in the public repository. In additional offline comparisons against the original private source, **300** synthetic close fixtures matched actions and execution directives, covering all eight action types and no action. **2,400** synthetic order-planning fixtures matched whole-share buys and sells across target-weight entry, additive entry, and full exit. Those private-source comparisons match policy inputs; the illustrative public defaults do not represent the original strategy settings.

This extract excludes the broker adapter, credential and account setup, live execution, order journal and recovery, and real data. It does not claim historical or live performance.
