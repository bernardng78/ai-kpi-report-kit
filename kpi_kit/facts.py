"""Period facts: the brand's own numbers by week, month and quarter.

Every input column is additive (a sum or a count), so a KPI over any span is a
ratio of sums. The derived columns (net revenue, total spend, margins) are
computed here for the Python side; the workbook recomputes them with formulas.
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from .clean import CleanData
from .config import COHORT_OFFSET, Config
from .kpis import BASE_COLUMNS

INPUT_COLUMNS = [c for c, _, _, formula in BASE_COLUMNS if formula is None]
SUMMED_COLUMNS = [c for c in INPUT_COLUMNS if not c.startswith("cohort_")]  # cohorts are added per grain
GRAINS = ["week", "month", "quarter"]


@dataclass
class PeriodData:
    grain: str
    table: pd.DataFrame        # one row per complete period, indexed by key ("2026-W43", "2026-09", "2026-Q3")
    ads: pd.DataFrame          # spend, value and impressions by period, platform and campaign kind
    devices: pd.DataFrame      # GA4 sessions and transactions by period and device
    channels: pd.DataFrame     # GA4 sessions by period and channel group
    skus: pd.DataFrame         # net sales and refunds by period and SKU
    winback: pd.Series         # customers whose last order was 90-180 days before the period ended
    sku_names: dict[str, str]


def daily(clean: CleanData, cfg: Config) -> pd.DataFrame:
    o = clean.orders
    d = pd.DataFrame(index=pd.date_range(cfg.history_start, cfg.as_of, freq="D"))
    by_day = o.groupby("date")
    d["orders"] = by_day.size()
    d["gross_rev"] = by_day["gross_rev"].sum()
    d["discounts"] = by_day["discount_ex"].sum()
    d["units"] = by_day["units"].sum()
    d["fulfilment"] = by_day["fulfilment"].sum()
    d["fees"] = by_day["fees"].sum()
    d["new_customers"] = by_day["is_new"].sum()
    d["returning_gross"] = o[~o["is_new"]].groupby("date")["gross_rev"].sum()
    lines = clean.lines
    d["cogs_sold"] = (lines["qty"] * lines["sku"].map(clean.costs)).groupby(lines["date"]).sum()
    r = clean.refunds
    d["refunds"] = r.groupby("date")["amount_ex"].sum()
    back = r[r["restocked"]]
    d["cogs_returned"] = (back["qty"] * back["sku"].map(clean.costs)).groupby(back["date"]).sum()
    for platform in ["meta", "google", "tiktok"]:
        a = clean.ads[clean.ads["platform"] == platform].groupby("date")
        d[f"spend_{platform}"] = a["spend"].sum()
        d[f"value_{platform}"] = a["value"].sum()
    d["sessions"] = clean.ga4.groupby("date")["sessions"].sum()
    d = d.fillna(0.0)
    d["cogs"] = d["cogs_sold"] - d["cogs_returned"]
    return d


def period_of(dates: pd.Series | pd.DatetimeIndex, grain: str) -> pd.DataFrame:
    """Key, first day and last day of the period each date falls in."""
    dates = pd.DatetimeIndex(dates)
    if grain == "week":
        iso = dates.isocalendar()
        key = iso["year"].astype(str) + "-W" + iso["week"].astype(str).str.zfill(2)
        start = dates - pd.to_timedelta(dates.dayofweek, unit="D")
        end = start + pd.Timedelta(days=6)
    elif grain == "month":
        key = pd.Series(dates.strftime("%Y-%m"), index=dates)
        start = dates.to_period("M").start_time
        end = dates.to_period("M").end_time.normalize()
    else:
        p = dates.to_period("Q")
        key = pd.Series(p.year.astype(str) + "-Q" + p.quarter.astype(str), index=dates)
        start = p.start_time
        end = p.end_time.normalize()
    return pd.DataFrame({"key": key.to_numpy(), "start": start, "end": end}, index=dates)


def aggregate(day: pd.DataFrame, grain: str, cfg: Config) -> pd.DataFrame:
    p = period_of(day.index, grain)
    sums = day[SUMMED_COLUMNS].groupby(p["key"].to_numpy()).sum()
    bounds = p.groupby("key").agg(start=("start", "first"), end=("end", "first"))
    table = bounds.join(sums)
    complete = (table["start"] >= pd.Timestamp(cfg.history_start)) & (table["end"] <= pd.Timestamp(cfg.as_of))
    table = table[complete].sort_values("start")
    money = [c for c, _, fmt, formula in BASE_COLUMNS if formula is None and fmt == "money" and c in table]
    table[money] = table[money].round(2)  # cents, exactly as the workbook stores them
    table.index.name = "key"
    return table


def add_cohorts(table: pd.DataFrame, clean: CleanData, grain: str, cfg: Config) -> pd.DataFrame:
    """Cohort columns for the 90-day repeat rate, shifted so each row's cohort has had ~90 days."""
    o = clean.orders
    first = o[o["is_new"]].set_index("email")["date"]
    second = o[~o["is_new"]].drop_duplicates("email").set_index("email")["date"]
    back_in_90 = (second.reindex(first.index) - first).dt.days <= 90
    first_key = period_of(first, grain)["key"].to_numpy()
    by_period = pd.DataFrame({"new": 1, "repeat": back_in_90.to_numpy().astype(int)}).groupby(first_key).sum()
    by_period = by_period.reindex(table.index)
    by_period[table["start"] < pd.Timestamp(cfg.customer_metrics_from)] = float("nan")
    k = COHORT_OFFSET[grain]
    table = table.copy()
    table["cohort_new"] = by_period["new"].shift(k)
    table["cohort_repeat90"] = by_period["repeat"].shift(k)
    return table


