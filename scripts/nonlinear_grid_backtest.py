from __future__ import annotations

import argparse
import json
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
RAW_ROOT = ROOT / "engine" / "data" / "raw"
OUT_ROOT = ROOT / "engine" / "artifacts" / "backtests" / "nonlinear_grid"
LOG_LATEST_MD = ROOT / "logs" / "nonlinear_grid_latest.md"


def now_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def utc_iso(ts_ms: int) -> str:
    raw = float(ts_ms)
    scale = 1000.0
    if abs(raw) > 1e17:
        scale = 1_000_000_000.0
    elif abs(raw) > 1e14:
        scale = 1_000_000.0
    elif abs(raw) > 1e11:
        scale = 1000.0
    else:
        scale = 1.0
    return datetime.fromtimestamp(raw / scale, tz=timezone.utc).isoformat().replace("+00:00", "Z")


def _clip(value: float, lo: float, hi: float) -> float:
    return max(float(lo), min(float(hi), float(value)))


def compute_rsi(close: pd.Series, window: int = 14) -> pd.Series:
    delta = close.diff()
    up = delta.clip(lower=0.0)
    down = (-delta).clip(lower=0.0)
    avg_up = up.ewm(alpha=1.0 / float(window), adjust=False, min_periods=window).mean()
    avg_down = down.ewm(alpha=1.0 / float(window), adjust=False, min_periods=window).mean()
    rs = avg_up / avg_down.replace(0.0, np.nan)
    rsi = 100.0 - (100.0 / (1.0 + rs))
    return rsi.fillna(50.0)


