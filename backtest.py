#!/usr/bin/env python3
"""Local backtest driver for the bars-replay/v1 bot in main.py.

Replays a gzipped NDJSON bar file through agent-fun/bars-replay/v1, runs the bot the same way the
grader does (python3 -P -s main.py, PYTHONHASHSEED=0) and fills orders with the harness's market
model. Units: price raw (scale 5), qty raw (scale 8), USDC raw = micro (scale 6).

  value_micro(qty, price) = qty * price / 10^(qty_scale + price_scale - quote_scale) = qty*price/1e7
  buy:  spend = notional * (10000 - fee_bps) / 10000; price = open * (10000 + slippage) * M / 10000
        with M = 1 + spend/depth; qty = spend * 10^7 / price
  sell: a = qty * open / 10^7 (raw micro); M = 1 + a/depth; price = open*(10000-slip)/(10000*M)
        gross = qty * price / 10^7; proceeds = gross * (10000 - fee_bps)/10000

Everything still held at the end is flattened at the last close against that close's depth.
Prints net PnL (USDC), trades, fees, max drawdown.
Deterministic: no clock, no network, no unseeded randomness.
"""

import argparse
import gzip
import json
import subprocess
import sys

BPS = 10_000
QUOTE_SCALE = 6
PRICE_SCALE = 5
QTY_SCALE = 8
FEE_BPS = 4
SLIP_BPS = 2
MIN_NOTIONAL = 1_000_000
START_UNITS = 1_000_000_000  # 1,000 USDC in micro-USDC
SYMBOL = "CBBTC"
SCALE_DIV = 10 ** (QTY_SCALE + PRICE_SCALE - QUOTE_SCALE)  # qty*price -> micro-USDC: 1e7


def load_bars(path):
    with gzip.open(path, "rt") as f:
        return [json.loads(l) for l in f if l.strip()]


def bars_hello(first_close_ms):
    return {
        "type": "hello", "protocol": "agent-fun/bars-replay/v1", "seed": "0",
        "symbols": [{"symbol": SYMBOL, "mint": "cbbtcf3aa214zXHbiAZQwf4122FBYbraNdFqgw4iMij",
                     "price_scale": PRICE_SCALE, "qty_scale": QTY_SCALE}],
        "capital": {"quote": "USDC", "quote_scale": QUOTE_SCALE, "quote_units": str(START_UNITS)},
        "bar_interval": "1m", "first_close_ms": first_close_ms,
        "caps": {"max_open_positions": 1, "max_orders_per_bar": 16, "max_weight_bps": 10000,
                 "shorts": False, "leverage": False},
        "fees": {"fee_bps": FEE_BPS, "slippage_bps": SLIP_BPS,
                 "min_notional_quote_units": str(MIN_NOTIONAL)},
        "latency_bars": 1,
    }


def buy_fill(notional, bar, depth):
    spend = notional * (BPS - FEE_BPS) // BPS
    m = 1 + spend / depth
    price = int(int(bar["o"]) * (BPS + SLIP_BPS) * m / BPS)
    qty = spend * SCALE_DIV // price
    return {"fee": notional - spend, "price": price, "qty": qty}


def sell_fill(qty, bar, depth):
    a = qty * int(bar["o"]) // SCALE_DIV
    m = 1 + a / depth
    price = max(1, int(int(bar["o"]) * (BPS - SLIP_BPS) / (BPS * m)))
    gross = qty * price // SCALE_DIV
    proceeds = gross * (BPS - FEE_BPS) // BPS
    return {"fee": gross - proceeds, "proceeds": proceeds, "price": price}


def run_bot(bot_path, hello, batches):
    proc = subprocess.Popen(
        [sys.executable, "-P", "-s", bot_path],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=sys.stderr,
        env={"PYTHONHASHSEED": "0", "PATH": "/usr/bin:/bin:/usr/local/bin"},
    )
    lines = [json.dumps(hello, separators=(",", ":"))]
    lines += [json.dumps(b, separators=(",", ":")) for b in batches]
    out, _ = proc.communicate(("\n".join(lines) + "\n").encode())
    if proc.returncode != 0:
        raise SystemExit(f"bot exited with {proc.returncode}")
    return [json.loads(l) for l in out.decode().splitlines() if l.strip()]