def add_derived(table: pd.DataFrame) -> pd.DataFrame:
    table = table.copy()
    table["net_rev"] = table["gross_rev"] - table["refunds"]
    table["spend_total"] = table["spend_meta"] + table["spend_google"] + table["spend_tiktok"]
    table["gross_margin"] = table["net_rev"] - table["cogs"]
    table["cm"] = table["net_rev"] - table["cogs"] - table["fulfilment"] - table["fees"] - table["spend_total"]
    return table


def _winback(clean: CleanData, table: pd.DataFrame) -> pd.Series:
    o = clean.orders[["email", "date"]]
    counts = {}
    for key, end in table["end"].items():
        last = o[o["date"] <= end].groupby("email")["date"].max()
        age = (end - last).dt.days
        counts[key] = int(((age > 90) & (age <= 180)).sum())
    return pd.Series(counts)


def build(clean: CleanData, cfg: Config) -> dict[str, PeriodData]:
    day = daily(clean, cfg)
    out = {}
    for grain in GRAINS:
        table = add_derived(add_cohorts(aggregate(day, grain, cfg), clean, grain, cfg))
        early = table["start"] < pd.Timestamp(cfg.customer_metrics_from)
        table.loc[early, ["new_customers", "returning_gross"]] = float("nan")
        keep = table.index

        ads = clean.ads.copy()
        ads["key"] = period_of(ads["date"], grain)["key"].to_numpy()
        ads = ads[ads["key"].isin(keep)].groupby(["key", "platform", "kind"])[["spend", "value", "impressions"]].sum()

        ga = clean.ga4.copy()
        ga["key"] = period_of(ga["date"], grain)["key"].to_numpy()
        ga = ga[ga["key"].isin(keep)]
        devices = ga.groupby(["key", "device"])[["sessions", "transactions"]].sum()
        channels = ga.groupby(["key", "channel"])[["sessions"]].sum()

        lines = clean.lines.assign(key=period_of(clean.lines["date"], grain)["key"].to_numpy())
        refunds = clean.refunds.assign(key=period_of(clean.refunds["date"], grain)["key"].to_numpy())
        skus = pd.concat([lines.groupby(["key", "sku"])["net_ex"].sum().rename("net_sales"),
                          refunds.groupby(["key", "sku"])["amount_ex"].sum().rename("refunds")], axis=1).fillna(0)
        skus = skus[skus.index.get_level_values("key").isin(keep)]

        out[grain] = PeriodData(grain, table, ads, devices, channels, skus, _winback(clean, table), clean.sku_names)
    return out