def compute_atr(high: pd.Series, low: pd.Series, close: pd.Series, window: int = 14) -> pd.Series:
    prev_close = close.shift(1)
    tr = pd.concat(
        [
            high - low,
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return tr.ewm(alpha=1.0 / float(window), adjust=False, min_periods=window).mean().fillna(0.0)


def rolling_trendline_last(close: np.ndarray, window: int) -> np.ndarray:
    n = int(window)
    out = np.full(close.shape[0], np.nan, dtype=np.float64)
    if close.shape[0] < n or n < 3:
        return out
    x = np.arange(n, dtype=np.float64)
    s_x = float(np.sum(x))
    s_xx = float(np.sum(x * x))
    denom = float(n * s_xx - s_x * s_x)
    if denom == 0.0:
        return out

    series = np.asarray(close, dtype=np.float64)
    s_y = np.convolve(series, np.ones(n, dtype=np.float64), mode="valid")
    s_xy = np.convolve(series, x[::-1], mode="valid")
    slope = (n * s_xy - s_x * s_y) / denom
    intercept = (s_y - slope * s_x) / float(n)
    pred = intercept + slope * float(n - 1)
    out[n - 1 :] = pred
    return out


def online_rls_forecast(features: np.ndarray, target: np.ndarray, lam: float = 0.995) -> np.ndarray:
    rows, cols = features.shape
    theta = np.zeros(cols, dtype=np.float64)
    p = np.eye(cols, dtype=np.float64) * 1000.0
    preds = np.zeros(rows, dtype=np.float64)
    lam = _clip(lam, 0.90, 0.9999)

    for i in range(rows):
        x = features[i]
        y_hat = float(np.dot(theta, x))
        preds[i] = max(0.0, y_hat)
        y = target[i]
        if not np.isfinite(y):
            continue
        px = p @ x
        denom = lam + float(x.T @ px)
        if not np.isfinite(denom) or abs(denom) < 1e-12:
            continue
        k = px / denom
        err = float(y - y_hat)
        theta = theta + k * err
        p = (p - np.outer(k, x.T @ p)) / lam
    return preds


def load_1m_frame(symbol: str, max_bars: int) -> pd.DataFrame:
    tf_root = RAW_ROOT / f"symbol={symbol}" / "timeframe=1m"
    files = sorted(tf_root.rglob("*.parquet"))
    if not files:
        raise FileNotFoundError(f"No 1m parquet files found under {tf_root}")
    frames: list[pd.DataFrame] = []
    if max_bars > 0:
        # Read recent files first to avoid loading the full multi-year archive.
        rows_collected = 0
        for path in reversed(files):
            frame = pd.read_parquet(path)
            frames.append(frame)
            rows_collected += int(len(frame))
            if rows_collected >= int(max_bars * 1.25):
                break
        frames.reverse()
    else:
        frames = [pd.read_parquet(path) for path in files]
    df = pd.concat(frames, axis=0, ignore_index=True)
    for col in ("ts", "open", "high", "low", "close", "volume"):
        if col not in df.columns:
            raise ValueError(f"Missing required column: {col}")
    df = df[["ts", "open", "high", "low", "close", "volume"]].copy()
    df["ts"] = pd.to_numeric(df["ts"], errors="coerce")
    for col in ("open", "high", "low", "close", "volume"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.dropna().drop_duplicates(subset=["ts"]).sort_values("ts")
    if max_bars > 0 and len(df) > max_bars:
        df = df.iloc[-max_bars:].copy()
    return df.reset_index(drop=True)


def tier_base_ratio(equity: float) -> float:
    if equity <= 100_000.0:
        return 0.15
    if equity <= 500_000.0:
        return 0.10
    return 0.05


@dataclass
class Position:
    side: int
    entry_price: float
    qty: float
    interval: float
    open_ts: int
    open_idx: int


def unrealized_pnl(position: Position, price: float) -> float:
    return float(position.side) * (float(price) - float(position.entry_price)) * float(position.qty)


def reduce_losing_positions_with_credit(positions: list[Position], credit: float, price: float) -> float:
    remaining = float(max(0.0, credit))
    if remaining <= 0.0:
        return 0.0
    candidates = sorted(
        [p for p in positions if unrealized_pnl(p, price) < 0.0 and p.qty > 0.0],
        key=lambda item: item.open_idx,
    )
    for pos in candidates:
        pnl_per_qty = float(pos.side) * (float(price) - float(pos.entry_price))
        loss_per_qty = abs(min(0.0, pnl_per_qty))
        if loss_per_qty <= 1e-12:
            continue
        cover_value = min(remaining, loss_per_qty * pos.qty)
        qty_reduce = cover_value / loss_per_qty
        pos.qty = max(0.0, pos.qty - qty_reduce)
        remaining -= cover_value
        if remaining <= 1e-12:
            break
    positions[:] = [p for p in positions if p.qty > 1e-10]
    return max(0.0, remaining)


def max_drawdown(nav: np.ndarray) -> float:
    if nav.size == 0:
        return 0.0
    peak = np.maximum.accumulate(nav)
    dd = np.where(peak > 0.0, (nav - peak) / peak, 0.0)
    return float(np.min(dd))


def sharpe_ratio(nav: np.ndarray) -> float:
    if nav.size < 3:
        return 0.0
    ret = np.diff(nav) / np.where(nav[:-1] == 0.0, 1.0, nav[:-1])
    mu = float(np.nanmean(ret))
    sd = float(np.nanstd(ret))
    if not np.isfinite(sd) or sd <= 1e-12:
        return 0.0
    return float((mu / sd) * math.sqrt(525_600.0))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="BTC 1m nonlinear dynamic band-grid backtest.")
    parser.add_argument("--symbol", default="BTCUSDT")
    parser.add_argument("--max-bars", type=int, default=300_000, help="0 means full dataset.")
    parser.add_argument("--initial-capital", type=float, default=50_000.0)
    parser.add_argument("--alpha", type=float, default=0.35, help="Scale-down decay coefficient.")
    parser.add_argument("--max-layers", type=int, default=6)
    parser.add_argument("--k-atr", type=float, default=1.35)
    parser.add_argument("--k-premium", type=float, default=0.0025)
    parser.add_argument("--x-min", type=float, default=0.0020)
    parser.add_argument("--x-max", type=float, default=0.0250)
    parser.add_argument("--trend-window", type=int, default=240)
    parser.add_argument("--trend-beta", type=float, default=0.60)
    parser.add_argument("--rsi-window", type=int, default=14)
    parser.add_argument("--rsi-oversold", type=float, default=35.0)
    parser.add_argument("--rsi-overbought", type=float, default=65.0)
    parser.add_argument("--tp-mult", type=float, default=0.8)
    parser.add_argument("--sl-mult", type=float, default=2.2)
    parser.add_argument("--fee-bps", type=float, default=4.0)
    parser.add_argument("--slippage-bps", type=float, default=2.0)
    parser.add_argument("--rls-lambda", type=float, default=0.995)
    parser.add_argument("--out-root", default=str(OUT_ROOT))
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    df = load_1m_frame(symbol=str(args.symbol).upper(), max_bars=max(0, int(args.max_bars)))
    close = df["close"].astype(float)
    high = df["high"].astype(float)
    low = df["low"].astype(float)
    volume = df["volume"].astype(float)

    atr14 = compute_atr(high=high, low=low, close=close, window=14)
    atr24 = atr14.rolling(1440, min_periods=120).mean()
    atr24_ratio = (atr24 / close.replace(0.0, np.nan)).ffill().fillna(0.0)
    ret_1m = close.pct_change().fillna(0.0)
    rv60 = ret_1m.rolling(60, min_periods=20).std().fillna(0.0)
    rr = ((high - low) / close.replace(0.0, np.nan)).fillna(0.0)
    ret_z_60 = ((ret_1m - ret_1m.rolling(60, min_periods=20).mean()) / ret_1m.rolling(60, min_periods=20).std()).replace(
        [np.inf, -np.inf], np.nan
    ).fillna(0.0)
    vol_z_60 = ((volume - volume.rolling(60, min_periods=20).mean()) / volume.rolling(60, min_periods=20).std()).replace(
        [np.inf, -np.inf], np.nan
    ).fillna(0.0)

    feature_mat = np.column_stack(
        [
            np.ones(len(df), dtype=np.float64),
            (atr14 / close.replace(0.0, np.nan)).fillna(0.0).to_numpy(dtype=np.float64),
            rv60.to_numpy(dtype=np.float64),
            rr.to_numpy(dtype=np.float64),
            ret_z_60.abs().to_numpy(dtype=np.float64),
            vol_z_60.abs().to_numpy(dtype=np.float64),
        ]
    )
    target = atr24_ratio.shift(-1).ffill().fillna(0.0).to_numpy(dtype=np.float64)
    atr_hat = online_rls_forecast(feature_mat, target=target, lam=float(args.rls_lambda))

    trendline = rolling_trendline_last(close.to_numpy(dtype=np.float64), window=max(30, int(args.trend_window)))
    rsi = compute_rsi(close=close, window=max(5, int(args.rsi_window))).to_numpy(dtype=np.float64)

    equity = float(args.initial_capital)
    reserve = 0.0
    anchor = float(args.initial_capital)
    positions: list[Position] = []
    trades: list[dict[str, Any]] = []
    nav_rows: list[dict[str, Any]] = []
    fee_rate = max(0.0, float(args.fee_bps) + float(args.slippage_bps)) / 10_000.0

    close_arr = close.to_numpy(dtype=np.float64)
    high_arr = high.to_numpy(dtype=np.float64)
    low_arr = low.to_numpy(dtype=np.float64)
    ts_arr = df["ts"].to_numpy(dtype=np.int64)
    atr_arr = atr14.to_numpy(dtype=np.float64)
    ret_z_arr = ret_z_60.to_numpy(dtype=np.float64)
    vol_z_arr = vol_z_60.to_numpy(dtype=np.float64)

    start_idx = max(2000, int(args.trend_window) + 5)
    for i in range(start_idx, len(df)):
        price = float(close_arr[i])
        ts = int(ts_arr[i])
        atr_now = float(max(1e-8, atr_arr[i]))
        trend_now = float(trendline[i]) if np.isfinite(trendline[i]) else price
        rsi_now = float(rsi[i]) if np.isfinite(rsi[i]) else 50.0

        premium_raw = (abs(float(ret_z_arr[i])) + abs(float(vol_z_arr[i]))) / 6.0
        premium = _clip(premium_raw, 0.0, 1.0)
        x_val = _clip(float(args.k_atr) * float(atr_hat[i]) + float(args.k_premium) * premium, float(args.x_min), float(args.x_max))
        interval = max(1e-8, price * x_val)

        # Exit check first.
        bar_high = float(high_arr[i])
        bar_low = float(low_arr[i])
        still_open: list[Position] = []
        positive_credit = 0.0
        for pos in positions:
            tp = pos.entry_price + (float(args.tp_mult) * pos.interval * pos.side)
            sl = pos.entry_price - (float(args.sl_mult) * pos.interval * pos.side)
            exit_price = None
            exit_reason = None

            if pos.side > 0:
                if bar_low <= sl:
                    exit_price = sl
                    exit_reason = "sl"
                elif bar_high >= tp:
                    exit_price = tp
                    exit_reason = "tp"
            else:
                if bar_high >= sl:
                    exit_price = sl
                    exit_reason = "sl"
                elif bar_low <= tp:
                    exit_price = tp
                    exit_reason = "tp"

            if exit_price is None:
                still_open.append(pos)
                continue

            gross = float(pos.side) * (float(exit_price) - float(pos.entry_price)) * float(pos.qty)
            fees = (float(pos.entry_price) * float(pos.qty) + float(exit_price) * float(pos.qty)) * fee_rate
            pnl = gross - fees
            if pnl > 0.0:
                positive_credit += pnl
            else:
                equity += pnl
            trades.append(
                {
                    "open_ts": utc_iso(pos.open_ts),
                    "close_ts": utc_iso(ts),
                    "side": "long" if pos.side > 0 else "short",
                    "entry_price": pos.entry_price,
                    "exit_price": float(exit_price),
                    "qty": pos.qty,
                    "interval": pos.interval,
                    "pnl": pnl,
                    "reason": exit_reason,
                }
            )
        positions = [p for p in still_open if p.qty > 1e-10]
        if positive_credit > 0.0:
            leftover = reduce_losing_positions_with_credit(positions, positive_credit, price)
            equity += leftover

        # Entry rule.
        active_side = 0
        if positions:
            signed = sum(float(p.side) * float(p.qty) for p in positions)
            active_side = 1 if signed > 0 else (-1 if signed < 0 else 0)
        long_signal = bool(price < (trend_now - float(args.trend_beta) * atr_now) and rsi_now <= float(args.rsi_oversold))
        short_signal = bool(price > (trend_now + float(args.trend_beta) * atr_now) and rsi_now >= float(args.rsi_overbought))
        side_signal = 1 if long_signal else (-1 if short_signal else 0)

        if side_signal != 0 and len(positions) < max(1, int(args.max_layers)):
            if active_side == 0 or active_side == side_signal:
                base_ratio = tier_base_ratio(equity)
                cap_ratio = base_ratio * math.exp(-float(args.alpha) * max(0.0, (equity / float(args.initial_capital)) - 1.0))
                cap_ratio = _clip(cap_ratio, 0.005, 0.20)
                notional = max(20.0, equity * cap_ratio / max(1, int(args.max_layers)))
                qty = notional / max(price, 1e-8)
                if qty > 0:
                    positions.append(
                        Position(
                            side=side_signal,
                            entry_price=price,
                            qty=float(qty),
                            interval=float(interval),
                            open_ts=ts,
                            open_idx=i,
                        )
                    )

        # Doubling withdrawal.
        nav_unrealized = sum(unrealized_pnl(pos, price) for pos in positions)
        nav = equity + nav_unrealized
        if equity >= (2.0 * anchor):
            withdraw = equity * 0.50
            reserve += withdraw
            equity -= withdraw
            anchor = max(1.0, equity)
            trades.append(
                {
                    "open_ts": utc_iso(ts),
                    "close_ts": utc_iso(ts),
                    "side": "system",
                    "entry_price": price,
                    "exit_price": price,
                    "qty": 0.0,
                    "interval": interval,
                    "pnl": 0.0,
                    "reason": f"withdraw_{withdraw:.2f}",
                }
            )
            nav = equity + sum(unrealized_pnl(pos, price) for pos in positions)

        nav_rows.append(
            {
                "ts": utc_iso(ts),
                "equity_cash": equity,
                "reserve": reserve,
                "unrealized": nav - equity,
                "nav": nav,
                "open_layers": len(positions),
                "x_spacing": x_val,
                "interval": interval,
            }
        )

    # Force close remaining positions at final close.
    if len(df) > 0:
        final_price = float(close_arr[-1])
        final_ts = int(ts_arr[-1])
        for pos in positions:
            gross = float(pos.side) * (final_price - float(pos.entry_price)) * float(pos.qty)
            fees = (float(pos.entry_price) * float(pos.qty) + final_price * float(pos.qty)) * fee_rate
            pnl = gross - fees
            equity += pnl
            trades.append(
                {
                    "open_ts": utc_iso(pos.open_ts),
                    "close_ts": utc_iso(final_ts),
                    "side": "long" if pos.side > 0 else "short",
                    "entry_price": pos.entry_price,
                    "exit_price": final_price,
                    "qty": pos.qty,
                    "interval": pos.interval,
                    "pnl": pnl,
                    "reason": "eod",
                }
            )
        positions = []

    nav_df = pd.DataFrame(nav_rows)
    if nav_df.empty:
        raise RuntimeError("No NAV rows generated; dataset is too short.")
    nav_values = nav_df["nav"].to_numpy(dtype=np.float64)
    final_nav = float(nav_values[-1] + reserve)
    total_return = (final_nav / float(args.initial_capital)) - 1.0

    trades_df = pd.DataFrame(trades)
    closed = trades_df[trades_df["side"].isin(["long", "short"])].copy() if not trades_df.empty else pd.DataFrame()
    wins = int((closed["pnl"] > 0.0).sum()) if not closed.empty else 0
    total_closed = int(len(closed))
    win_rate = float(wins / total_closed) if total_closed > 0 else 0.0

    summary = {
        "run_id": f"nonlinear_grid_{now_stamp()}",
        "generated_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "symbol": str(args.symbol).upper(),
        "timeframe": "1m",
        "bars": int(len(df)),
        "initial_capital": float(args.initial_capital),
        "final_equity_cash": float(equity),
        "final_reserve": float(reserve),
        "final_total_value": float(final_nav),
        "total_return_pct": float(total_return * 100.0),
        "max_drawdown_pct": float(max_drawdown(nav_values) * 100.0),
        "sharpe_1m_annualized": float(sharpe_ratio(nav_values)),
        "closed_trades": total_closed,
        "win_rate": win_rate,
        "model": {
            "spacing": "interval = price * clip(k_atr*atr_hat + k_premium*sentiment, x_min, x_max)",
            "allocation": "tier_base(15/10/5) * exp(-alpha*(equity/initial_capital-1))",
            "debt_repair": "positive pnl preferentially reduces oldest losing layers",
            "withdrawal": "equity >= 2*anchor => withdraw 50%",
        },
        "params": vars(args),
    }

    out_root = Path(args.out_root)
    run_dir = out_root / summary["run_id"]
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    trades_df.to_csv(run_dir / "trades.csv", index=False)
    nav_df.to_csv(run_dir / "equity_curve.csv", index=False)

    md_lines = [
        "# Nonlinear Grid Backtest Report",
        "",
        f"- run_id: `{summary['run_id']}`",
        f"- symbol/timeframe: `{summary['symbol']} / {summary['timeframe']}`",
        f"- bars: `{summary['bars']}`",
        f"- initial_capital: `{summary['initial_capital']:.2f}`",
        f"- final_total_value: `{summary['final_total_value']:.2f}`",
        f"- total_return_pct: `{summary['total_return_pct']:+.2f}%`",
        f"- max_drawdown_pct: `{summary['max_drawdown_pct']:.2f}%`",
        f"- sharpe_1m_annualized: `{summary['sharpe_1m_annualized']:.3f}`",
        f"- closed_trades: `{summary['closed_trades']}`",
        f"- win_rate: `{summary['win_rate']:.3f}`",
        "",
        "## Strategy",
        "- Dynamic spacing from online RLS ATR forecast + sentiment premium",
        "- Tiered base allocation (15/10/5) with exponential scale-down",
        "- Profit-first loss repair on oldest losing layers",
        "- Doubling-withdrawal circuit breaker",
    ]
    report_md = "\n".join(md_lines) + "\n"
    (run_dir / "report.md").write_text(report_md, encoding="utf-8")
    LOG_LATEST_MD.parent.mkdir(parents=True, exist_ok=True)
    LOG_LATEST_MD.write_text(report_md, encoding="utf-8")

    print(json.dumps({"ok": True, "run_dir": str(run_dir), "summary": summary}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
