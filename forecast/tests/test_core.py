#!/usr/bin/env python3
"""Stdlib-only tests for the pure parts of the forecast pipeline."""

import sys
import unittest
from datetime import date
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import methods  # noqa: E402
import series  # noqa: E402


class CalendarTests(unittest.TestCase):
    def test_month_bounds_leap_and_year_end(self):
        self.assertEqual(series.month_bounds(date(2026, 2, 14)), (date(2026, 2, 1), date(2026, 2, 28)))
        self.assertEqual(series.month_bounds(date(2028, 2, 3)), (date(2028, 2, 1), date(2028, 2, 29)))
        self.assertEqual(series.month_bounds(date(2026, 12, 31)), (date(2026, 12, 1), date(2026, 12, 31)))

    def test_missing_day_is_zero_not_gap(self):
        import tempfile
        from pathlib import Path as P
        with tempfile.TemporaryDirectory() as tmp:
            series.APP_SUPPORT = P(tmp)
            series.LOG = P(tmp) / "spend-daily.jsonl"
            series.append_day(date(2026, 11, 1), 1.0)
            series.append_day(date(2026, 11, 4), 2.0)
            dates, values = series.load_series()
            self.assertEqual(len(dates), 4)
            self.assertEqual(values, [1.0, 0.0, 0.0, 2.0])

    def test_append_is_idempotent_per_day(self):
        import tempfile
        from pathlib import Path as P
        with tempfile.TemporaryDirectory() as tmp:
            series.APP_SUPPORT = P(tmp)
            series.LOG = P(tmp) / "spend-daily.jsonl"
            series.append_day(date(2026, 11, 2), 1.0)
            series.append_day(date(2026, 11, 2), 3.0)
            rows = series.load_rows()
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["usage"], 3.0)


class MethodTests(unittest.TestCase):
    def test_baselines_have_horizon_shape(self):
        ctx = np.abs(np.random.default_rng(1).normal(1, 0.2, 60))
        for name, pred in methods.baselines(ctx, 17).items():
            self.assertEqual(len(pred), 17, name)
            self.assertTrue((pred >= 0).all(), name)

    def test_weekday_baseline_uses_matching_weekday(self):
        ctx = np.array([10.0] * 56)
        pred = methods.baselines(ctx, 7)["seasonal_wd"]
        self.assertTrue(np.allclose(pred, 10.0))

    def test_lognormal_mean_exceeds_median(self):
        self.assertGreater(methods.lognormal_mean(1.0, 3.0), 1.0)
        self.assertAlmostEqual(methods.lognormal_mean(2.0, 2.0), 2.0, places=6)
        self.assertEqual(methods.lognormal_mean(0.0, 5.0), 0.0)


class SeasonalRecentTests(unittest.TestCase):
    """Weekday-seasonal pace over 14 days: the shipped fallback (gate-verified)."""

    def test_weekend_dip_is_reproduced(self):
        # Two weeks starting Monday: weekdays 10, Sat/Sun 1.
        ctx = np.array([10.0, 10.0, 10.0, 10.0, 10.0, 1.0, 1.0] * 4)
        pred = methods.seasonal_recent(ctx, 7, first_weekday=0)   # Mon..Sun
        self.assertEqual(len(pred), 7)
        self.assertGreater(pred[4], pred[5])                     # Fri > Sat
        self.assertGreater(pred[0], pred[6])                     # Mon > Sun

    def test_flat_series_stays_flat(self):
        pred = methods.seasonal_recent(np.full(28, 4.0), 14, first_weekday=3)
        self.assertTrue(np.allclose(pred, 4.0))

    def test_single_spike_day_is_shrunk(self):
        # One huge Saturday must not triple the Saturday factor (lam = 0.5).
        ctx = np.full(14, 2.0)
        ctx[5] = 40.0                                            # a Saturday spike
        pred = methods.seasonal_recent(ctx, 7, first_weekday=0)   # Mon..Sun
        level = float(np.mean(ctx))
        self.assertLess(pred[5], level * 3)
        self.assertGreater(pred[5], level)

    def test_survives_short_history_and_zero_level(self):
        pred = methods.seasonal_recent(np.array([1.0]), 5, first_weekday=2)
        self.assertEqual(len(pred), 5)
        self.assertTrue((pred >= 0).all())
        self.assertTrue(np.allclose(methods.seasonal_recent(np.zeros(14), 5, 0), 0.0))

    def test_beats_flat_pace_after_a_level_break(self):
        # 60 stable weeks at 10, then the level drops to 2 for the last 14 days.
        ctx = np.concatenate([np.full(46, 10.0), np.full(14, 2.0)])
        h = 14
        flat = float(np.mean(ctx[-28:]) * h)
        seas = float(methods.seasonal_recent(ctx, h, first_weekday=0).sum())
        actual = 2.0 * h
        self.assertLess(abs(seas - actual), abs(flat - actual))


class BuildTests(unittest.TestCase):
    def _series(self, days=60, value=3.0):
        from datetime import timedelta
        first = date(2026, 9, 1)
        dates = [first + timedelta(days=i) for i in range(days)]
        return dates, [value] * days

    def test_no_model_uses_seasonal_and_reports_pace_side_by_side(self):
        import forecast
        dates, values = self._series()
        as_of = dates[-1]
        out = forecast.build(as_of, dates, values, None, None)
        self.assertEqual(out["method"], "seasonal-14d")
        self.assertEqual(out["projected_total"], out["seasonal_total"])
        self.assertIn("pace_baseline_total", out)
        self.assertIsNone(out["low"])
        self.assertEqual(out["context_points"], 14)

    def test_provider_month_to_date_wins_when_higher(self):
        import forecast
        dates, values = self._series()
        out = forecast.build(dates[-1], dates, values, None, None, provider_mtd=999.0)
        self.assertEqual(out["spent_mtd"], 999.0)
        self.assertEqual(out["spent_source"], "provider-usage_monthly")

    def test_horizon_zero_is_month_complete_not_a_forecast(self):
        import forecast
        dates, values = self._series()
        out = forecast.build(date(2026, 10, 31), dates, values, None, None)
        self.assertEqual(out["horizon_days"], 0)
        self.assertEqual(out["method"], "month-complete")
        self.assertEqual(out["projected_total"], out["spent_mtd"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
