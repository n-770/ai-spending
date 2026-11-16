#!/usr/bin/env python3
"""Rolling-origin gate: does TimesFM beat the pace baselines on the SUM at horizon?

Usage:
    python backtest.py --jsonl                 # logged series
    python backtest.py --csv spend.csv         # date,value
    python backtest.py --synthetic 150         # generated (plumbing only)
    add --timesfm to include the model

Promotion rule: beat the best baseline on mean cumulative error by >=10%
while winning >=60% of origins.
"""

from __future__ import annotations

import argparse
import csv
import sys
from datetime import date, timedelta

import numpy as np

import methods
import series


def load_csv(path: str) -> tuple[np.ndarray, int]:
    rows: dict[date, float] = {}
    with open(path, newline="") as fh:
        for row in csv.DictReader(fh):
            key = row.get("date") or row.get("day")
            val = (row.get("value") or row.get("total_usage") or row.get("cost_usd")
                   or row.get("spend"))
            if not key or val is None:
                sys.exit("csv needs date,value columns")
            rows[date.fromisoformat(str(key)[:10])] = float(val)
    if not rows:
        sys.exit("csv has no rows")
    start, end = min(rows), max(rows)
    out, cur = [], start
    while cur <= end:                       # missing days are real zeros
        out.append(rows.get(cur, 0.0))
        cur += timedelta(days=1)
    return np.asarray(out, dtype=np.float64), start.weekday()


def synthetic(n_days: int = 150, seed: int = 7) -> np.ndarray:
    rng = np.random.default_rng(seed)
    weekday_f = np.array([1.0, 1.35, 1.3, 1.25, 1.2, 0.95, 0.45])
    out, level = [], 1.0
    for i in range(n_days):
        level *= rng.normal(1.004, 0.02)
        base = level * weekday_f[i % 7]
        if rng.random() < 0.10:
            base *= 0.15
        if rng.random() < 0.07:
            base *= rng.uniform(2.5, 6.0)
        out.append(max(0.0, base * rng.lognormal(0, 0.18)))
    return np.asarray(out, dtype=np.float64)


def main() -> int:
    ap = argparse.ArgumentParser()
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--csv")
    src.add_argument("--jsonl", action="store_true")
    src.add_argument("--synthetic", type=int)
    ap.add_argument("--horizon", type=int, default=30)
    ap.add_argument("--stride", type=int, default=5)
    ap.add_argument("--min-context", type=int, default=45)
    ap.add_argument("--timesfm", action="store_true")
    args = ap.parse_args()

    start_wd = 0
    if args.csv:
        values, start_wd = load_csv(args.csv)
        label = args.csv
    elif args.jsonl:
        dates, values = series.load_series()
        values = np.asarray(values, dtype=np.float64)
        start_wd = dates[0].weekday() if dates else 0
        label = "logged series"
    else:
        values = synthetic(args.synthetic)
        label = f"synthetic({args.synthetic})"

    h = args.horizon
    origins = list(range(args.min_context, len(values) - h + 1, args.stride))
    if len(origins) < 6:
        print(f"series={label} points={len(values)} origins={len(origins)}: "
              f"need >=6 origins of {h}d; keep logging or backfill first")
        return 1

    name, model = methods.load_model() if args.timesfm else (None, None)
    if args.timesfm and model is None:
        print(f"timesfm unavailable: {methods.os.environ.get('AI_SPENDING_MODEL_ERRORS', '?')}")

    cum: dict[str, list[float]] = {}
    daily: dict[str, list[float]] = {}
    for origin in origins:
        ctx, actual = values[:origin], values[origin:origin + h]
        preds = methods.baselines(ctx, h, first_weekday=start_wd)
        if model is not None and len(ctx) >= methods.MIN_CONTEXT:
            comp = methods.timesfm_components(name or "", model, ctx, h)
            preds[f"{name}_mean"] = comp["mean"]
            preds[f"{name}_median"] = comp["median"]
        for label_, pred in preds.items():
            pred = np.clip(np.asarray(pred, dtype=float), 0, None)
            cum.setdefault(label_, []).append(abs(pred.sum() - actual.sum()))
            daily.setdefault(label_, []).append(float(np.abs(pred - actual).mean()))

    base = min((k for k in cum if not k.startswith("timesfm")), key=lambda k: np.mean(cum[k]))
    print(f"series={label} points={len(values)} origins={len(origins)} horizon={h}d base={base}")
    print(f"{'method':<18}{'mean|cum err|':>14}{'median':>9}{'daily MAE':>12}{'wins':>8}")
    for key in cum:
        wins = sum(a < b for a, b in zip(cum[key], cum[base])) / len(cum[key])
        print(f"{key:<18}{np.mean(cum[key]):>14.2f}{np.median(cum[key]):>9.2f}"
              f"{np.mean(daily[key]):>12.3f}{wins:>7.0%}")

    if model is not None:
        best_model = min((k for k in cum if k.startswith("timesfm")), key=lambda k: np.mean(cum[k]))
        gain = 1 - np.mean(cum[best_model]) / np.mean(cum[base])
        wins = sum(a < b for a, b in zip(cum[best_model], cum[base])) / len(cum[best_model])
        verdict = "PASS" if gain >= 0.10 and wins >= 0.60 else "FAIL"
        print(f"\ngate: {best_model} {gain:+.1%} cum-error gain, {wins:.0%} wins vs {base} -> {verdict}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
