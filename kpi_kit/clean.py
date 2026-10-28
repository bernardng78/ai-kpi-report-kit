"""Load the raw exports, fix their quirks and log every decision.

Each loader returns a tidy frame. Anything that changes or drops data is
recorded in DataChecks, which the workbook prints on its Data checks tab, so a
reviewer can see what was cleaned without reading code.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

from .config import Config

LINE_COLS = ["Lineitem quantity", "Lineitem name", "Lineitem price", "Lineitem sku"]
MONEY_COLS = ["Subtotal", "Shipping", "Taxes", "Total", "Discount Amount", "Refunded Amount"]
VALID_STATUSES = {"paid", "partially_refunded", "refunded"}
PLATFORM_LABEL = {"meta": "Meta", "google": "Google", "tiktok": "TikTok"}


@dataclass
class DataChecks:
    rows: list[tuple[str, str, str]] = field(default_factory=list)  # (source, check, result)

    def add(self, source: str, check: str, result: str) -> None:
        self.rows.append((source, check, result))


@dataclass
class CleanData:
    orders: pd.DataFrame   # one row per valid order
    lines: pd.DataFrame    # line items of valid orders
    refunds: pd.DataFrame  # refund lines, dated by refund
    ads: pd.DataFrame      # one row per day per campaign
    ga4: pd.DataFrame      # one row per day per channel group per device
    costs: dict[str, float]
    checks: DataChecks
    sku_names: dict[str, str]


def load_all(raw: Path, cfg: Config) -> CleanData:
    checks = DataChecks()
    orders, lines, sku_names = load_orders(raw, cfg, checks)
    costs = load_costs(raw, cfg, lines, checks)
    refunds = load_refunds(raw, cfg, orders, checks)
    ads = load_ads(raw, cfg, checks)
    ga4 = load_ga4(raw, cfg, checks)
    return CleanData(orders, lines, refunds, ads, ga4, costs, checks, sku_names)


def _local_time(values: pd.Series, tz: str) -> pd.Series:
    # Offsets change with daylight saving, so parse as UTC and convert back to store time.
    return pd.to_datetime(values, format="%Y-%m-%d %H:%M:%S %z", utc=True).dt.tz_convert(tz)


def load_orders(raw: Path, cfg: Config, checks: DataChecks) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, str]]:
    files = sorted(raw.glob("orders_export_*.csv"))
    frames = []
    for i, path in enumerate(files, start=1):
        df = pd.read_csv(path, dtype=str, keep_default_na=False)
        df["_export"] = i
        frames.append(df)
    df = pd.concat(frames, ignore_index=True)
    checks.add("Shopify orders", "Files read",
               f"{len(files)} exports, {len(df):,} rows (Shopify writes one row per line item).")

    # Order fields sit on the first row of each order only.
    order_cols = [c for c in df.columns if c not in LINE_COLS + ["Name", "Email", "_export"]]
    df[order_cols] = df[order_cols].replace("", np.nan)
    df[order_cols] = df.groupby(["_export", "Name"], sort=False)[order_cols].ffill()

    # The exports overlap. Keep each order from the newest file: refunds keep arriving after a file is pulled.
    latest = df.groupby("Name")["_export"].transform("max")
    older = df[df["_export"] != latest].drop_duplicates("Name").set_index("Name")
    if len(older):
        newer = df[(df["_export"] == latest) & df["Name"].isin(older.index)].drop_duplicates("Name").set_index("Name")
        changed = (newer["Refunded Amount"].astype(float) - older["Refunded Amount"].astype(float)
                   .reindex(newer.index)).abs() > 0.005
        checks.add("Shopify orders", "Orders in two exports",
                   f"{len(older):,} orders appear in both files. Kept the newer file, which adds "
                   f"{int(changed.sum()):,} refunds made after the older one was pulled.")
    df = df[df["_export"] == latest].copy()

    for col in MONEY_COLS:
        df[col] = df[col].astype(float)
    df["qty"] = df["Lineitem quantity"].astype(int)
    df["price"] = df["Lineitem price"].astype(float)
    df["created"] = _local_time(df["Created at"], cfg.timezone)
    df["date"] = df["created"].dt.tz_localize(None).dt.normalize()

    orders = df.drop_duplicates("Name").copy()
    status = orders["Financial Status"].str.lower()
    tags = orders["Tags"].fillna("").str.lower()
    email = orders["Email"].str.strip().str.lower()
    is_test = tags.str.contains(r"\btest\b") | email.str.endswith("@demostore.test")
    cancelled = orders["Cancelled at"].notna() | (status == "voided")
    pending = status == "pending"
    valid = status.isin(VALID_STATUSES) & ~is_test & ~cancelled
    checks.add("Shopify orders", "Test orders removed",
               f"{int(is_test.sum()):,} orders tagged 'test' or placed from a staff address "
               f"(€{orders.loc[is_test, 'Total'].sum():,.0f} that would have inflated revenue).")
    checks.add("Shopify orders", "Cancelled and pending orders removed",
               f"{int((cancelled & ~is_test).sum()):,} cancelled and {int((pending & ~is_test).sum()):,} "
               f"unpaid orders are not revenue.")

    orders = orders[valid].copy()
    orders["email"] = email[valid]
    orders["gross_rev"] = orders["Total"] - orders["Taxes"]
    orders["discount_ex"] = orders["Discount Amount"] / (1 + cfg.vat_rate)
    orders["fees"] = cfg.payment_fee_pct * orders["Total"] + cfg.payment_fee_fixed
    orders = orders.sort_values("created", kind="stable")
    orders["is_new"] = ~orders.duplicated("email")
    checks.add("Shopify orders", "New vs returning customers",
               f"A customer is new on their first paid order in the exports, but someone who first bought "
               f"before {cfg.history_start:%d %b %Y} would look new too. Customer metrics (new customers, "
               f"CAC, returning share, repeat rate) therefore start on {cfg.customer_metrics_from:%d %b %Y}, "
               f"26 weeks in.")

    sku_names = dict(zip(df["Lineitem sku"], df["Lineitem name"]))
    lines = df[df["Name"].isin(orders["Name"])][["Name", "date", "Lineitem sku", "qty", "price"]].copy()
    lines = lines.rename(columns={"Lineitem sku": "sku"})
    rate = orders.set_index("Name")["Discount Amount"] / (orders.set_index("Name")["Subtotal"]
                                                        + orders.set_index("Name")["Discount Amount"])
    lines["net_ex"] = lines["qty"] * lines["price"] * (1 - lines["Name"].map(rate)) / (1 + cfg.vat_rate)
    units = lines.groupby("Name")["qty"].sum()
    orders["units"] = orders["Name"].map(units).astype(int)
    orders["fulfilment"] = cfg.fulfilment_per_order + cfg.fulfilment_per_extra_unit * (orders["units"] - 1)
    checks.add("Shopify orders", "Orders kept",
               f"{len(orders):,} paid orders from {orders['date'].min():%d %b %Y} to "
               f"{orders['date'].max():%d %b %Y}, {len(lines):,} line items.")
    return orders.reset_index(drop=True), lines.reset_index(drop=True), sku_names


def load_costs(raw: Path, cfg: Config, lines: pd.DataFrame, checks: DataChecks) -> dict[str, float]:
    costs = pd.read_csv(raw / "product_costs.csv", sep=";", decimal=",")
    table = dict(zip(costs["SKU"], costs["Unit cost (EUR)"].astype(float)))
    checks.add("Product costs", "File format", "Semicolon-separated with comma decimals (saved from a Danish Excel).")
    for sku in sorted(set(lines["sku"]) - set(table)):
        price = lines.loc[lines["sku"] == sku, "price"].iloc[0]
        table[sku] = round(cfg.missing_cost_share * price / (1 + cfg.vat_rate), 2)
        checks.add("Product costs", f"Missing cost: {sku}",
                   f"No cost row, so COGS uses {cfg.missing_cost_share:.0%} of its net price "
                   f"(€{table[sku]:.2f}) until the cost sheet is updated.")
    return table


def load_refunds(raw: Path, cfg: Config, orders: pd.DataFrame, checks: DataChecks) -> pd.DataFrame:
    r = pd.read_csv(raw / "refunds_export.csv", dtype=str, keep_default_na=False)
    r["refund_at"] = _local_time(r["Refund date"], cfg.timezone)
    r["date"] = r["refund_at"].dt.tz_localize(None).dt.normalize()
    r["amount_ex"] = r["Refund amount"].astype(float) / (1 + cfg.vat_rate)
    r["qty"] = r["Quantity"].astype(int)
    r["restocked"] = r["Restocked"].str.lower().eq("yes")
    r = r.rename(columns={"Order": "Name", "SKU": "sku"})

    known = r["Name"].isin(orders["Name"])
    by_order = r[known].groupby("Name")["Refund amount"].apply(lambda s: s.astype(float).sum())
    recorded = orders.set_index("Name")["Refunded Amount"]
    refunded_orders = recorded[recorded > 0]
    match = (by_order.reindex(refunded_orders.index, fill_value=0) - refunded_orders).abs() < 0.01
    checks.add("Refunds", "Booked on the refund date",
               "Refunds count in the period they are issued, as in Shopify's own sales reports, so recent "
               "weeks are final the day they close.")
    checks.add("Refunds", "Reconciles with orders",
               f"Refund lines add up to each order's Refunded Amount for {match.mean():.1%} of "
               f"{len(refunded_orders):,} refunded orders.")
    checks.add("Refunds", "Orders placed before the exports",
               f"{int((~known).sum()):,} refund lines belong to orders placed before "
               f"{cfg.history_start:%d %b %Y}. They still count, on their refund date.")
    return r[["Name", "date", "sku", "qty", "amount_ex", "restocked"]]


def _kind(platform: str, campaign: str, campaign_type: str = "") -> str:
    name = campaign.lower()
    if platform == "google":
        if "brand" in name:
            return "brand"
        return {"performance max": "pmax", "shopping": "shopping"}.get(campaign_type.lower(), "generic")
    return "retargeting" if name.startswith("rt ") or "| rt" in name else "prospecting"


def _to_number(s: pd.Series) -> pd.Series:
    return pd.to_numeric(s.astype(str).str.replace(",", "").replace({"--": "0", "": "0"}))


def load_ads(raw: Path, cfg: Config, checks: DataChecks) -> pd.DataFrame:
    meta = pd.read_csv(raw / "meta_ads_export.csv", dtype=str, keep_default_na=False)
    summary = meta["Campaign name"] == ""
    meta = meta[~summary]
    meta = pd.DataFrame({
        "date": pd.to_datetime(meta["Reporting starts"]), "platform": "meta", "campaign": meta["Campaign name"],
        "spend": _to_number(meta["Amount spent (EUR)"]), "impressions": _to_number(meta["Impressions"]),
        "clicks": _to_number(meta["Link clicks"]), "purchases": _to_number(meta["Purchases"]),
        "value": _to_number(meta["Purchases conversion value"]),
    })
    checks.add("Meta Ads", "Summary row dropped", f"Removed {int(summary.sum())} all-campaign total row above the data.")

    google = pd.read_csv(raw / "google_ads_campaigns.csv", dtype=str, keep_default_na=False, skiprows=2)
    google = pd.DataFrame({
        "date": pd.to_datetime(google["Day"]), "platform": "google", "campaign": google["Campaign"],
        "campaign_type": google["Campaign type"], "spend": _to_number(google["Cost"]),
        "impressions": _to_number(google["Impr."]), "clicks": _to_number(google["Clicks"]),
        "purchases": _to_number(google["Conversions"]), "value": _to_number(google["Conv. value"]),
    })
    checks.add("Google Ads", "Title rows and text numbers",
               "Skipped the 2 report-title lines; read '1,234.56' as numbers and '--' as zero.")

    tiktok = pd.read_csv(raw / "tiktok_ads_export.csv", dtype=str, keep_default_na=False)
    total_row = tiktok["Date"].str.startswith("Total")
    tiktok = tiktok[~total_row]
    tiktok = pd.DataFrame({
        "date": pd.to_datetime(tiktok["Date"], format="%d/%m/%Y"), "platform": "tiktok",
        "campaign": tiktok["Campaign name"], "spend": _to_number(tiktok["Cost"]),
        "impressions": _to_number(tiktok["Impressions"]), "clicks": _to_number(tiktok["Clicks (destination)"]),
        "purchases": _to_number(tiktok["Complete payment"]), "value": _to_number(tiktok["Total complete payment value"]),
    })
    checks.add("TikTok Ads", "Day-first dates and totals row",
               f"Read dates as DD/MM/YYYY and removed {int(total_row.sum())} totals row. "
               f"Spend starts {tiktok['date'].min():%d %b %Y}, when the channel launched.")

    ads = pd.concat([meta, google, tiktok], ignore_index=True)
    ads["campaign_type"] = ads["campaign_type"].fillna("")
    ads["kind"] = [_kind(p, c, t) for p, c, t in zip(ads["platform"], ads["campaign"], ads["campaign_type"])]
    ads = ads[(ads["date"] >= pd.Timestamp(cfg.history_start)) & (ads["date"] <= pd.Timestamp(cfg.as_of))]
    totals = ads.groupby("platform")["spend"].sum()
    checks.add("Ad platforms", "Spend loaded",
               ", ".join(f"{PLATFORM_LABEL[p]} €{v:,.0f}" for p, v in totals.items()) + ". Platform-reported purchase "
               "value is kept for budget splits only; totals use Shopify revenue.")
    return ads.drop(columns="campaign_type").reset_index(drop=True)


def load_ga4(raw: Path, cfg: Config, checks: DataChecks) -> pd.DataFrame:
    ga = pd.read_csv(raw / "ga4_sessions.csv", comment="#", dtype={"Date": str})
    ga = ga.rename(columns={"Session default channel group": "channel", "Device category": "device",
                            "Sessions": "sessions", "Engaged sessions": "engaged", "Total users": "users",
                            "Transactions": "transactions"})
    ga["date"] = pd.to_datetime(ga["Date"], format="%Y%m%d")
    days = ga["date"].nunique()
    expected = (pd.Timestamp(cfg.as_of) - pd.Timestamp(cfg.history_start)).days + 1
    checks.add("GA4", "Comment header and dates",
               f"Skipped the comment lines above the header and read YYYYMMDD dates. {days:,} of "
               f"{expected:,} days present.")
    checks.add("GA4", "Transactions are not orders",
               "GA4 records fewer purchases than Shopify (consent banners), so conversion rate uses "
               "Shopify orders over GA4 sessions; GA4 transactions are only used to compare devices.")
    return ga[["date", "channel", "device", "sessions", "engaged", "users", "transactions"]]
