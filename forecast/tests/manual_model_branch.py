"""Exercise the model branch of forecast.build() with a synthetic 70-day series."""
import sys
from datetime import date, timedelta

import numpy as np

sys.path.insert(0, ".")
import forecast
import methods

rng = np.random.default_rng(11)
days = 70
end = date(2026, 11, 15)
dates = [end - timedelta(days=days - 1 - i) for i in range(days)]
weekday_f = np.array([1.0, 1.3, 1.3, 1.2, 1.2, 0.9, 0.5])
values = [float(abs(rng.lognormal(1.2, 0.35)) * weekday_f[d.weekday()]) for d in dates]

name, model = methods.load_model()
print("model:", name, "| errors:", methods.os.environ.get("AI_SPENDING_MODEL_ERRORS"))
out = forecast.build(date(2026, 11, 16), dates, values, name, model,
                     provider_mtd=sum(values[-15:]))
for k in ("spent_mtd", "projected_total", "low", "high", "method", "horizon_days",
          "context_points", "spent_source"):
    print(f"{k}: {out[k]}")
assert out["method"].startswith("timesfm"), out
assert out["low"] <= out["projected_total"] <= out["high"], out
assert out["horizon_days"] == 14, out
print("model branch OK")
