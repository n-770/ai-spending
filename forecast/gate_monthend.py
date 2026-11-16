#!/usr/bin/env python3
"""Month-end gate: the metric the app actually shows.

Rolling origins at every complete day, horizon = days left in that UTC month.
Target = the real sum from the next day to month end. This differs from
backtest.py (fixed 30-day blocks) by asking the product question each day:
"how wrong would the projected month-end total have been?"

Usage:
    python gate_monthend.py --jsonl --timesfm
    python gate_monthend.py --csv spend.csv --min-context 45
"""

from __future__ import annotations

import argparse
import sys

import numpy as np

import methods
import series


def load_csv(path: str) -> tuple[list, list]:
    import csv
    from datetime import date, timedelta

    rows: dict[date, float] = {}
    with open(path, newline="") as fh:
        for row in csv.DictReader(fh):
            key = row.get("date") or row.get("day")
            val = row.get("value") or row.get("total_usage") or row.get("spend")
            if not key or val is None:
                sys.exit("csv needs date,value columns")
            rows[date.fromisoformat(str(key)[:10])] = float(val)
    start, end = min(rows), max(rows)
    dates, values, cur = [], [], start
    while cur <= end:
        dates.append(cur)
        values.append(rows.get(cur, 0.0))
        cur += timedelta(days=1)
    return dates, values


def main() -> int:
    ap = argparse.ArgumentParser()
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--csv")
    src.add_argument("--jsonl", action="store_true")
    ap.add_argument("--min-context", type=int, default=45)
    ap.add_argument("--timesfm", action="store_true")
    ap.add_argument("--detail", action="store_true", help="per-origin rows")
    args = ap.parse_args()

    if args.csv:
        dates, values = load_csv(args.csv)
        label = args.csv
    else:
        dates, values = series.load_series()
        label = "logged series"
    values = np.asarray(values, dtype=np.float64)
    if not len(values):
        print("gate: empty series")
        return 1

    ends: list[int] = []
    for i, d in enumerate(dates):
        _, last = series.month_bounds(d)
        j = dates.index(last) if last in dates else -1
        ends.append(j)
    # index lookup without O(n^2)
    pos = {d: i for i, d in enumerate(dates)}

    origins = []
    for i, d in enumerate(dates):
        if i + 1 < args.min_context:
            continue
        _, last = series.month_bounds(d)
        j = pos.get(last)
        if j is None or j <= i:          # month not complete yet -> no ground truth
            continue
        origins.append((i, i + 1, j + 1))   # ctx end, target start, target stop

    if len(origins) < 6:
        print(f"gate: pts={len(values)} origins={len(origins)} (need >=6 complete month-ends)")
        return 1

    name, model = methods.load_model() if args.timesfm else (None, None)
    if args.timesfm and model is None:
        print(f"timesfm unavailable: {methods.os.environ.get('AI_SPENDING_MODEL_ERRORS', '?')}")

    err: dict[str, list[float]] = {}
    pct: dict[str, list[float]] = {}
    rows = []
    for ctx_end, tgt_start, tgt_stop in origins:
        ctx = values[:ctx_end]
        actual = float(values[tgt_start:tgt_stop].sum())
        h = tgt_stop - tgt_start
        preds = methods.baselines(ctx, h, first_weekday=dates[0].weekday())
        if model is not None and len(ctx) >= methods.MIN_CONTEXT:
            comp = methods.timesfm_components(name or "", model, ctx, h)
            preds[f"{name}_mean"] = comp["mean"]
            preds[f"{name}_median"] = comp["median"]
        for k, p in preds.items():
            pred = float(np.clip(np.asarray(p, dtype=float), 0, None)[:h].sum())
            err.setdefault(k, []).append(abs(pred - actual))
            if actual > 0:
                pct.setdefault(k, []).append(abs(pred - actual) / actual)
        rows.append((dates[ctx_end - 1], dates[tgt_stop - 1], h, actual,
                     {k: float(np.clip(np.asarray(p, dtype=float), 0, None)[:h].sum())
                      for k, p in preds.items()}))

    base = min((k for k in err if not k.startswith("timesfm")), key=lambda k: np.mean(err[k]))
    print(f"series={label} pts={len(values)} origins={len(origins)} base={base} "
          f"mean_actual=${np.mean([r[3] for r in rows]):.2f}")
    print(f"{'method':<18}{'mean |err|':>12}{'median':>9}{'MAPE':>8}{'wins':>7}")
    for k in err:
        wins = sum(a < b for a, b in zip(err[k], err[base])) / len(err[k])
        print(f"{k:<18}{np.mean(err[k]):>12.2f}{np.median(err[k]):>9.2f}"
              f"{100 * np.mean(pct[k]):>7.1f}%{wins:>6.0%}")

    if args.detail:
        print("\norigin      month_end   h  actual " + " ".join(f"{k:>16}" for k in err))
        for d, e, h, actual, preds in rows:
            print(f"{d}  {e}  {h:>2} {actual:>7.2f} "
                  + " ".join(f"{preds[k]:>16.2f}" for k in err))

    if model is not None:
        best = min((k for k in err if k.startswith("timesfm")), key=lambda k: np.mean(err[k]))
        gain = 1 - np.mean(err[best]) / np.mean(err[base])
        wins = sum(a < b for a, b in zip(err[best], err[base])) / len(err[best])
        verdict = "PASS" if gain >= 0.10 and wins >= 0.60 else "FAIL"
        print(f"\ngate: {best} {gain:+.1%} mean-error gain, {wins:.0%} wins vs {base} -> {verdict}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
