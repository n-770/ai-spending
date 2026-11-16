#!/usr/bin/env python3
"""Ingest OpenRouter Activity CSV exports (daily rollup) into spend-daily.jsonl.

The exports are per-model rows with a `date__day` column:
    date__day,model,total_usage,request_count

This script aggregates them to one calendar day per row and upserts into the
append-only log used by forecast.py. No API key is needed: the CSVs come from
the Activity page.

Usage:
    python ingest_activity.py --csv-dir ../../export/daily
    python ingest_activity.py --csv-dir ../../export/daily --dry-run
    python ingest_activity.py --csv-dir ../../export/daily --drop-incomplete-last-day

Missing days inside the export range are written as real 0.0 only when they are
absent from every file; --dry-run prints the diagnostics without touching the log.
"""

from __future__ import annotations

import argparse
import csv
import sys
from collections import defaultdict
from collections.abc import Sequence
from datetime import date, datetime, timedelta
from pathlib import Path

import series
import spendlog


def _find_col(fieldnames: Sequence[str] | None, *candidates: str) -> str | None:
    names = list(fieldnames or [])
    low = {f.strip().lower(): f for f in names}
    for c in candidates:
        if c in low:
            return low[c]
    for f in names:
        if any(c in f.strip().lower() for c in candidates):
            return f
    return None


def parse_files(paths: list[Path]) -> tuple[dict[date, dict], list[str]]:
    """Aggregate every CSV into {day: {usage, requests, models}}.

    Files often overlap (usage-by-model / usage-type are identical exports), so
    the same (day, model) can appear twice; per file we de-duplicate by model and
    then take the file that covers the widest date range as the authority per day.
    """
    warnings: list[str] = []
    per_source: list[tuple[Path, dict[date, dict]]] = []

    for path in paths:
        rows: dict[date, dict] = {}
        dup = 0
        with path.open(newline="") as fh:
            reader = csv.DictReader(fh)
            if not reader.fieldnames:
                warnings.append(f"{path.name}: empty")
                continue
            dcol = _find_col(reader.fieldnames, "date__day", "date")
            scol = _find_col(reader.fieldnames, "total_usage", "usage", "spend", "cost")
            rcol = _find_col(reader.fieldnames, "request_count", "requests")
            mcol = _find_col(reader.fieldnames, "model")
            if not dcol or not scol:
                warnings.append(f"{path.name}: no date/usage column, skipped")
                continue

            seen: set[tuple[date, str]] = set()
            for row in reader:
                raw = (row.get(dcol) or "").strip()
                if not raw:
                    continue
                try:
                    day = date.fromisoformat(raw[:10])
                except ValueError:
                    warnings.append(f"{path.name}: bad date {raw!r}")
                    continue
                day = day  # type: ignore[assignment]
                key = (day, (row.get(mcol) or "").strip() if mcol else "")
                if key in seen:
                    dup += 1
                    continue
                seen.add(key)
                try:
                    usage = float((row.get(scol) or "0").replace("$", "").replace(",", ""))
                except ValueError:
                    warnings.append(f"{path.name}: bad usage {row.get(scol)!r}")
                    continue
                agg = rows.setdefault(day, {"usage": 0.0, "requests": 0, "models": 0})
                agg["usage"] += max(0.0, usage)
                if rcol:
                    try:
                        agg["requests"] += int(float(row.get(rcol) or 0))
                    except ValueError:
                        pass
                agg["models"] += 1
        if dup:
            warnings.append(f"{path.name}: {dup} duplicate (day,model) rows collapsed")
        if rows:
            per_source.append((path, rows))

    if not per_source:
        return {}, warnings

    # Merge: a day takes the value from the file with the most days (widest export).
    per_source.sort(key=lambda pr: len(pr[1]), reverse=True)
    merged: dict[date, dict] = {}
    for path, rows in per_source:
        for day, agg in rows.items():
            if day not in merged or agg["usage"] > merged[day]["usage"]:
                merged[day] = dict(agg, source=path.name)
    return merged, warnings


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv-dir", help="directory of Activity exports")
    ap.add_argument("--csv", action="append", default=[], help="individual CSV (repeatable)")
    ap.add_argument("--drop-incomplete-last-day", action="store_true",
                    help="do not write today's partial row")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    paths = [Path(p).expanduser() for p in args.csv]
    if args.csv_dir:
        paths += sorted(Path(args.csv_dir).expanduser().glob("*.csv"))
    if not paths:
        ap.error("give --csv-dir or --csv")

    merged, warnings = parse_files(paths)
    if not merged:
        print("ingest: no rows parsed", file=sys.stderr)
        return 2

    days = sorted(merged)
    start, end = days[0], days[-1]
    today = series.utc_today()
    missing = [start + timedelta(days=i) for i in range((end - start).days + 1)
               if (start + timedelta(days=i)) not in merged]

    if args.drop_incomplete_last_day and end >= today:
        merged.pop(end, None)
        print(f"ingest: dropped partial day {end}")

    print(f"ingest: {len(paths)} file(s) -> {len(merged)} days {start}..{end}")
    print(f"ingest: missing calendar days inside range: {len(missing)}"
          + (f" ({missing[0]}..{missing[-1]})" if missing else ""))
    by_month: dict[str, float] = defaultdict(float)
    for d, a in merged.items():
        by_month[f"{d.year}-{d.month:02d}"] += a["usage"]
    for m in sorted(by_month):
        print(f"ingest:   {m}: ${by_month[m]:.2f}")
    last = merged[max(merged)]
    print(f"ingest: last day {max(merged)} ${last['usage']:.4f} "
          f"({last['requests']} req, {last['models']} models)")
    for w in warnings[:10]:
        print(f"ingest: WARN {w}", file=sys.stderr)

    if args.dry_run:
        print("ingest: dry-run, log untouched")
        return 0

    keep = {r["day"]: r for r in series.load_rows()}
    for d in sorted(merged):
        a = merged[d]
        extra = {
            "requests": a["requests"],
            "models": a["models"],
            "source": a.get("source", "activity-export"),
        }
        # Do not drop provider-reported windows the snapshot job wrote.
        prior = keep.get(d.isoformat(), {})
        for k in ("usage_monthly", "usage_weekly", "usage_daily"):
            if isinstance(prior.get(k), (int, float)):
                extra[k] = prior[k]
        series.append_day(d, a["usage"], extra)
    print(f"ingest: wrote {len(merged)} days to {series.LOG}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
