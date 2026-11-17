#!/usr/bin/env python3
"""BTC hybrid regime-aware trading bot for agent-fun/bars-replay/v1.

Ensemble strategy combining regime-aware mean-reversion and momentum on 1m CBBTC bars.
Long-only, with dynamic stop-loss, breakeven adjustment, trailing stop, and trade throttling
(2-8 trades per 24 hours via cooldown and bar filters).
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "vendor"))
import makefun_bars

SYMBOL = "CBBTC"

# Configuration parameters
EMA_PERIOD = 30
SLOPE_PERIOD = 60
LOOKBACK_PERIOD = 60
MIN_HISTORY = 380
COOLDOWN_BARS = 50
TIME_STOP_BARS = 240
MAX_TRADES = 8
RISK_FRAC_NUM = 20
RISK_PCT = RISK_FRAC_NUM
MAX_SLIPPAGE_BPS = 60

# Fixed-point and scaling factors
SCALE = 1_000_000_000
MILLI = 1_000


class BotState:
    """Maintains strategy indicators, position lifecycle, and risk controls."""

    def __init__(self):
        self.closes = []
        self.ema_history = []
        self.ema_fast = None
        self.bar_index = 0
        self.sma = 0
        self.std_dev = 0
        self.trade_record = None
        self.cooldown_end = -1
        self.trade_count = 0
        self.alpha = 2 * MILLI // (EMA_PERIOD + 1)

    def update_indicators(self, price: int):
        self.bar_index += 1
        self.closes.append(price)
        if len(self.closes) > LOOKBACK_PERIOD:
            self.closes.pop(0)

        if self.ema_fast is None:
            self.ema_fast = price
        else:
            self.ema_fast += (price - self.ema_fast) * self.alpha // MILLI

        self.ema_history.append(self.ema_fast)
        if len(self.ema_history) > SLOPE_PERIOD + 1:
            self.ema_history.pop(0)

        if self.closes:
            self.sma = sum(self.closes) // len(self.closes)
            variance = sum((c - self.sma) ** 2 for c in self.closes) // len(self.closes)
            self.std_dev = int(variance ** 0.5)

    def calculate_slope(self) -> int:
        if len(self.ema_history) < SLOPE_PERIOD + 1 or self.ema_history[0] <= 0:
            return 0
        return (self.ema_fast - self.ema_history[0]) * SCALE // self.ema_history[0]


STATE = BotState()


def on_batch(state, batch):
    st = STATE
    price = state.close(SYMBOL)
    if price is None:
        return []

    try:
        st.update_indicators(price)
    except Exception:
        return []

    orders = []
    position = state.positions.get(SYMBOL)

    # 1. Manage active position (SL, Breakeven, Trailing Stop, Time Stop)
    if position is not None and position.qty > 0 and st.trade_record is not None:
        rec = st.trade_record
        if rec["entry_price"] is None:
            rec["entry_price"] = int(batch["bars"][0]["o"])
            rec["peak_price"] = rec["entry_price"]
            rec["sd"] = max(rec["sd"], 1)

        sd = max(rec["sd"], 1)
        if price > rec["peak_price"]:
            rec["peak_price"] = price

        gain_milli = (price - rec["entry_price"]) * MILLI // sd
        peak_gain_milli = (rec["peak_price"] - rec["entry_price"]) * MILLI // sd

        exit_triggered = False

        # Base Stop Loss: 2.0 sigma below entry
        sl_price = rec["entry_price"] - (2 * sd)

        # Move to breakeven if profit >= 1.0 sigma
        if peak_gain_milli >= 1000 or gain_milli >= 1000:
            sl_price = max(sl_price, rec["entry_price"])

        # Trailing stop if profit >= 1.5 sigma (trail by 1.0 sigma from peak)
        if peak_gain_milli >= 1500:
            trailing_stop = rec["peak_price"] - sd
            sl_price = max(sl_price, trailing_stop)

        if price <= sl_price:
            exit_triggered = True
        elif rec["kind"] == "momentum" and st.calculate_slope() < -3_000_000:
            exit_triggered = True
        elif st.bar_index - rec["entry_bar"] >= TIME_STOP_BARS:
            exit_triggered = True

        if exit_triggered:
            orders.append({
                "side": "sell",
                "symbol": SYMBOL,
                "qty": position.qty,
                "max_slippage_bps": MAX_SLIPPAGE_BPS,
            })
            st.trade_record = None
            st.cooldown_end = st.bar_index + COOLDOWN_BARS
            st.trade_count += 1
        return orders

    # 2. Check entry conditions
    if st.trade_record is not None or (position is not None and position.qty > 0):
        return orders
    if st.bar_index < MIN_HISTORY or st.std_dev <= 0:
        return orders
    if st.bar_index < st.cooldown_end or st.trade_count >= MAX_TRADES:
        return orders

    equity = state.equity
    if equity <= 0:
        return orders

    notional = equity * RISK_PCT // 100
    room = state.weight_room(SYMBOL)
    if room > 0:
        notional = min(notional, room)
    if notional > state.cash:
        notional = state.cash

    min_notional = int(state.hello["fees"]["min_notional_quote_units"])
    if notional < min_notional:
        return orders

    sd = st.std_dev
    z_score = (price - st.sma) * MILLI // sd
    slope = st.calculate_slope()

    is_uptick = len(st.closes) >= 3 and st.closes[-1] > st.closes[-2] > st.closes[-3]
    is_roc_positive = len(st.closes) >= 5 and st.closes[-1] > st.closes[-5]

    signal_kind = None
    # Mean Reversion: deep oversold (-2.5 sigma) with uptick confirmation
    if z_score <= -2500 and is_uptick:
        signal_kind = "mean_reversion"
    # Flat Regime Reversion: range bottom reclaim
    elif abs(slope) <= 3_000_000 and z_score <= -1800 and st.closes[-1] > st.closes[-2] and st.closes[-2] <= st.sma:
        signal_kind = "mean_reversion"
    # Momentum Pullback: uptrend with pullback near EMA
    elif slope > 3_000_000 and 0 <= z_score <= 500 and is_uptick and is_roc_positive:
        signal_kind = "momentum"

    if signal_kind is None:
        return orders

    orders.append({
        "side": "buy",
        "symbol": SYMBOL,
        "notional_quote_units": notional,
        "max_slippage_bps": MAX_SLIPPAGE_BPS,
    })
    st.trade_record = {
        "entry_price": None,
        "peak_price": None,
        "sd": sd,
        "entry_bar": st.bar_index,
        "kind": signal_kind,
    }
    return orders


def on_done(state, done):
    pass


if __name__ == "__main__":
    makefun_bars.run(on_batch, on_done=on_done)
