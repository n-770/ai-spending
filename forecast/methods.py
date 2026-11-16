"""Forecast methods: simple pace baselines and TimesFM (3.0 via MLX, 2.5 fallback).

Rule 0: a budget question is answered by the sum at the horizon, so the point
output used for the total is an estimate of the MEAN daily spend, never the
median of a right-skewed daily series.
"""

from __future__ import annotations

import math
import os

import numpy as np

MIN_CONTEXT = 32
CONTEXT_WINDOW = 56
SEASONAL_WINDOW = 14
SEASONAL_SHRINK = 0.5     # halve weekday factors: 14d = only 2 samples per weekday


def baselines(ctx: np.ndarray, h: int, first_weekday: int | None = None) -> dict[str, np.ndarray]:
    """Naive and weekday-seasonal pace baselines.

    `first_weekday` is the weekday (Mon=0) of ctx[0]; pass it so the weekday
    profile lines up with the real calendar. Without it the index is assumed to
    start on Monday, which misaligns the profile whenever it does not.
    """
    ctx = np.asarray(ctx, dtype=float)
    n = len(ctx)
    last7 = float(np.mean(ctx[-7:]))
    last28 = float(np.mean(ctx[-28:]))
    base_wd = 0 if first_weekday is None else int(first_weekday) % 7

    def wd_of(i: int) -> int:
        return (base_wd + i) % 7

    wd_tot: dict[int, float] = {}
    wd_cnt: dict[int, int] = {}
    for i in range(max(0, n - 28), n):
        wd = wd_of(i)
        wd_tot[wd] = wd_tot.get(wd, 0.0) + float(ctx[i])
        wd_cnt[wd] = wd_cnt.get(wd, 0) + 1
    seasonal = np.array([
        wd_tot.get(wd_of(n + s), last7) / max(1, wd_cnt.get(wd_of(n + s), 1))
        for s in range(h)
    ])
    return {
        "naive_7d": np.full(h, last7),
        "naive_28d": np.full(h, last28),
        "seasonal_wd": seasonal,
        "seasonal_14d": seasonal_recent(ctx, h, wd_of(n), base_wd=base_wd),
    }


def seasonal_recent(ctx: np.ndarray, h: int, first_weekday: int,
                    window: int = SEASONAL_WINDOW, lam: float = SEASONAL_SHRINK,
                    base_wd: int | None = None) -> np.ndarray:
    """Weekday profile over the last `window` days, shrunk toward the flat level.

    `first_weekday` is the weekday of the first forecast day. Weekday factors are
    shrunk by `lam` because a 14-day window gives only two samples per weekday, so
    a single spike day would otherwise inflate that weekday for the whole horizon.
    Measured on 101 real days: this beats a flat 28-day pace by ~27% on month-end totals.
    """
    ctx = np.asarray(ctx, dtype=float)
    n = len(ctx)
    if n == 0:
        return np.zeros(h)
    window = max(1, min(window, n))
    level = float(np.mean(ctx[-window:]))
    if level <= 0:
        return np.zeros(h)
    ctx_first = ((int(first_weekday) - n) % 7) if base_wd is None else int(base_wd) % 7
    tot: dict[int, float] = {}
    cnt: dict[int, int] = {}
    for i in range(n - window, n):
        wd = (ctx_first + i) % 7
        tot[wd] = tot.get(wd, 0.0) + float(ctx[i])
        cnt[wd] = cnt.get(wd, 0) + 1
    out = []
    for s in range(h):
        wd = (int(first_weekday) + s) % 7
        if cnt.get(wd):
            factor = (tot[wd] / cnt[wd]) / level
            out.append(max(0.0, level * (1.0 + lam * (factor - 1.0))))
        else:
            out.append(level)
    return np.asarray(out, dtype=float)


def lognormal_mean(median: float, q90: float) -> float:
    """E[X] for a lognormal fitted to (median, q90). Falls back to the median."""
    try:
        if median <= 0 or q90 <= median:
            return max(median, 0.0)
        sigma = math.log(q90 / median) / 1.2815515655446004
        return median * math.exp(0.5 * sigma * sigma)
    except (ValueError, ZeroDivisionError):
        return max(median, 0.0)


def _model_3() :
    from timesfm3.mlx import TimesFM3Forecaster
    return "timesfm3", TimesFM3Forecaster.from_pretrained("google/timesfm-3.0-pytorch")


def _model_25():
    import timesfm
    from timesfm.timesfm_2p5.timesfm_2p5_torch import TimesFM_2p5_200M_torch

    model = TimesFM_2p5_200M_torch.from_pretrained("google/timesfm-2.5-200m-pytorch")
    model.compile(timesfm.ForecastConfig(
        max_context=512, max_horizon=32, normalize_inputs=True,
        use_continuous_quantile_head=True, force_flip_invariance=True,
        infer_is_positive=True, fix_quantile_crossing=True,
        per_core_batch_size=1))
    return "timesfm2.5", model


def load_model(prefer: str = "auto"):
    """Load once per process. Returns (name, model) or (None, None)."""
    order = ["timesfm3", "timesfm2.5"] if prefer == "auto" else [prefer]
    errors = []
    for kind in order:
        try:
            return (_model_3() if kind == "timesfm3" else _model_25())
        except Exception as exc:                       # noqa: BLE001 - report, then fall back
            errors.append(f"{kind}: {type(exc).__name__}: {exc}")
    if errors:
        os.environ.setdefault("AI_SPENDING_MODEL_ERRORS", " | ".join(errors))
    return None, None


def timesfm_components(name: str, model, ctx: np.ndarray, h: int) -> dict:
    """Mean/low/high over the horizon, per-head semantics of each model version."""
    ctx = np.asarray(ctx, dtype=np.float32)[-CONTEXT_WINDOW:]
    if name == "timesfm3":
        out = model.predict(ctx, horizon=h, return_quantiles=True)
        median = np.clip(np.asarray(out.forecast, dtype=float), 0, None)
        q = np.clip(np.asarray(out.quantiles, dtype=float), 0, None)   # (h, 9) = q10..q90
        low, high = q[:, 0], q[:, -1]
        mean = np.array([lognormal_mean(m, hi) for m, hi in zip(median, high)])
    else:
        point, quant = model.forecast(horizon=h, inputs=[ctx])
        q = np.asarray(quant[0], dtype=float)          # (h, 10): 0 = mean, 5 = median
        median = np.clip(np.asarray(point[0], dtype=float), 0, None)
        low, high = np.clip(q[:, 1], 0, None), np.clip(q[:, 9], 0, None)
        mean = np.clip(q[:, 0], 0, None)
    return {"mean": mean, "median": median, "low": low, "high": high}
