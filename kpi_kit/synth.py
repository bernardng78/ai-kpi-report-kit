"""Synthetic, deliberately messy exports for a fictional outdoor-apparel store.

A fixed seed makes every run identical. The mess mirrors real exports:
- Shopify writes one row per line item, with order fields only on the first row.
- Two order exports overlap by a month, and the older one misses later refunds.
- Test orders sit among real ones.
- Google Ads puts a title and date range above the header and formats numbers as text.
- GA4 starts its CSV with comment lines and writes dates as YYYYMMDD.
- TikTok writes day-first dates and appends a totals row; Meta prepends one.
- The cost sheet was saved from a Danish Excel: semicolons, comma decimals and one SKU missing.

The demand model also plants a story in the last weeks so the report has
something to say: Meta prospecting gets pricier from 28 September, a theme
update breaks part of mobile checkout on 5 October, a jacket launched on
1 September is returned far more than the rest of the range, and a bundle
launched on 1 October lifts order value.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from .config import Config

SIM_START = date(2022, 10, 31)       # a year of customers before the exports start
EXPORT_1_LAST_DAY = date(2025, 12, 31)
EXPORT_2_FIRST_DAY = date(2025, 12, 1)
EXPORT_1_PULLED = date(2026, 1, 6)   # refunds after this day are missing from export 1
META_PRICIER_FROM = date(2026, 9, 28)
CHECKOUT_BUG_FROM = date(2026, 10, 5)
TIKTOK_LAUNCH = date(2025, 3, 3)


@dataclass(frozen=True)
class Product:
    sku: str
    name: str
    price: float  # incl. VAT
    cost: float   # ex VAT
    season: str
    popularity: float
    refund_prob: float
    launch: date | None = None


PRODUCTS = [
    Product("JKT-INSUL", "Insulated Parka", 269.0, 84.0, "winter", 0.8, 0.11),
    Product("JKT-RAIN", "Rain Jacket", 139.0, 39.0, "shoulder", 1.0, 0.10),
    Product("JKT-ALPINE", "Alpine Shell Jacket", 249.0, 74.0, "shoulder", 0.25, 0.45, date(2026, 9, 1)),
    Product("FLC-MID", "Midlayer Fleece", 89.0, 22.0, "winter", 1.2, 0.08),
    Product("BSL-MERINO", "Merino Base Layer", 69.0, 19.0, "winter", 1.2, 0.07),
    Product("PNT-HIKE", "Hiking Pants", 99.0, 27.0, "summer", 0.9, 0.09),
    Product("SCK-WOOL", "Wool Socks 2-pack", 25.0, 5.5, "all", 1.8, 0.03),
    Product("HAT-BEANIE", "Knit Beanie", 29.0, 6.0, "winter", 1.3, 0.03),
    Product("GLV-TOUCH", "Touchscreen Gloves", 35.0, 8.5, "winter", 0.8, 0.05),
    Product("BAG-DAY", "Daypack 22L", 119.0, 34.0, "summer", 0.6, 0.05),
    Product("BTL-STEEL", "Steel Bottle", 29.0, 7.0, "summer", 0.8, 0.02),
    Product("KIT-LAYER", "Layering Kit", 179.0, 47.0, "winter", 0.45, 0.06, date(2026, 10, 1)),
]
MISSING_COST_SKU = "KIT-LAYER"  # new SKU the cost sheet hasn't caught up with

SEASON = {  # relative demand by month, Jan..Dec
    "winter": [1.3, 1.0, 0.7, 0.5, 0.3, 0.2, 0.2, 0.4, 0.8, 1.3, 1.6, 1.7],
    "shoulder": [0.6, 0.7, 1.1, 1.3, 1.0, 0.7, 0.6, 0.9, 1.3, 1.3, 1.0, 0.8],
    "summer": [0.4, 0.5, 0.8, 1.2, 1.5, 1.7, 1.7, 1.3, 0.8, 0.5, 0.6, 0.7],
    "all": [1.0] * 12,
}
STORE_SEASON = [0.85, 0.70, 0.80, 0.90, 0.85, 0.75, 0.70, 0.85, 1.00, 1.10, 1.15, 1.30]
CPA_SEASON = [0.88, 0.88, 0.92, 0.92, 0.92, 0.92, 0.92, 0.94, 0.97, 1.00, 1.04, 1.06]
DOW = [1.05, 1.00, 0.98, 0.97, 0.94, 0.92, 1.14]  # Mon..Sun
HOUR_WEIGHTS = [0.6, 0.4, 0, 0.2, 0.2, 0.3, 0.6, 1.0, 1.4, 1.6, 1.7, 1.8,
                2.0, 1.9, 1.8, 1.8, 1.9, 2.1, 2.4, 2.8, 3.0, 2.8, 2.0, 1.1]  # no 02:00, so no DST gaps

# Platform-reported purchases per real order, by who the platform claims:
# (campaign's own new customers, returning customers, organic new customers).
Campaign = tuple[str, str, str, float, float, float, float, tuple[float, float, float]]
CAMPAIGNS: list[Campaign] = [
    # platform, name, type, budget/day at as_of, CPA at as_of, CPM, CTR, attribution
    ("meta", "PROS | Broad | Advantage+", "prospecting", 770, 68, 9.5, 0.011, (1.3, 0.03, 0.0)),
    ("meta", "RT | Site visitors 30d", "retargeting", 220, 48, 14.0, 0.016, (1.3, 0.12, 0.0)),
    ("google", "Search | Brand", "brand", 130, 24, 30.0, 0.090, (1.1, 0.06, 0.15)),
    ("google", "Search | Generic", "generic", 200, 77, 22.0, 0.035, (1.2, 0.0, 0.0)),
    ("google", "PMax | All products", "pmax", 350, 55, 7.0, 0.012, (1.3, 0.05, 0.06)),
    ("google", "Shopping | Jackets", "shopping", 140, 58, 6.0, 0.010, (1.25, 0.0, 0.0)),
    ("tiktok", "TT | Spark Ads | Creators", "prospecting", 270, 88, 6.5, 0.009, (1.2, 0.0, 0.0)),
]
GOOGLE_TYPE_LABEL = {"brand": "Search", "generic": "Search", "pmax": "Performance Max", "shopping": "Shopping"}

CHANNELS = ["Organic Search", "Paid Social", "Paid Search", "Direct", "Email", "Organic Social", "Referral", "Unassigned"]
CHANNEL_SHARE = np.array([0.20, 0.24, 0.16, 0.19, 0.08, 0.05, 0.05, 0.03])
CHANNEL_CR = np.array([1.0, 0.7, 1.4, 1.3, 2.4, 0.5, 0.9, 0.8])
DEVICES = ["mobile", "desktop", "tablet"]
DEVICE_CR = np.array([1.0, 2.0, 1.3])
MOBILE_CR_AFTER_BUG = 0.78


def generate(cfg: Config, out_dir: Path) -> dict[str, int]:
    """Write every raw export into out_dir and return row counts."""
    rng = np.random.default_rng(cfg.seed)
    out_dir.mkdir(parents=True, exist_ok=True)
    cal = _calendar(cfg)
    ads = _ad_days(cal, rng)
    organic = _organic_new(cal, rng)
    orders, ret_potential = _simulate_customers(cal, ads, organic, rng)
    orders, lines, refunds = _baskets(cfg, cal, orders, rng)
    orders, lines = _add_test_orders(cfg, cal, orders, lines, rng)
    orders = _name_orders(orders)

    counts = {}
    counts.update(_write_shopify(cfg, orders, lines, refunds, out_dir))
    counts.update(_write_ads(cfg, cal, ads, orders, organic, rng, out_dir))
    counts.update(_write_ga4(cfg, cal, ads, organic, orders, ret_potential, rng, out_dir))
    _write_costs(out_dir)
    return counts


# --- calendar -------------------------------------------------------------------

def _black_friday(year: int) -> date:
    nov1 = date(year, 11, 1)
    first_thursday = nov1 + timedelta(days=(3 - nov1.weekday()) % 7)
    return first_thursday + timedelta(days=22)


def _spring_sale_start(year: int) -> date:
    apr1 = date(year, 4, 1)
    return apr1 + timedelta(days=(3 - apr1.weekday()) % 7 + 7)


def _event(d: date) -> tuple[float, float, float, float, str, float]:
    """(demand, spend, CPA, conversion-rate multipliers, discount code, discount rate)."""
    delta = (d - _black_friday(d.year)).days
    if -7 <= delta <= -1:
        return 1.25, 1.4, 1.05, 1.05, "", 0.0
    if delta == 0:
        return 2.6, 2.4, 0.85, 1.6, "BF25", 0.25
    if delta in (1, 2):
        return (2.0, 1.9)[delta - 1], (2.0, 1.9)[delta - 1], 0.85, 1.5, "BF25", 0.25
    if delta == 3:
        return 2.1, 2.0, 0.85, 1.5, "BF25", 0.25
    if delta == 4:
        return 1.3, 1.2, 1.0, 1.1, "", 0.0
    if d.month == 12:
        if d.day <= 18:
            return 1.15, 1.2, 1.1, 1.05, "", 0.0
        if d.day <= 23:
            return 0.9, 1.0, 1.0, 1.0, "", 0.0
        if d.day <= 26:
            return 0.45, 0.6, 1.0, 0.9, "", 0.0
        return 0.9, 0.8, 1.0, 1.0, "", 0.0
    if d.month == 1 and 2 <= d.day <= 10:
        return 1.35, 1.3, 0.95, 1.15, "JAN20", 0.20
    spring = _spring_sale_start(d.year)
    if 0 <= (d - spring).days <= 3:
        return 1.45, 1.4, 0.95, 1.2, "SPRING15", 0.15
    return 1.0, 1.0, 1.0, 1.0, "", 0.0


def _month_curve(dates: pd.DatetimeIndex, values: list[float]) -> np.ndarray:
    mids = np.array([15, 46, 74, 105, 135, 166, 196, 227, 258, 288, 319, 349])
    x = np.concatenate([mids - 365, mids, mids + 365])
    return np.interp(dates.dayofyear.to_numpy(), x, np.tile(values, 3))


def _calendar(cfg: Config) -> pd.DataFrame:
    dates = pd.date_range(SIM_START, cfg.as_of, freq="D")
    cal = pd.DataFrame({"date": dates.date})
    years_to_asof = (dates - pd.Timestamp(cfg.as_of)).days.to_numpy() / 365.25
    season = _month_curve(dates, STORE_SEASON)
    asof_season = _month_curve(pd.DatetimeIndex([pd.Timestamp(cfg.as_of)]), STORE_SEASON)[0]
    cal["trend"] = 1.25 ** years_to_asof          # the brand grows ~25% a year
    cal["cpi"] = 1.08 ** years_to_asof            # media costs rise ~8% a year
    cal["season"] = season / asof_season
    cal["dow"] = np.array(DOW)[dates.dayofweek]
    cal["month"] = dates.month
    events = [_event(d) for d in cal["date"]]
    for i, col in enumerate(["ev_demand", "ev_spend", "ev_cpa", "ev_cr", "ev_code", "ev_rate"]):
        cal[col] = [e[i] for e in events]
    years_since_start = (dates - pd.Timestamp(cfg.history_start)).days.to_numpy() / 365.25
    cal["mobile_share"] = np.clip(0.64 + 0.03 * years_since_start, 0.60, 0.72)
    bug = np.asarray(dates >= pd.Timestamp(CHECKOUT_BUG_FROM))
    cal["mobile_cr_mult"] = np.where(bug, MOBILE_CR_AFTER_BUG, 1.0)
    # share of would-be orders that survive the broken mobile checkout
    cal["p_keep"] = 1 - cal["mobile_share"] * (1 - cal["mobile_cr_mult"])
    cr_season = np.select([dates.month.isin([11, 12]), dates.month.isin([6, 7, 8])], [1.05, 0.95], 1.0)
    cal["cr_base"] = 0.0235 * cr_season * cal["ev_cr"] * 1.02 ** years_to_asof
    cal["ret_mult"] = cal["season"] ** 0.5 * cal["ev_demand"] ** 0.8 * cal["dow"]
    return cal


# --- demand ---------------------------------------------------------------------

def _story_cpa(platform: str, kind: str, d: np.ndarray) -> np.ndarray:
    out = np.ones(len(d))
    days_since = (d - np.datetime64(META_PRICIER_FROM)).astype("timedelta64[D]").astype(int)
    ramp = np.clip((days_since + 1) / 7, 0, 1)  # takes a week to bite
    if platform == "meta":
        out *= 1 + (0.40 if kind == "prospecting" else 0.15) * ramp
    if platform == "tiktok":
        since_launch = (d - np.datetime64(TIKTOK_LAUNCH)).astype("timedelta64[D]").astype(int)
        out *= 1.6 - 0.6 * np.clip(since_launch / 180, 0, 1)  # learning phase after launch
    return out


def _ad_days(cal: pd.DataFrame, rng: np.random.Generator) -> pd.DataFrame:
    """One row per day per campaign: spend, impressions, clicks and customers won."""
    d = cal["date"].to_numpy().astype("datetime64[D]")
    cpa_season = np.array(CPA_SEASON)[cal["month"].to_numpy() - 1]
    frames = []
    for ci, (platform, _name, kind, budget, cpa, cpm, ctr, _) in enumerate(CAMPAIGNS):
        active = np.ones(len(cal), bool) if platform != "tiktok" else d >= np.datetime64(TIKTOK_LAUNCH)
        spend = budget * cal["trend"] * cal["season"] * cal["ev_spend"] * rng.lognormal(0, 0.08, len(cal))
        spend = np.where(active, spend.round(2), 0.0)
        story = _story_cpa(platform, kind, d)
        day_cpa = (cpa * cal["cpi"] * cpa_season * cal["ev_cpa"] / cal["dow"] * story
                   * rng.lognormal(0, 0.07, len(cal)))
        potential = rng.poisson(np.where(active, spend / day_cpa, 0))
        won = rng.binomial(potential, cal["p_keep"])
        cpm_story = 1 + (0.25 * (story - 1) / 0.40 if platform == "meta" else 0)
        impressions = np.where(active, spend / (cpm * cal["cpi"] * cpa_season * cpm_story) * 1000, 0)
        impressions = rng.poisson(impressions)
        clicks = rng.binomial(impressions, ctr * rng.uniform(0.9, 1.1, len(cal)))
        frames.append(pd.DataFrame({
            "day": np.arange(len(cal)), "campaign": ci, "spend": spend, "potential_new": potential,
            "new_won": won, "impressions": impressions, "clicks": clicks,
        }))
    return pd.concat(frames, ignore_index=True)


def _organic_new(cal: pd.DataFrame, rng: np.random.Generator) -> pd.DataFrame:
    lam = 14 * cal["trend"] * cal["season"] * cal["ev_demand"] * cal["dow"] * rng.lognormal(0, 0.10, len(cal))
    potential = rng.poisson(lam)
    return pd.DataFrame({"potential": potential, "won": rng.binomial(potential, cal["p_keep"])})


def _simulate_customers(cal: pd.DataFrame, ads: pd.DataFrame, organic: pd.DataFrame,
                        rng: np.random.Generator) -> tuple[pd.DataFrame, np.ndarray]:
    """Walk day by day: returning customers come back on a recency-weighted hazard.

    Returns the orders and, per day, how many returning orders were attempted
    before the broken checkout lost some (sessions follow attempts, not orders).
    """
    n_days = len(cal)
    new_won = ads.groupby("day")["new_won"].sum().to_numpy() + organic["won"].to_numpy()
    cap = int(new_won.sum()) + 10
    last = np.zeros(cap, np.int32)
    count = np.zeros(cap, np.int16)
    n = 0
    days, customers, is_new = [], [], []
    ret_potential = np.zeros(n_days, int)
    ret_mult = cal["ret_mult"].to_numpy()
    p_keep = cal["p_keep"].to_numpy()
    for i in range(n_days):
        if n:
            age = i - last[:n]
            w = np.exp(-age / 120.0) * (1 - np.exp(-age / 10.0)) * (1 + 0.3 * np.minimum(count[:n] - 1, 5))
            total = w.sum()
            k = min(int(rng.poisson(0.0028 * total * ret_mult[i])), n)
            if k:
                back = rng.choice(n, size=k, replace=False, p=w / total)
                ret_potential[i] = k
                back = back[rng.random(k) < p_keep[i]]
                last[back] = i
                count[back] += 1
                days.append(np.full(len(back), i))
                customers.append(back)
                is_new.append(np.zeros(len(back), bool))
        m = int(new_won[i])
        ids = np.arange(n, n + m)
        last[ids] = i
        count[ids] = 1
        n += m
        days.append(np.full(m, i))
        customers.append(ids)
        is_new.append(np.ones(m, bool))
    orders = pd.DataFrame({"day": np.concatenate(days), "customer": np.concatenate(customers),
                           "is_new": np.concatenate(is_new)})
    return orders, ret_potential


# --- baskets, refunds -----------------------------------------------------------

def _baskets(cfg: Config, cal: pd.DataFrame, orders: pd.DataFrame, rng: np.random.Generator):
    n = len(orders)
    day = orders["day"].to_numpy()
    dates = pd.to_datetime(cal["date"]).to_numpy()
    order_date = dates[day]
    months = cal["month"].to_numpy()

    # line items: SKUs drawn by season, popularity and launch date
    n_lines = rng.choice([1, 2, 3, 4], size=n, p=[0.66, 0.24, 0.08, 0.02])
    line_order = np.repeat(np.arange(n), n_lines)
    line_day = day[line_order]
    sku_idx = np.empty(len(line_order), int)
    pop = np.array([p.popularity for p in PRODUCTS])
    launch = np.array([np.datetime64(p.launch) if p.launch else np.datetime64("1900-01-01") for p in PRODUCTS])
    season = np.array([SEASON[p.season] for p in PRODUCTS])  # products x 12
    order_of_lines = np.argsort(line_day, kind="stable")
    sorted_days = line_day[order_of_lines]
    bounds = np.flatnonzero(np.diff(sorted_days)) + 1
    for chunk in np.split(order_of_lines, bounds):
        di = line_day[chunk[0]]
        w = pop * season[:, months[di] - 1] * (launch <= dates[di])
        sku_idx[chunk] = rng.choice(len(PRODUCTS), size=len(chunk), p=w / w.sum())
    lines = pd.DataFrame({"order": line_order, "sku_idx": sku_idx})
    lines = lines.groupby(["order", "sku_idx"], as_index=False).size().rename(columns={"size": "qty"})
    socks = lines["sku_idx"] == [p.sku for p in PRODUCTS].index("SCK-WOOL")
    lines.loc[socks, "qty"] += rng.choice([0, 1, 2], size=int(socks.sum()), p=[0.70, 0.25, 0.05])
    price = np.array([p.price for p in PRODUCTS])
    lines["price"] = price[lines["sku_idx"]]
    lines["line_total"] = lines["qty"] * lines["price"]

    # order totals: discount codes, shipping, VAT
    orders = orders.copy()
    orders["date"] = order_date
    sub_before = lines.groupby("order")["line_total"].sum().reindex(range(n), fill_value=0).to_numpy()
    ev_code = cal["ev_code"].to_numpy()[day]
    ev_rate = cal["ev_rate"].to_numpy()[day]
    use_event = (ev_code != "") & (rng.random(n) < 0.8)
    welcome = ~use_event & orders["is_new"].to_numpy() & (rng.random(n) < 0.35)
    vip = ~use_event & ~welcome & ~orders["is_new"].to_numpy() & (rng.random(n) < 0.05)
    code = np.where(use_event, ev_code, np.where(welcome, "WELCOME10", np.where(vip, "VIP15", "")))
    rate = np.where(use_event, ev_rate, np.where(welcome, 0.10, np.where(vip, 0.15, 0.0)))
    discount = (sub_before * rate).round(2)
    subtotal = sub_before - discount
    express = rng.random(n) < 0.08
    shipping = np.where(express, 9.95, np.where(subtotal >= 100, 0.0, 5.95))
    total = (subtotal + shipping).round(2)
    orders["discount_code"] = code
    orders["discount_rate"] = rate
    orders["discount"] = discount
    orders["subtotal"] = subtotal.round(2)
    orders["shipping"] = shipping
    orders["shipping_method"] = np.where(express, "Express", "Standard")
    orders["total"] = total
    orders["taxes"] = (total * cfg.vat_rate / (1 + cfg.vat_rate)).round(2)
    status = np.where(rng.random(n) < 0.004, "pending", "paid")
    status = np.where(rng.random(n) < 0.007, "voided", status)
    orders["status"] = status
    hours = rng.choice(24, size=n, p=np.array(HOUR_WEIGHTS) / sum(HOUR_WEIGHTS))
    seconds = hours * 3600 + rng.integers(0, 3600, n)
    orders["created"] = pd.to_datetime(order_date) + pd.to_timedelta(seconds, unit="s")
    orders["accepts_marketing"] = np.where(rng.random(n) < 0.55, "yes", "no")

    # refunds: whole lines, a few days to a few weeks after the order
    refund_prob = np.array([p.refund_prob for p in PRODUCTS])[lines["sku_idx"]]
    order_month = pd.DatetimeIndex(order_date[lines["order"]]).month.to_numpy()
    refund_prob = refund_prob * np.where(np.isin(order_month, [12, 1]), 1.25, 1.0)
    refundable = status[lines["order"]] == "paid"
    refunded = refundable & (rng.random(len(lines)) < refund_prob)
    r = lines[refunded].copy()
    r["amount"] = (r["line_total"] * (1 - rate[r["order"]])).round(2)
    lag_days = 3 + rng.gamma(2.0, 5.0, len(r))
    r["refund_at"] = (orders["created"].to_numpy()[r["order"]] + pd.to_timedelta(lag_days, unit="D")).floor("D")
    r["refund_at"] += pd.to_timedelta(rng.integers(8 * 3600, 17 * 3600, len(r)), unit="s")
    r["restocked"] = np.where(rng.random(len(r)) < 0.85, "yes", "no")
    cutoff = pd.Timestamp(cfg.as_of) + pd.Timedelta(days=1)
    refunds = r[r["refund_at"] < cutoff].reset_index(drop=True)  # later refunds haven't happened yet
    return orders, lines, refunds


def _add_test_orders(cfg: Config, cal: pd.DataFrame, orders: pd.DataFrame, lines: pd.DataFrame,
                     rng: np.random.Generator):
    """A few QA orders a month, placed by staff through draft orders."""
    window = cal.index[cal["date"] >= cfg.history_start].to_numpy()
    n_test = int(len(window) / 30 * 3)
    test_days = np.sort(rng.choice(window, size=n_test, replace=False))
    start = len(orders)
    sku = rng.integers(0, len(PRODUCTS) - 1, n_test)  # never the bundle
    price = np.array([p.price for p in PRODUCTS])[sku]
    dates = pd.to_datetime(cal["date"]).to_numpy()[test_days]
    test = pd.DataFrame({
        "day": test_days, "customer": -1, "is_new": False, "date": dates,
        "discount_code": "", "discount_rate": 0.0, "discount": 0.0, "subtotal": price,
        "shipping": 0.0, "shipping_method": "Standard", "total": price,
        "taxes": (price * cfg.vat_rate / (1 + cfg.vat_rate)).round(2), "status": "paid",
        "created": pd.to_datetime(dates) + pd.to_timedelta(rng.integers(9 * 3600, 16 * 3600, n_test), unit="s"),
        "accepts_marketing": "no", "is_test": True,
    })
    orders = orders.assign(is_test=False)
    test.index = range(start, start + n_test)
    test_lines = pd.DataFrame({"order": test.index, "sku_idx": sku, "qty": 1, "price": price, "line_total": price})
    return pd.concat([orders, test]), pd.concat([lines, test_lines], ignore_index=True)


def _name_orders(orders: pd.DataFrame) -> pd.DataFrame:
    order = orders.sort_values("created", kind="stable").index
    names = pd.Series(np.arange(1001, 1001 + len(orders)), index=order)
    orders = orders.copy()
    orders["number"] = names.reindex(orders.index).to_numpy()
    orders["name"] = "#" + orders["number"].astype(str)
    orders["shopify_id"] = 5_600_000_000_000 + orders["number"] * 37
    return orders


# --- writers --------------------------------------------------------------------

def _stamp(ts: pd.Series, tz: str) -> pd.Series:
    local = pd.DatetimeIndex(ts).tz_localize(tz)  # generated times avoid the DST gap hour
    return pd.Series(local.strftime("%Y-%m-%d %H:%M:%S %z"), index=ts.index)


def _money(x) -> pd.Series:
    return pd.Series(x).map(lambda v: f"{v:.2f}")


def _write_shopify(cfg: Config, orders: pd.DataFrame, lines: pd.DataFrame, refunds: pd.DataFrame,
                   out_dir: Path) -> dict[str, int]:
    tz = cfg.timezone
    customer = orders["customer"].to_numpy()
    orders = orders.copy()
    orders["email"] = np.where(orders["is_test"], "qa+" + orders["number"].astype(str) + "@demostore.test",
                               "cust" + pd.Series(customer, index=orders.index).astype(str).str.zfill(6) + "@shopper.test")
    orders["created_str"] = _stamp(orders["created"], tz)
    orders["tags"] = np.where(orders["is_test"], "test", "")
    orders["source"] = np.where(orders["is_test"], "shopify_draft_order", "web")
    sku = np.array([p.sku for p in PRODUCTS])
    pname = np.array([p.name for p in PRODUCTS])
    lines = lines.merge(orders[["name", "email"]], left_on="order", right_index=True)
    lines = lines.sort_values(["order", "sku_idx"], kind="stable")
    lines["first"] = ~lines.duplicated("order")

    written = {}
    for idx, (first_day, last_day, pulled) in enumerate(
            [(cfg.history_start, EXPORT_1_LAST_DAY, EXPORT_1_PULLED),
             (EXPORT_2_FIRST_DAY, cfg.as_of, cfg.as_of + timedelta(days=1))], start=1):
        created_day = orders["created"].dt.date
        sel = orders[(created_day >= first_day) & (created_day <= last_day)].copy()
        seen = refunds[refunds["refund_at"] < pd.Timestamp(pulled)]
        refunded_amt = seen.groupby("order")["amount"].sum()
        refunded_lines = seen.groupby("order").size()
        line_count = lines.groupby("order").size()
        sel["refunded"] = refunded_amt.reindex(sel.index, fill_value=0.0).to_numpy()
        n_ref = refunded_lines.reindex(sel.index, fill_value=0).to_numpy()
        all_ref = n_ref == line_count.reindex(sel.index).to_numpy()
        fin = np.where(n_ref == 0, sel["status"], np.where(all_ref, "refunded", "partially_refunded"))
        sel["financial"] = np.where(sel["status"] == "paid", fin, sel["status"])
        recent = sel["created"] > pd.Timestamp(pulled) - pd.Timedelta(days=2)
        sel["fulfillment"] = np.where(sel["status"] == "voided", "",
                                      np.where((sel["status"] == "pending") | recent, "unfulfilled", "fulfilled"))
        sel["paid_at"] = np.where(sel["status"] == "paid", sel["created_str"], "")
        sel["cancelled_at"] = np.where(sel["status"] == "voided", sel["created_str"], "")

        ln = lines[lines["order"].isin(sel.index)].copy()
        o = sel.loc[ln["order"]].reset_index(drop=True)
        ln = ln.reset_index(drop=True)
        first = ln["first"].to_numpy()

        def order_field(values) -> np.ndarray:
            return np.where(first, values, "")

        rows = pd.DataFrame({
            "Name": ln["name"], "Email": ln["email"],
            "Financial Status": order_field(o["financial"]),
            "Paid at": order_field(o["paid_at"]),
            "Fulfillment Status": order_field(o["fulfillment"]),
            "Accepts Marketing": order_field(o["accepts_marketing"]),
            "Currency": order_field(np.full(len(o), "EUR")),
            "Subtotal": order_field(_money(o["subtotal"])),
            "Shipping": order_field(_money(o["shipping"])),
            "Taxes": order_field(_money(o["taxes"])),
            "Total": order_field(_money(o["total"])),
            "Discount Code": order_field(o["discount_code"]),
            "Discount Amount": order_field(_money(o["discount"])),
            "Shipping Method": order_field(o["shipping_method"]),
            "Created at": order_field(o["created_str"]),
            "Lineitem quantity": ln["qty"],
            "Lineitem name": pname[ln["sku_idx"]],
            "Lineitem price": _money(ln["price"]),
            "Lineitem sku": sku[ln["sku_idx"]],
            "Refunded Amount": order_field(_money(o["refunded"])),
            "Cancelled at": order_field(o["cancelled_at"]),
            "Source": order_field(o["source"]),
            "Tags": order_field(o["tags"]),
            "Id": order_field(o["shopify_id"].astype(str)),
        })
        rows.to_csv(out_dir / f"orders_export_{idx}.csv", index=False)
        written[f"orders_export_{idx}.csv"] = len(rows)

    in_window = refunds["refund_at"] >= pd.Timestamp(cfg.history_start)
    r = refunds[in_window].sort_values("refund_at")
    out = pd.DataFrame({
        "Order": orders.loc[r["order"], "name"].to_numpy(),
        "Refund date": _stamp(r["refund_at"].reset_index(drop=True), tz),
        "SKU": sku[r["sku_idx"]],
        "Quantity": r["qty"].to_numpy(),
        "Refund amount": _money(r["amount"].to_numpy()),
        "Restocked": r["restocked"].to_numpy(),
    })
    out.to_csv(out_dir / "refunds_export.csv", index=False)
    written["refunds_export.csv"] = len(out)
    return written


def _platform_rows(cfg: Config, cal: pd.DataFrame, ads: pd.DataFrame, orders: pd.DataFrame,
                   organic: pd.DataFrame, rng: np.random.Generator) -> pd.DataFrame:
    real = orders[~orders["is_test"] & (orders["status"] != "voided")]
    per_day = real.groupby("day").agg(aov=("total", "mean"), returning=("is_new", lambda s: int((~s).sum())))
    per_day = per_day.reindex(range(len(cal)))
    aov = per_day["aov"].fillna(per_day["aov"].mean()).to_numpy()
    returning = per_day["returning"].fillna(0).to_numpy()
    org = organic["won"].to_numpy()
    rows = ads.copy()
    a_new = np.array([c[7][0] for c in CAMPAIGNS])[rows["campaign"]]
    a_ret = np.array([c[7][1] for c in CAMPAIGNS])[rows["campaign"]]
    a_org = np.array([c[7][2] for c in CAMPAIGNS])[rows["campaign"]]
    expected = rows["new_won"] * a_new + returning[rows["day"]] * a_ret + org[rows["day"]] * a_org
    expected = np.where(rows["spend"] > 0, expected, 0)
    rows["purchases"] = rng.poisson(expected)
    rows["value"] = (rows["purchases"] * aov[rows["day"]] * rng.lognormal(0, 0.05, len(rows))).round(2)
    rows["date"] = cal["date"].to_numpy()[rows["day"]]
    return rows[rows["date"] >= cfg.history_start]


def _write_ads(cfg: Config, cal: pd.DataFrame, ads: pd.DataFrame, orders: pd.DataFrame,
               organic: pd.DataFrame, rng: np.random.Generator, out_dir: Path) -> dict[str, int]:
    rows = _platform_rows(cfg, cal, ads, orders, organic, rng)
    name = np.array([c[1] for c in CAMPAIGNS])
    platform = np.array([c[0] for c in CAMPAIGNS])[rows["campaign"]]
    kind = np.array([c[2] for c in CAMPAIGNS])[rows["campaign"]]
    written = {}

    m = rows[platform == "meta"]
    meta = pd.DataFrame({
        "Reporting starts": m["date"].astype(str), "Reporting ends": m["date"].astype(str),
        "Campaign name": name[m["campaign"]], "Ad set name": np.char.add(name[m["campaign"]], " | All"),
        "Amount spent (EUR)": _money(m["spend"]).to_numpy(), "Impressions": m["impressions"].to_numpy(),
        "Link clicks": m["clicks"].to_numpy(), "Purchases": m["purchases"].to_numpy(),
        "Purchases conversion value": _money(m["value"]).to_numpy(),
    })
    summary = pd.DataFrame([{
        "Reporting starts": str(cfg.history_start), "Reporting ends": str(cfg.as_of),
        "Campaign name": "", "Ad set name": "",
        "Amount spent (EUR)": f"{m['spend'].sum():.2f}", "Impressions": int(m["impressions"].sum()),
        "Link clicks": int(m["clicks"].sum()), "Purchases": int(m["purchases"].sum()),
        "Purchases conversion value": f"{m['value'].sum():.2f}",
    }])
    pd.concat([summary, meta]).to_csv(out_dir / "meta_ads_export.csv", index=False)
    written["meta_ads_export.csv"] = len(meta) + 1

    g = rows[platform == "google"]
    conv = (g["purchases"] * rng.uniform(0.92, 1.08, len(g))).round(2)
    google = pd.DataFrame({
        "Day": g["date"].astype(str), "Campaign": name[g["campaign"]],
        "Campaign type": [GOOGLE_TYPE_LABEL[k] for k in kind[platform == "google"]],
        "Currency code": "EUR",
        "Cost": g["spend"].map(lambda v: f"{v:,.2f}"),
        "Impr.": g["impressions"].map(lambda v: f"{v:,}"),
        "Clicks": g["clicks"].map(lambda v: f"{v:,}"),
        "Conversions": np.where(conv > 0, conv.map(lambda v: f"{v:,.2f}"), "--"),
        "Conv. value": np.where(g["value"] > 0, g["value"].map(lambda v: f"{v:,.2f}"), "--"),
    })
    path = out_dir / "google_ads_campaigns.csv"
    with path.open("w", newline="", encoding="utf-8") as f:
        f.write("Campaign report\n")
        f.write(f"{cfg.history_start.day} {cfg.history_start:%B %Y} - {cfg.as_of.day} {cfg.as_of:%B %Y}\n")
        google.to_csv(f, index=False)
    written["google_ads_campaigns.csv"] = len(google)

    t = rows[(platform == "tiktok") & (rows["spend"] > 0)]
    tiktok = pd.DataFrame({
        "Date": pd.to_datetime(t["date"]).dt.strftime("%d/%m/%Y"), "Campaign name": name[t["campaign"]],
        "Cost": _money(t["spend"]).to_numpy(), "Impressions": t["impressions"].to_numpy(),
        "Clicks (destination)": t["clicks"].to_numpy(), "Complete payment": t["purchases"].to_numpy(),
        "Total complete payment value": _money(t["value"]).to_numpy(),
    })
    total = pd.DataFrame([{
        "Date": f"Total of {len(tiktok)} results", "Campaign name": "", "Cost": f"{t['spend'].sum():.2f}",
        "Impressions": int(t["impressions"].sum()), "Clicks (destination)": int(t["clicks"].sum()),
        "Complete payment": int(t["purchases"].sum()), "Total complete payment value": f"{t['value'].sum():.2f}",
    }])
    pd.concat([tiktok, total]).to_csv(out_dir / "tiktok_ads_export.csv", index=False)
    written["tiktok_ads_export.csv"] = len(tiktok) + 1
    return written


def _write_ga4(cfg: Config, cal: pd.DataFrame, ads: pd.DataFrame, organic: pd.DataFrame,
               orders: pd.DataFrame, ret_potential: np.ndarray, rng: np.random.Generator,
               out_dir: Path) -> dict[str, int]:
    potential = (ads.groupby("day")["potential_new"].sum().to_numpy() + organic["potential"].to_numpy()
                 + ret_potential)
    sessions = np.round(potential / cal["cr_base"].to_numpy() * rng.lognormal(0, 0.06, len(cal))).astype(int)
    real = orders[~orders["is_test"] & (orders["status"] != "voided")]
    daily_orders = real.groupby("day").size().reindex(range(len(cal)), fill_value=0).to_numpy()
    transactions = rng.binomial(daily_orders, 0.88)  # consent mode loses some purchases

    keep = np.flatnonzero(cal["date"].to_numpy() >= cfg.history_start)
    out = []
    for i in keep:
        m = cal.at[i, "mobile_share"]
        dev_share = np.array([m, 1 - m - 0.04, 0.04])
        p_sess = np.outer(CHANNEL_SHARE, dev_share).ravel()
        s = rng.multinomial(sessions[i], p_sess / p_sess.sum())
        dev_cr = DEVICE_CR * np.array([cal.at[i, "mobile_cr_mult"], 1, 1])
        p_tx = np.outer(CHANNEL_SHARE * CHANNEL_CR, dev_share * dev_cr).ravel()
        t = rng.multinomial(transactions[i], p_tx / p_tx.sum())
        engaged = rng.binomial(s, np.tile([0.58, 0.70, 0.62], len(CHANNELS)))
        users = rng.binomial(s, 0.86)
        d = cal.at[i, "date"].strftime("%Y%m%d")
        for j in range(len(p_sess)):
            out.append((d, CHANNELS[j // 3], DEVICES[j % 3], s[j], engaged[j], users[j], t[j]))
    ga = pd.DataFrame(out, columns=["Date", "Session default channel group", "Device category", "Sessions",
                                    "Engaged sessions", "Total users", "Transactions"])
    path = out_dir / "ga4_sessions.csv"
    with path.open("w", newline="", encoding="utf-8") as f:
        f.write("# ----------------------------------------\n")
        f.write(f"# {cfg.brand} - GA4\n")
        f.write("# Sessions by date, channel group and device\n")
        f.write(f"# {cfg.history_start:%Y%m%d}-{cfg.as_of:%Y%m%d}\n")
        f.write("# ----------------------------------------\n\n")
        ga.to_csv(f, index=False)
    return {"ga4_sessions.csv": len(ga)}


def _write_costs(out_dir: Path) -> None:
    rows = [f"{p.sku};{p.name};" + f"{p.cost:.2f}".replace(".", ",") for p in PRODUCTS if p.sku != MISSING_COST_SKU]
    (out_dir / "product_costs.csv").write_text("SKU;Product;Unit cost (EUR)\n" + "\n".join(rows) + "\n",
                                              encoding="utf-8")