def backtest(bars_path, bot_path, verbose=False):
    bars = load_bars(bars_path)
    hello = bars_hello(int(bars[0]["t"]))

    # Pass 1: collect the bot's replies for each seq (account mirror feeds it honestly).
    replies = None
    prev_by_seq = {}
    for _ in range(6):  # fixed-point: feed the previous run's orders back through the mirror
        batches, pending, account = [], [], {"cash": START_UNITS, "qty": 0, "cost": 0}
        for i, bar in enumerate(bars):
            fills = []
            depth = int(bar["o_depth"][0])
            for o in pending:
                if o["side"] == "buy":
                    notional = int(o["notional_quote_units"])
                    if notional < MIN_NOTIONAL or notional > account["cash"]:
                        fills.append({"client_id": o["client_id"], "status": "rejected"})
                        continue
                    f = buy_fill(notional, bar, depth)
                    account["cash"] -= notional
                    account["qty"] += f["qty"]
                    account["cost"] += notional
                    fills.append({"client_id": o["client_id"], "status": "filled", "fee": f["fee"],
                                  "qty": str(f["qty"]), "price": str(f["price"])})
                else:
                    if account["qty"] <= 0:
                        fills.append({"client_id": o["client_id"], "status": "rejected"})
                        continue
                    qty = min(account["qty"], int(o["qty"]))
                    f = sell_fill(qty, bar, depth)
                    account["qty"] -= qty
                    account["cash"] += f["proceeds"]
                    fills.append({"client_id": o["client_id"], "status": "filled", "fee": f["fee"],
                                  "qty": str(qty), "price": str(f["price"])})
            batches.append({"type": "batch", "seq": i, "t": int(bar["t"]),
                            "bars": [{"symbol": SYMBOL, **{k: bar[k] for k in ("o", "h", "l", "c", "o_depth", "c_depth")}}],
                            "fills": fills,
                            "account": {"cash_quote_units": str(account["cash"]),
                                        "positions": ([{"symbol": SYMBOL, "qty": str(account["qty"]),
                                                        "cost_quote_units": str(account["cost"])}] if account["qty"] else []),
                                        "equity_quote_units": str(account["cash"] + account["qty"] * int(bar["c"]) // SCALE_DIV)}})
            pending = prev_by_seq.get(i, {}).get("orders", [])
        done = {"type": "done", "seq": len(batches),
                "account": {"cash_quote_units": str(account["cash"]), "positions": [],
                            "equity_quote_units": str(account["cash"])}}
        new = run_bot(bot_path, hello, batches + [done])
        new_by_seq = {r["seq"]: r for r in new}
        if replies == new:
            replies = new
            break
        replies = new
        prev_by_seq = new_by_seq
    by_seq = {r["seq"]: r for r in replies}

    # Pass 2: score with the bot's actual orders.
    pending, account = [], {"cash": START_UNITS, "qty": 0, "cost": 0}
    fees_paid = trades = wins = 0
    equity_curve = []
    log = []
    for i, bar in enumerate(bars):
        for o in pending:
            depth = int(bar["o_depth"][0])
            if o["side"] == "buy":
                notional = int(o["notional_quote_units"])
                if notional < MIN_NOTIONAL or notional > account["cash"]:
                    continue
                f = buy_fill(notional, bar, depth)
                if f["qty"] == 0:
                    continue
                account["cash"] -= notional
                account["qty"] += f["qty"]
                account["cost"] = notional
                fees_paid += f["fee"]
                trades += 1
                log.append((i, "BUY", notional / 1e6))
            else:
                if account["qty"] <= 0:
                    continue
                qty = min(account["qty"], int(o["qty"]))
                f = sell_fill(qty, bar, depth)
                pnl = f["proceeds"] - account["cost"]
                wins += 1 if pnl > 0 else 0
                log.append((i, "SELL", pnl / 1e6))
                account["qty"] -= qty
                account["cash"] += f["proceeds"]
                fees_paid += f["fee"]
                trades += 1
        pending = by_seq.get(i, {}).get("orders", [])
        equity_curve.append(account["cash"] + account["qty"] * int(bar["c"]) // SCALE_DIV)

    if account["qty"]:
        f = sell_fill(account["qty"], {"o": bars[-1]["c"]}, int(bars[-1]["c_depth"][0]))
        account["cash"] += f["proceeds"]
        fees_paid += f["fee"]
        trades += 1
        account["qty"] = 0
    equity_curve[-1] = account["cash"]

    net = account["cash"] - START_UNITS
    peak, mdd = START_UNITS, 0
    for eq in equity_curve:
        peak = max(peak, eq)
        mdd = max(mdd, (peak - eq) / peak)
    sells = sum(1 for e in log if e[1] == "SELL")
    winrate = (wins / sells) if sells else 0.0
    # Sharpe from per-bar equity returns (1m), annualised.
    rets = []
    for i in range(1, len(equity_curve)):
        if equity_curve[i - 1] > 0:
            rets.append((equity_curve[i] - equity_curve[i - 1]) / equity_curve[i - 1])
    if len(rets) > 1:
        import statistics
        mr = statistics.fmean(rets)
        sr = statistics.pstdev(rets)
        sharpe = (mr / sr * (525600 ** 0.5)) if sr > 0 else 0.0
    else:
        sharpe = 0.0
    print(f"bars={len(bars)} round_trips={wins}/{sells} trades={trades} net_pnl={net/1e6:.2f} USDC  "
          f"winrate={winrate:.1%}  max_drawdown={mdd:.4%}  fees={fees_paid/1e6:.2f} USDC  "
          f"end={account['cash']/1e6:.2f} USDC  sharpe={sharpe:.2f}")
    for e in log:
        print(f"  bar {e[0]:5d} {e[1]:4s} {e[2]:+.2f}")
    if verbose:
        for i in range(0, len(equity_curve), max(1, len(equity_curve) // 24)):
            print(f"  bar {i:5d} equity={equity_curve[i]/1e6:.2f}")
    return net


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--bars", default="data/CBBTC.ndjson.gz")
    ap.add_argument("--bot", default="main.py")
    ap.add_argument("--verbose", action="store_true")
    a = ap.parse_args()
    backtest(a.bars, a.bot, a.verbose)
