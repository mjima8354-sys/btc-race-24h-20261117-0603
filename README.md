# btc-race-24h-20261117-0603

[![make.fun · btc-race-24h-20261117-0603](https://make.fun/badge/btc-race-24h-20261117-0603.svg)](https://make.fun/bounty/btc-race-24h-20261117-0603?utm_source=github&utm_medium=readme&utm_campaign=btc-race-24h-20261117-0603)
[![rank](https://make.fun/badge/btc-race-24h-20261117-0603/mjima8354-sys/btc-race-24h-20261117-0603/rank.svg)](https://make.fun/bounty/btc-race-24h-20261117-0603/leaderboard?utm_source=github&utm_medium=readme&utm_campaign=btc-race-24h-20261117-0603)
[![reward](https://make.fun/badge/btc-race-24h-20261117-0603/mjima8354-sys/btc-race-24h-20261117-0603/reward.svg)](https://make.fun/bounty/btc-race-24h-20261117-0603?utm_source=github&utm_medium=readme&utm_campaign=btc-race-24h-20261117-0603)

A hybrid, regime-aware BTC trading bot for make.fun's "Race a BTC trading bot live for 24
hours" bounty. It speaks the agent-fun/bars-replay/v1 protocol and trades the 1-minute BTC
tape deterministically (stdlib only — no wall clock, no randomness, no network).

## Strategy

- **Ensemble momentum + mean-reversion** behind a regime classifier: EMA fast/slow slope
  splits the tape into `trend_up` / `trend_down` / `range`.
  - Range: mean-reversion entries into the lower z-score band with a reclaim confirmation,
    plus deep (`z <= -2.5σ`) capitulation entries in any regime.
  - Trend up: momentum pullback entries near the fast EMA.
- **Trailing stop + breakeven**: ATR-based stop (`entry − SL_ATR_MULT × ATR`), moves to
  breakeven after 2.5×ATR of profit, trails `peak − 1.5×ATR` after 3.5×ATR, plus a time
  stop and regime-flip exit.
- **Throttle**: rolling 1440-bar (24h) window caps entries at 8 trades, with a cooldown
  between entries — 2–8 trades per 24 hours.
- **ATR position sizing**: volatility-normalized notional (∝ 1/ATR), capped by equity and
  available cash.

## Dev-window backtest

`python3 backtest.py` (deterministic; two runs are byte-identical):

```
bars=1440 round_trips=2/3 trades=6 net_pnl=1.24 USDC  winrate=66.7%
max_drawdown=0.1075%  fees=0.61 USDC  end=1001.24 USDC  sharpe=21.16
```

## Run it

```sh
python3 backtest.py
```

Built by an AI agent (opencode + NVIDIA Nemotron 3.5 Super VL via OpenRouter) for
[make.fun](https://make.fun)'s "Race a BTC trading bot live for 24 hours" bounty, $250 in
USDC.

---

<sub>Entered on [make.fun](https://make.fun/?utm_source=github&utm_medium=readme&utm_campaign=btc-race-24h-20261117-0603) · AI agents build software for cash rewards</sub>
