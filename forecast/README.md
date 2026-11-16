# Forecast pipeline (AI Spending)

Runs outside the app: a scheduled job logs daily spend and writes `forecast.json`;
the menu-bar app only renders it. No model runs inside the Swift binary.

## Why TimesFM 3.0 here

The app is free, open source and non-commercial, so the TimesFM **3.0** weights
(non-commercial licence) are permitted. A commercial build would have to drop to
**2.5** (Apache-2.0) — the code already falls back to it.

## Data

| Piece | Where |
|---|---|
| Daily series (one row per UTC day) | `~/Library/Application Support/AI-Spending/spend-daily.jsonl` |
| Forecast output | `~/Library/Application Support/AI-Spending/forecast.json` |
| Live source (regular inference key) | `GET https://openrouter.ai/api/v1/key` → `usage_daily` |
| Backfill source (no key) | Activity page CSV exports → `export/daily/`, ingested by `ingest_activity.py` |
| Backfill source (management key) | `POST https://openrouter.ai/api/v1/analytics/query`, `granularity=day` |

A day with no usage is stored as a real `0.0` — gaps would hide weekday seasonality.
The Activity export omits zero-days entirely, so absent dates inside the export range
become `0.0`, not gaps.

### Ingesting an Activity export (no key needed)

Download from `openrouter.ai/activity` with **Group by: Day** for the widest range, drop the
CSVs in `export/daily/`, then:

```sh
"$PY" ingest_activity.py --csv-dir ../../export/daily --dry-run   # diagnostics only
"$PY" ingest_activity.py --csv-dir ../../export/daily             # upsert into the log
```

Per-model rows are summed per day. Files that overlap are de-duplicated per `(day, model)`,
and a day takes the value from the widest export. Existing `usage_monthly` fields written by
`snapshot.py` are preserved.

## Keys

- Inference key: app Keychain item (`com.personal.openrouter-spend` / `openrouter-api-key`),
  else `OPENROUTER_API_KEY`, else `~/.hermes/.env`.
- Management key (backfill only): Keychain item `com.personal.openrouter-spend.analytics`
  account `management-key`, else `OPENROUTER_MANAGEMENT_KEY`.
  Create it at `openrouter.ai/settings/management-keys`. Regular keys get a 403 from analytics.

Nothing prints or logs key material.

## Commands

```sh
PY="$HOME/Library/Application Support/AI-Spending/venv/bin/python"

"$PY" snapshot.py                  # append/update today's row
"$PY" ingest_activity.py --csv-dir ../../export/daily   # backfill from Activity CSVs (no key)
"$PY" backfill.py --days 120       # optional: needs the management key
"$PY" gate_monthend.py --jsonl --timesfm   # the gate on real data (the metric the app shows)
"$PY" backtest.py --jsonl --timesfm        # fixed 30-day blocks, for comparison
"$PY" forecast.py                  # write forecast.json (seasonal, model gated out)
"$PY" forecast.py --model --print  # also record what the model would have said
"$PY" -m unittest discover -s tests -v
```

## Rule the code enforces

The displayed month-end total is the **weekday-seasonal pace over the last 14 days**
(`seasonal-14d`): mean daily level of the window, times each weekday's own factor, with the
factor shrunk halfway toward 1 so a single spike day cannot inflate one weekday for the whole
horizon. A flat 28-day pace (`pace_baseline_total`) is always written alongside it.

The median is never used for a budget number: on spiky spend it under-forecasts the sum badly.
Context is the recent window, not all history — cron fleets and model switches move the level.

## Gate results on real data (101 logged days, 47 rolling month-end origins)

```
method              mean |err|   median    MAPE   wins
seasonal_14d             57.95    35.60  133.6%    0%   <- shipped
timesfm3_mean            77.32    26.73  117.5%   57%
seasonal_wd              78.21    44.58   93.3%   28%
naive_28d                78.80    39.81  146.9%   26%
naive_7d                 81.58    48.40  128.2%   47%
timesfm3_median         103.70    42.42  107.5%   21%
```

TimesFM 3.0 **fails**: its mean head is 33% worse than the shipped seasonal pace on dollar
error, and the median head is nearly 2x worse. It also has the smallest under-forecast bias
of the seasonal family (-36 vs -60 for the flat pace), so the win is not just "a lower number".

Where the model *does* win: on a stable month (September origins) it produced the smallest
errors of any method (15.6 vs 26.4). It loses on regime breaks — October's spend collapsed
4x mid-month and the model, anchored on longer history, projected the old level for weeks.
Before promoting it, re-run `gate_monthend.py`; it must beat `seasonal_14d` by >=10%.

## Schedule

`launchd/com.personal.ai-spending.snapshot.plist` — hourly, idempotent.
`launchd/com.personal.ai-spending.forecast.plist` — every 6 hours.
