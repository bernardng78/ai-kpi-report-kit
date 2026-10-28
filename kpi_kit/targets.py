"""Targets, performance and status for every KPI and period.

This is the Python twin of the workbook's formulas, used for the HTML report
and the actions. tests/test_workbook.py checks that both give the same numbers.

For period i, with lag L (periods in a year), trailing window T and anchor
half-width h:

    anchor   = periods i-L-h .. i-L+h   (same period last year)
    growth   = sum of the last T periods / sum of the same T periods a year earlier
    target   = average(anchor) x clamp(growth)

Ratio KPIs use ratios of sums in both places. A target exists only once every
window has data, so no target is built on a half-empty year.

    perf     = actual / target - 1       (sign flipped when lower is better)
    band     = interquartile range of perf over the previous B periods, kept within [2%, 25%]
    status   = On track if perf >= -band/2, Watch if perf >= -band, else Off track
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .config import BAND_CAP, BAND_FLOOR, DEFAULT_BAND, GROWTH_MAX, GROWTH_MIN, WINDOWS
from .kpis import KPIS, Kpi


def _ratio(num: float, den: float) -> float:
    return num / den if den else np.nan


def first_target_index(table: pd.DataFrame, kpi: Kpi, grain: str) -> int:
    w = WINDOWS[grain]
    cols = [kpi.num] + ([kpi.den] if kpi.den else [])
    first_data = max(int(np.argmax(table[c].notna().to_numpy())) for c in cols)
    return first_data + w["lag"] + w["trailing"]


def kpi_frame(table: pd.DataFrame, kpi: Kpi, grain: str) -> pd.DataFrame:
    w = WINDOWS[grain]
    lag, h, t, b = w["lag"], w["anchor"], w["trailing"], w["band"]
    num = table[kpi.num].to_numpy(dtype=float)
    den = table[kpi.den].to_numpy(dtype=float) if kpi.den else None
    n = len(table)
    actual = num.copy() if den is None else np.array([_ratio(a, d) for a, d in zip(num, den)])
    target = np.full(n, np.nan)
    start = first_target_index(table, kpi, grain)
    for i in range(start, n):
        anchor = slice(i - lag - h, i - lag + h + 1)
        trail = slice(i - t, i)
        trail_ly = slice(i - lag - t, i - lag)
        if den is None:
            base = num[anchor].mean()
            growth = _ratio(num[trail].sum(), num[trail_ly].sum())
        else:
            base = _ratio(num[anchor].sum(), den[anchor].sum())
            growth = _ratio(_ratio(num[trail].sum(), den[trail].sum()),
                            _ratio(num[trail_ly].sum(), den[trail_ly].sum()))
        if np.isfinite(base) and np.isfinite(growth):
            target[i] = base * min(GROWTH_MAX, max(GROWTH_MIN, growth))

    perf = np.full(n, np.nan)
    ok = np.isfinite(actual) & np.isfinite(target) & (target > 0)
    if kpi.direction == "down":
        perf[ok] = 1 - actual[ok] / target[ok]
    else:
        perf[ok] = actual[ok] / target[ok] - 1

    band = np.full(n, np.nan)
    for i in range(b, n):
        window = perf[i - b:i]
        if np.isfinite(window).all():
            q1, q3 = np.quantile(window, [0.25, 0.75])  # linear interpolation, like QUARTILE()
            band[i] = max(BAND_FLOOR, min(BAND_CAP, q3 - q1))

    return pd.DataFrame({"actual": actual, "target": target, "perf": perf, "band": band}, index=table.index)


def status(perf: float, band: float, direction: str) -> str:
    if not np.isfinite(perf):
        return "n/a"
    band = band if np.isfinite(band) else DEFAULT_BAND
    if direction == "neutral":
        return "Above plan" if perf > band else "Below plan" if perf < -band else "On plan"
    if perf >= -band / 2:
        return "On track"
    return "Watch" if perf >= -band else "Off track"


def compute(table: pd.DataFrame, grain: str) -> dict[str, pd.DataFrame]:
    """KPI id -> frame of actual, target, perf, band and status, one row per period."""
    out = {}
    for kpi in KPIS:
        f = kpi_frame(table, kpi, grain)
        f["status"] = [status(p, b, kpi.direction) for p, b in zip(f["perf"], f["band"])]
        out[kpi.id] = f
    return out


def targeted_periods(results: dict[str, pd.DataFrame]) -> list[str]:
    """Periods where the headline KPI has a target: the ones a report can show."""
    f = results["net_rev"]
    return list(f.index[f["target"].notna()])
