"""The KPI dictionary: one place that says what every metric means.

A KPI is a numerator over an optional denominator, both base columns of the
period data. Additive KPIs (no denominator) are summed; ratio KPIs are a ratio
of sums, never an average of ratios.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Kpi:
    id: str
    label: str
    section: str
    num: str
    den: str | None
    direction: str  # "up" (higher is better), "down" (lower is better) or "neutral"
    fmt: str        # money, money2, int, pct1, pct2, ratio
    definition: str

    @property
    def is_ratio(self) -> bool:
        return self.den is not None


SECTIONS = ["Revenue", "Site & conversion", "Acquisition", "Retention", "Profit"]

KPIS = [
    Kpi("net_rev", "Net revenue", "Revenue", "net_rev", None, "up", "money",
        "Gross revenue minus refunds issued in the period, ex VAT."),
    Kpi("orders", "Orders", "Revenue", "orders", None, "up", "int",
        "Paid orders, excluding test, pending and cancelled orders."),
    Kpi("aov", "Average order value", "Revenue", "gross_rev", "orders", "up", "money2",
        "Gross revenue ex VAT ÷ orders."),
    Kpi("refund_rate", "Refund rate", "Revenue", "refunds", "gross_rev", "down", "pct1",
        "Refunds issued in the period ÷ gross revenue, both ex VAT."),
    Kpi("sessions", "Sessions", "Site & conversion", "sessions", None, "up", "int",
        "GA4 sessions, all channels and devices."),
    Kpi("cr", "Conversion rate", "Site & conversion", "orders", "sessions", "up", "pct2",
        "Shopify orders ÷ GA4 sessions."),
    Kpi("spend", "Ad spend", "Acquisition", "spend_total", None, "neutral", "money",
        "Meta + Google + TikTok spend. Shown against trajectory, not judged good or bad."),
    Kpi("mer", "MER", "Acquisition", "net_rev", "spend_total", "up", "ratio",
        "Net revenue ÷ ad spend: blended efficiency from Shopify, not platform claims."),
    Kpi("new_customers", "New customers", "Acquisition", "new_customers", None, "up", "int",
        "Customers whose first paid order falls in the period."),
    Kpi("ncac", "New-customer CAC", "Acquisition", "spend_total", "new_customers", "down", "money2",
        "Ad spend ÷ new customers."),
    Kpi("roas_meta", "Meta ROAS (platform)", "Acquisition", "value_meta", "spend_meta", "up", "ratio",
        "Meta-reported purchase value ÷ Meta spend. Used to split budget, not to judge totals."),
    Kpi("roas_google", "Google ROAS (platform)", "Acquisition", "value_google", "spend_google", "up", "ratio",
        "Google-reported conversion value ÷ Google spend. Used to split budget, not to judge totals."),
    Kpi("roas_tiktok", "TikTok ROAS (platform)", "Acquisition", "value_tiktok", "spend_tiktok", "up", "ratio",
        "TikTok-reported purchase value ÷ TikTok spend. Used to split budget, not to judge totals."),
    Kpi("returning_share", "Returning-customer share", "Retention", "returning_gross", "gross_rev", "up", "pct1",
        "Gross revenue from customers with an earlier paid order ÷ gross revenue."),
    Kpi("repeat_90d", "90-day repeat rate", "Retention", "cohort_repeat90", "cohort_new", "up", "pct1",
        "Of the customers who first bought about 90 days earlier, the share who ordered again within 90 days."),
    Kpi("gm_pct", "Gross margin %", "Profit", "gross_margin", "net_rev", "up", "pct1",
        "(Net revenue − COGS) ÷ net revenue. COGS is net of restocked returns."),
    Kpi("cm", "Contribution margin", "Profit", "cm", None, "up", "money",
        "Net revenue − COGS − fulfilment − payment fees − ad spend."),
    Kpi("cm_pct", "Contribution margin %", "Profit", "cm", "net_rev", "up", "pct1",
        "Contribution margin ÷ net revenue."),
]

KPI_BY_ID = {k.id: k for k in KPIS}

# Base columns of the period data, in sheet order: (id, header, format, formula).
# A formula column is derived inside the workbook from the columns before it.
BASE_COLUMNS = [
    ("orders", "Orders", "int", None),
    ("gross_rev", "Gross revenue", "money", None),
    ("discounts", "Discounts", "money", None),
    ("refunds", "Refunds issued", "money", None),
    ("net_rev", "Net revenue", "money", "{gross_rev}-{refunds}"),
    ("units", "Units sold", "int", None),
    ("cogs", "COGS net of restocked returns", "money", None),
    ("fulfilment", "Fulfilment", "money", None),
    ("fees", "Payment fees", "money", None),
    ("spend_meta", "Meta spend", "money", None),
    ("spend_google", "Google spend", "money", None),
    ("spend_tiktok", "TikTok spend", "money", None),
    ("spend_total", "Ad spend", "money", "{spend_meta}+{spend_google}+{spend_tiktok}"),
    ("value_meta", "Meta-reported value", "money", None),
    ("value_google", "Google-reported value", "money", None),
    ("value_tiktok", "TikTok-reported value", "money", None),
    ("new_customers", "New customers", "int", None),
    ("returning_gross", "Returning-customer gross revenue", "money", None),
    ("cohort_new", "Repeat cohort size", "int", None),
    ("cohort_repeat90", "Repeat cohort: back within 90 days", "int", None),
    ("sessions", "Sessions", "int", None),
    ("gross_margin", "Gross margin", "money", "{net_rev}-{cogs}"),
    ("cm", "Contribution margin", "money", "{net_rev}-{cogs}-{fulfilment}-{fees}-{spend_total}"),
]
