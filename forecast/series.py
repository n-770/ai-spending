"""Daily spend series: append-only JSONL log + calendar-complete series builder."""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone

from spendlog import APP_SUPPORT

LOG = APP_SUPPORT / "spend-daily.jsonl"


def utc_today(now: datetime | None = None) -> date:
    return (now or datetime.now(timezone.utc)).date()


def append_day(day: date, usage_daily: float, extra: dict | None = None) -> None:
    """Upsert one UTC day. Later calls for the same day update the row in place."""
    APP_SUPPORT.mkdir(parents=True, exist_ok=True)
    record = {"day": day.isoformat(), "usage": round(float(usage_daily), 6)}
    if extra:
        record.update(extra)
    record["logged_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")

    rows: dict[str, dict] = {}
    if LOG.exists():
        for line in LOG.read_text().splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if row.get("day"):
                rows[row["day"]] = row
    rows[record["day"]] = record

    tmp = LOG.with_suffix(".jsonl.tmp")
    tmp.write_text("\n".join(json.dumps(rows[k], sort_keys=True) for k in sorted(rows)) + "\n")
    tmp.replace(LOG)


def load_rows() -> list[dict]:
    if not LOG.exists():
        return []
    out = []
    for line in LOG.read_text().splitlines():
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return sorted(out, key=lambda r: r["day"])


def load_series(first: date | None = None, last: date | None = None):
    """Calendar-complete (dates, values). A day with no usage is a real 0.0, not a gap."""
    rows = load_rows()
    if not rows:
        return [], []
    by_day = {r["day"]: float(r.get("usage") or 0.0) for r in rows}
    start = first or date.fromisoformat(min(by_day))
    end = last or date.fromisoformat(max(by_day))
    if end < start:
        return [], []
    dates, values, cur = [], [], start
    while cur <= end:
        dates.append(cur)
        values.append(by_day.get(cur.isoformat(), 0.0))
        cur += timedelta(days=1)
    return dates, values


def month_bounds(day: date) -> tuple[date, date]:
    first = day.replace(day=1)
    nxt = (first.replace(year=first.year + 1, month=1) if first.month == 12
           else first.replace(month=first.month + 1))
    return first, nxt - timedelta(days=1)
