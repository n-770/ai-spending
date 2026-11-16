#!/usr/bin/env python3
"""Write forecast.json: projected spend for the current UTC month to date + rest of month.

Contract (read by the menu-bar app, which never loads a model itself):
    spent_mtd, projected_total, low, high, horizon_days, method, context_points,
    data_days, stale_days, generated_at, period_start, period_end

Rule: the projected total uses the MEAN daily estimate. The median of a spiky
daily series under-forecasts the sum and must not be used for budget numbers.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime, timedelta, timezone

import numpy as np

import methods
import series
import spendlog

OUT = spendlog.APP_SUPPORT / "forecast.json"

# The model stays out of the displayed number until it wins the gate. Measured on
# 101 real days / 47 rolling month-end origins: timesfm3_mean made month-end errors
# 33% WORSE than the 14-day weekday-seasonal pace (77.32 vs 57.95 mean |error|), and
# the median head was worse still (103.70). Re-run gate_monthend.py before flipping.
MODEL_PROMOTED = False


def build(day, dates, values, model_name, model, horizon_cap: int = 31,
          provider_mtd: float | None = None) -> dict:
    first, last = series.month_bounds(day)
    by_day = dict(zip(dates, values))

    logged_mtd = sum(v for d, v in by_day.items() if first <= d <= day)
    # Provider-reported month-to-date is authoritative; logged rows may be partial.
    spent_mtd = provider_mtd if (provider_mtd is not None and provider_mtd >= logged_mtd) else logged_mtd
    complete = [v for d, v in by_day.items() if first <= d < day]
    ctx = np.asarray([v for d, v in by_day.items() if d < day], dtype=float)
    h = max(0, min(horizon_cap, (last - day).days))

    pace_mean = float(np.mean(ctx[-28:])) if len(ctx) else 0.0
    pace_total = spent_mtd + pace_mean * h
    # Weekday-seasonal pace over the last 14 days: the shipped fallback.
    first_weekday = (day.weekday() + 1) % 7
    seas = methods.seasonal_recent(ctx, h, first_weekday) if h > 0 else np.zeros(0)
    seasonal_total = spent_mtd + float(seas.sum())

    result = {
        "period_start": first.isoformat(),
        "period_end": last.isoformat(),
        "as_of": day.isoformat(),
        "spent_mtd": round(spent_mtd, 4),
        "days_complete_in_month": len(complete),
        "horizon_days": h,
        "data_days": len(ctx),
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }

    if model is not None and len(ctx) >= methods.MIN_CONTEXT and h > 0:
        comp = methods.timesfm_components(model_name, model, ctx, h)
        projected = spent_mtd + float(comp["mean"][:h].sum())
        result.update({
            "projected_total": round(projected, 4),
            "low": round(spent_mtd + float(comp["low"][:h].sum()), 4),
            "high": round(spent_mtd + float(comp["high"][:h].sum()), 4),
            "method": f"{model_name}-mean",
            "context_points": int(min(len(ctx), methods.CONTEXT_WINDOW)),
        })
    elif h == 0:
        result.update({
            "projected_total": round(spent_mtd, 4),
            "low": None,
            "high": None,
            "method": "month-complete",
            "context_points": 0,
            "fallback_reason": "horizon 0",
        })
    else:
        # Weekday-seasonal over 14 days. Gate-verified: 40/47 rolling month-end
        # origins, -27% mean error vs the flat 28-day pace.
        why = (None if len(ctx) >= methods.SEASONAL_WINDOW
               else f"history {len(ctx)}d < {methods.SEASONAL_WINDOW}d")
        result.update({
            "projected_total": round(seasonal_total, 4),
            "low": None,
            "high": None,
            "method": "seasonal-14d",
            "context_points": int(min(len(ctx), methods.SEASONAL_WINDOW)),
        })
        if why:
            result["fallback_reason"] = why
        if model is None:
            errs = methods.os.environ.get("AI_SPENDING_MODEL_ERRORS")
            result["model_status"] = f"unavailable: {errs}" if errs else "gated-out"

    result["pace_baseline_total"] = round(pace_total, 4)
    result["seasonal_total"] = round(seasonal_total, 4)
    result["preliminary"] = h > 0 and len(ctx) < 7
    result["spent_source"] = ("provider-usage_monthly" if spent_mtd > logged_mtd
                              else "logged-series")
    result["logged_mtd"] = round(logged_mtd, 4)
    result["stale_days"] = max(0, (day - dates[-1]).days) if dates else None
    errors = methods.os.environ.get("AI_SPENDING_MODEL_ERRORS")
    if errors:
        result["model_errors"] = errors
    return result


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", action="store_true",
                    help="also compute the TimesFM branch (recorded as model_projection, "
                         "not displayed while it fails the gate)")
    ap.add_argument("--no-model", action="store_true", help="pace/seasonal only (default)")
    ap.add_argument("--force-model", action="store_true",
                    help="display the model number even though it fails the gate")
    ap.add_argument("--print", action="store_true", help="also print the JSON")
    args = ap.parse_args()

    day = series.utc_today()
    dates, values = series.load_series()
    if not dates:
        print("forecast: no logged spend yet; run snapshot.py or ingest_activity.py first",
              file=sys.stderr)
        return 3

    name, model = (None, None)
    if (args.model or args.force_model) and not args.no_model:
        name, model = methods.load_model()
    shown = model if (args.force_model or MODEL_PROMOTED) else None

    provider_mtd = None
    first, _ = series.month_bounds(day)
    for row in reversed(series.load_rows()):
        if row.get("day") and first <= date.fromisoformat(row["day"]) <= day:
            if isinstance(row.get("usage_monthly"), (int, float)):
                provider_mtd = float(row["usage_monthly"])
                break

    result = build(day, dates, values, name, shown, provider_mtd=provider_mtd)

    # Record what the model would have said, without showing it to the user.
    if model is not None and shown is None:
        shadow = build(day, dates, values, name, model, provider_mtd=provider_mtd)
        result["model_projection"] = {
            "method": shadow["method"],
            "projected_total": shadow["projected_total"],
            "low": shadow["low"],
            "high": shadow["high"],
        }
        result["model_status"] = "gated-out: worse than seasonal-14d on real month-end origins"

    spendlog.APP_SUPPORT.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")

    print(f"forecast: {result['as_of']} spent ${result['spent_mtd']:.2f} "
          f"-> projected ${result['projected_total']:.2f} "
          f"({result['method']}, {result['horizon_days']}d left, "
          f"{result['data_days']}d history)")
    if result.get("stale_days"):
        print(f"forecast: WARNING series is {result['stale_days']}d stale", file=sys.stderr)
    if args.print:
        print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
