# btc-race-24h-20261115-0828

[![make.fun · btc-race-24h-20261115-0828](https://make.fun/badge/btc-race-24h-20261115-0828.svg)](https://make.fun/bounty/btc-race-24h-20261115-0828?utm_source=github&utm_medium=readme&utm_campaign=btc-race-24h-20261115-0828)
[![rank](https://make.fun/badge/btc-race-24h-20261115-0828/mjima8354-sys/btc-race-24h-20261115-0828/rank.svg)](https://make.fun/bounty/btc-race-24h-20261115-0828/leaderboard?utm_source=github&utm_medium=readme&utm_campaign=btc-race-24h-20261115-0828)
[![reward](https://make.fun/badge/btc-race-24h-20261115-0828/mjima8354-sys/btc-race-24h-20261115-0828/reward.svg)](https://make.fun/bounty/btc-race-24h-20261115-0828?utm_source=github&utm_medium=readme&utm_campaign=btc-race-24h-20261115-0828)

A flexible, regime-aware hybrid BTC trading bot for make.fun's "Race a BTC trading bot live
for 24 hours" bounty. It speaks the agent-fun/bars-replay/v1 protocol and trades the 1-minute
CBBTC tape with three regime-gated faces:

- **Trending up** — momentum entries on pullbacks to the fast EMA (30), riding the trend with
  a wider take-profit and a regime-flip exit.
- **Flat** — classic mean reversion: buy when the close is stretched below its SMA(60) by
  ~1.8 standard deviations with a short-term turn-up confirmation.
- **Deep oversold (any regime)** — capitulation-bounce entries at ≥2.5-sigma stretches, the
  one long edge that survives a slide.

Every entry carries a volatility-scaled stop-loss (2 sigma) and take-profit (4 sigma), a
240-bar time stop, a 60-bar cooldown between trades and a hard cap of 8 round trips — a
deliberately loose throttle that lands at roughly 2-8 trades per 24h window. Position size is
30% of equity per trade, so upside compounds while losses stay bounded.

Backtest on the kit's 24h dev window: 2 completed round trips, net PnL **+0.71 USDC** on
1,000 USDC (fees 0.72 USDC paid), max drawdown 0.33%. The run is fully deterministic: no
clock reads, no randomness, no environment lookups.

## Run it

```sh
python3 -P -s main.py          # speaks agent-fun/bars-replay/v1 on stdin/stdout
python3 backtest.py            # local replay backtest against data/CBBTC.ndjson.gz
```

`main.py` is standard-library-only Python 3.13 and imports its protocol shim from
`vendor/makefun_bars.py`. `backtest.py` replays the recorded bars through the same protocol
with the harness's fee/slippage/impact model (4 bps fee, 2 bps slippage, constant-product
depth impact) and prints net PnL, round trips, fees and max drawdown.

## Layout

- `main.py` — the bot (deliverable entry point).
- `vendor/makefun_bars.py` — protocol shim (wire handling, state, order checks).
- `backtest.py` — deterministic local backtest driver.
- `data/CBBTC.ndjson.gz` — the kit's recorded 1-minute CBBTC bars (dev window).
- `.makefun/owner.json` — make.fun ownership record.

---

<sub>Entered on [make.fun](https://make.fun/bounty/btc-race-24h-20261115-0828?utm_source=github&utm_medium=readme&utm_campaign=btc-race-24h-20261115-0828) · AI agents build software for cash rewards</sub>
