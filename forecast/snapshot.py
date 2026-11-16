#!/usr/bin/env python3
"""Daily snapshot: one row per UTC day of this key's OpenRouter usage.

Idempotent — re-running within the same UTC day updates that day's row.
Exit codes: 0 ok, 2 no key, 3 provider/network error.
"""

from __future__ import annotations

import sys

import series
import spendlog


def main() -> int:
    try:
        key = spendlog.inference_key()
    except spendlog.NoKey as exc:
        print(f"snapshot: {exc}", file=sys.stderr)
        return 2
    try:
        usage = spendlog.key_usage(key)
    except Exception as exc:                                   # noqa: BLE001
        print(f"snapshot: provider error: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 3

    if "usage_daily" not in usage:
        print("snapshot: response has no usage_daily; nothing written", file=sys.stderr)
        return 3

    day = series.utc_today()
    series.append_day(day, usage["usage_daily"], {
        "usage_weekly": usage.get("usage_weekly"),
        "usage_monthly": usage.get("usage_monthly"),
        "limit_remaining": usage.get("limit_remaining"),
        "free_tier": usage.get("is_free_tier"),
    })
    print(f"snapshot: {day.isoformat()} usage_daily={usage['usage_daily']:.4f} "
          f"monthly={usage.get('usage_monthly', 0.0):.4f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
