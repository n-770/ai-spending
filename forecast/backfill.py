#!/usr/bin/env python3
"""Backfill daily spend from OpenRouter analytics. Requires a management key.

Usage:
    OPENROUTER_MANAGEMENT_KEY=... python backfill.py --days 120
    python backfill.py --days 120          # key from Keychain/env

Writes one row per day into the same JSONL the snapshot job uses, so the
backtest and the live forecast read a single series.
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta, timezone

import series
import spendlog


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=120, help="how far back to pull")
    args = ap.parse_args()

    try:
        key = spendlog.analytics_key()
    except spendlog.NoKey as exc:
        print(f"backfill: {exc}", file=sys.stderr)
        return 2

    now = datetime.now(timezone.utc)
    start = (now - timedelta(days=args.days)).replace(hour=0, minute=0, second=0, microsecond=0)
    rows = spendlog.analytics_daily(key, start.isoformat(), now.isoformat())
    if not rows:
        print("backfill: analytics returned no rows", file=sys.stderr)
        return 3

    for row in rows:
        series.append_day(datetime.fromisoformat(row["day"]).date(),
                          row["usage"], {"source": "analytics", "requests": row["requests"]})

    total = sum(r["usage"] for r in rows)
    print(f"backfill: {len(rows)} days ({rows[0]['day']}..{rows[-1]['day']}), total ${total:.2f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
