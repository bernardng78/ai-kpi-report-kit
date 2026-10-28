"""Turn each period's numbers into the actions that close a report section.

Every action is a rule over the KPI results and the period breakdowns, with
the numbers written in. Each section keeps at most three. Nothing here is
generated free-form, so the same numbers always produce the same advice, and a
reviewer can trace every line back to a rule.

Breakdowns are compared with the same period last year where seasonality
matters (product mix, traffic sources) and with the trailing window where it
doesn't (device conversion, channel efficiency, cost shares).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .config import WINDOWS
from .facts import PeriodData
from .kpis import SECTIONS

ROUND_TO = {"week": 50, "month": 100, "quarter": 500}
GROUP_LABEL = {
    ("meta", "prospecting"): "Meta prospecting", ("meta", "retargeting"): "Meta retargeting",
    ("google", "brand"): "Google brand search", ("google", "generic"): "Google generic search",
    ("google", "pmax"): "Google Performance Max", ("google", "shopping"): "Google Shopping",
    ("tiktok", "prospecting"): "TikTok",
}
NOT_A_DESTINATION = {"brand", "retargeting"}  # they harvest demand that exists and can't absorb budget
MIN_DEVICE_TRANSACTIONS = 50
BAD = ("Watch", "Off track")


def _money(v: float, cents: bool = False) -> str:
    return f"€{v:,.2f}" if cents else f"€{v:,.0f}"


def _pct(v: float, digits: int = 1) -> str:
    return f"{v * 100:.{digits}f}%"


def _vs(perf: float) -> str:
    return f"{abs(perf) * 100:.1f}% {'under' if perf < 0 else 'over'} target"


def _change(v: float) -> str:
    return f"{'down' if v < 0 else 'up'} {abs(v) * 100:.1f}%"


class _Period:
    """Read-only view of one period: KPI rows plus breakdown lookups."""

    def __init__(self, key: str, results: dict[str, pd.DataFrame], data: PeriodData):
        w = WINDOWS[data.grain]
        self.key = key
        self.results = results
        self.data = data
        keys = list(data.table.index)
        pos = keys.index(key)
        self.t = w["trailing"]
        self.unit = data.grain
        self.prev = keys[max(0, pos - self.t):pos]
        lo, hi = pos - w["lag"] - w["anchor"], pos - w["lag"] + w["anchor"]
        self.last_year = keys[lo:hi + 1] if lo >= 0 else []

    def k(self, kpi: str) -> pd.Series:
        return self.results[kpi].loc[self.key]

    def row(self) -> pd.Series:
        return self.data.table.loc[self.key]

    def total(self, keys: list[str], column: str) -> float:
        return float(self.data.table.loc[keys, column].sum())


def _slice(frame: pd.DataFrame, keys: list[str]) -> pd.DataFrame:
    return frame[frame.index.get_level_values("key").isin(keys)]


def revenue(p: _Period) -> list[str]:
    out = []
    rev, orders, aov, refund = p.k("net_rev"), p.k("orders"), p.k("aov"), p.k("refund_rate")
    if rev["status"] in BAD:
        if orders["perf"] < aov["perf"]:
            out.append(f"Revenue is {_vs(rev['perf'])} because orders are {_vs(orders['perf'])} while order "
                       f"value held ({_vs(aov['perf'])}). Fix volume first: see conversion and acquisition below.")
        else:
            disc_now = p.row()["discounts"] / p.row()["gross_rev"]
            disc_before = p.total(p.prev, "discounts") / p.total(p.prev, "gross_rev")
            out.append(f"Revenue is {_vs(rev['perf'])} because order value fell to {_money(aov['actual'], True)} "
                       f"(target {_money(aov['target'], True)}). Discounts were {_pct(disc_now)} of gross sales, "
                       f"against {_pct(disc_before)} over the previous {p.t} {p.unit}s.")
    elif orders["status"] in BAD and aov["perf"] > 0:
        out.append(f"Revenue is within its normal range, but only because order value is {_vs(aov['perf'])}: "
                   f"orders are {_vs(orders['perf'])}. The order gap traces to conversion below.")

    if refund["status"] in BAD:
        skus = p.data.skus
        recent = _slice(skus, p.prev[-(p.t // 2 or 1):] + [p.key]).groupby(level="sku").sum()
        store_rate = recent["refunds"].sum() / recent["net_sales"].sum()
        excess = recent["refunds"] - recent["net_sales"] * store_rate  # refunds above the range's own rate
        top = excess.idxmax()
        if excess[top] > 0:
            rest = recent.drop(index=top)
            name = p.data.sku_names.get(top, top)
            out.append(f"Refunds are {_pct(refund['actual'])} of gross revenue (target {_pct(refund['target'])}). "
                       f"{name} ({top}) is refunded at {_pct(recent.loc[top, 'refunds'] / recent.loc[top, 'net_sales'], 0)} "
                       f"of its recent sales, against {_pct(rest['refunds'].sum() / rest['net_sales'].sum(), 0)} for the "
                       f"rest of the range. Check its size guide and reviews before reordering.")

    if aov["status"] == "On track" and aov["perf"] > max(aov["band"] if np.isfinite(aov["band"]) else 0, 0.02) \
            and p.last_year:
        skus = p.data.skus
        now = _slice(skus, [p.key]).groupby(level="sku")["net_sales"].sum()
        before = _slice(skus, p.last_year).groupby(level="sku")["net_sales"].sum()
        share_now = now / now.sum()
        share_before = (before / before.sum()).reindex(share_now.index, fill_value=0)
        riser = (share_now - share_before).idxmax()
        if share_now[riser] - share_before[riser] > 0.03:
            name = p.data.sku_names.get(riser, riser)
            out.append(f"Order value is {_vs(aov['perf'])} at {_money(aov['actual'], True)}, helped by {name}: "
                       f"{_pct(share_now[riser], 0)} of sales, against {_pct(share_before[riser], 0)} a year ago. "
                       f"Keep it in front of returning customers.")

    if not out:
        if rev["perf"] < 0 and np.isfinite(rev["band"]):
            return [f"Revenue is {_vs(rev['perf'])}, within normal {p.unit}ly variation "
                    f"(±{_pct(rev['band'] / 2)}). No action needed."]
        return [f"Revenue is {_vs(rev['perf'])}. No action needed."]
    return out[:3]


def _device_cr(p: _Period, keys: list[str]) -> pd.DataFrame:
    d = _slice(p.data.devices, keys).groupby(level="device").sum()
    d["cr"] = d["transactions"] / d["sessions"]
    return d


def site(p: _Period) -> list[str]:
    out = []
    cr, sessions = p.k("cr"), p.k("sessions")
    if cr["status"] in BAD:
        now, before = _device_cr(p, [p.key]), _device_cr(p, p.prev)
        big = now[(now["transactions"] >= MIN_DEVICE_TRANSACTIONS)
                  & (now["sessions"] >= 0.10 * now["sessions"].sum())].index  # small devices are mostly noise
        change = (now.loc[big, "cr"] / before.loc[big, "cr"] - 1).dropna()
        worst = change.idxmin() if len(change) else None
        others = change.drop(index=worst) if worst else change
        if worst and change[worst] < -0.08 and (others > change[worst] / 2).all():
            start = p.key
            for key in reversed(p.prev):  # walk back while the device stays well under its old level
                if _device_cr(p, [key]).loc[worst, "cr"] < before.loc[worst, "cr"] * 0.92:
                    start = key
                else:
                    break
            held = ", ".join(f"{dev} at {_pct(now.loc[dev, 'cr'], 2)}" for dev in others.index)
            out.append(f"{worst.title()} conversion fell to {_pct(now.loc[worst, 'cr'], 2)} from "
                       f"{_pct(before.loc[worst, 'cr'], 2)} ({_change(change[worst])}) while {held} held. It started "
                       f"in {start}: test the {worst} checkout end to end and review theme, app and payment changes "
                       f"made that {p.unit}.")
        else:
            out.append(f"Conversion fell across devices to {_pct(cr['actual'], 2)} (target {_pct(cr['target'], 2)}). "
                       f"Check stock-outs on top sellers, delivery promises and site speed.")
        if sessions["status"] == "On track":
            out.append(f"Traffic is {_vs(sessions['perf'])}, so the gap is conversion, not demand.")
    if sessions["status"] in BAD and p.last_year:
        ch = p.data.channels
        now = _slice(ch, [p.key]).groupby(level="channel")["sessions"].sum()
        ly = _slice(ch, p.last_year).groupby(level="channel")["sessions"].mean()
        expected = ly * sessions["target"] / ly.sum()  # last year's mix scaled to this period's target
        gap = (now - expected).sort_values()
        top = gap.index[0]
        out.append(f"Sessions are {_vs(sessions['perf'])}. The biggest gap is {top}: {now[top]:,.0f} sessions "
                   f"against about {expected[top]:,.0f} expected from last year's mix.")
    return out[:3] or [f"Traffic and conversion are on track: {_pct(cr['actual'], 2)} of "
                       f"{sessions['actual']:,.0f} sessions converted."]


def acquisition(p: _Period) -> list[str]:
    out = []
    ncac, mer, new, spend, cr = p.k("ncac"), p.k("mer"), p.k("new_customers"), p.k("spend"), p.k("cr")
    now = _slice(p.data.ads, [p.key]).groupby(level=["platform", "kind"]).sum()
    before = _slice(p.data.ads, p.prev).groupby(level=["platform", "kind"]).sum()
    roas_now, roas_before = now["value"] / now["spend"], before["value"] / before["spend"]
    if ncac["status"] in BAD or mer["status"] in BAD:
        change = (roas_now / roas_before - 1).dropna()
        share = now["spend"] / now["spend"].sum()
        sizable = change[share.reindex(change.index) > 0.10]
        destinations = [g for g in change.index if g[1] not in NOT_A_DESTINATION]
        if len(sizable) and change[sizable.idxmin()] < -0.10:
            worst = sizable.idxmin()
            options = [g for g in destinations if g != worst]
            if options:
                best = roas_now[options].idxmax()
                step = ROUND_TO[p.unit]
                amount = max(step, round(now.loc[worst, "spend"] * 0.15 / step) * step)
                line = (f"New-customer CAC is {_money(ncac['actual'], True)} against a {_money(ncac['target'], True)} "
                        f"target. Move about {_money(amount)} a {p.unit} from {GROUP_LABEL[worst]} (platform ROAS "
                        f"{roas_now[worst]:.2f}, {_change(change[worst])} on its {p.t}-{p.unit} average) to "
                        f"{GROUP_LABEL[best]} (ROAS {roas_now[best]:.2f}).")
                cpm_change = ((now.loc[worst, "spend"] / now.loc[worst, "impressions"])
                              / (before.loc[worst, "spend"] / before.loc[worst, "impressions"]) - 1)
                if cpm_change > 0.10:
                    line += f" Its CPMs are {_change(cpm_change)}, so refresh the creative as well."
                out.append(line)
        if cr["status"] in BAD and ncac["status"] in BAD:
            out.append("Part of the CAC rise is the conversion drop under Site & conversion: fixing it lowers CAC "
                       "without touching budgets.")
    if new["status"] in BAD and ncac["status"] == "On track":
        out.append(f"CAC is on target, so the new-customer gap ({_vs(new['perf'])}) is volume: raise the "
                   f"best-performing prospecting budget by about 10%.")
    if spend["status"] in ("Above plan", "Below plan"):
        out.append(f"Spend ran {_vs(spend['perf']).replace('target', 'its trajectory')} ({_money(spend['actual'])} "
                   f"against {_money(spend['target'])}). Confirm the change was intended.")
    return out[:3] or [f"Acquisition is on track: MER {mer['actual']:.2f} (target {mer['target']:.2f}), new-customer "
                       f"CAC {_money(ncac['actual'], True)} (target {_money(ncac['target'], True)})."]


def retention(p: _Period) -> list[str]:
    out = []
    share, repeat, new = p.k("returning_share"), p.k("repeat_90d"), p.k("new_customers")
    winback = int(p.data.winback.get(p.key, 0))
    if not np.isfinite(share["perf"]):
        return ["Not enough customer history yet for retention targets."]
    if share["perf"] > max(share["band"] if np.isfinite(share["band"]) else 0, 0.05) and new["status"] in BAD:
        loyalty = "so loyalty hasn't changed" if repeat["status"] == "On track" else "and it is slipping too"
        out.append(f"Returning customers are {_pct(share['actual'], 0)} of revenue (target {_pct(share['target'], 0)}), "
                   f"but only because fewer new customers came in. The 90-day repeat rate is "
                   f"{_pct(repeat['actual'])}, {repeat['status'].lower()}, {loyalty}.")
    if repeat["status"] in BAD:
        out.append(f"Fewer first-time buyers come back: {_pct(repeat['actual'])} reordered within 90 days, against "
                   f"{_pct(repeat['target'])}. Review the post-purchase emails and send a win-back to the "
                   f"{winback:,} customers whose last order was 90-180 days ago.")
    elif share["status"] in BAD:
        out.append(f"Returning customers drove {_pct(share['actual'], 0)} of revenue, against "
                   f"{_pct(share['target'], 0)}. Send a win-back to the {winback:,} customers whose last order was "
                   f"90-180 days ago.")
    return out[:3] or [f"Retention is on track: {_pct(repeat['actual'])} of new customers reorder within 90 days. "
                       f"The {winback:,} customers whose last order was 90-180 days ago are the next win-back audience."]


def profit(p: _Period) -> list[str]:
    out = []
    cm_pct, gm = p.k("cm_pct"), p.k("gm_pct")
    row = p.row()
    parts = {"ad spend": "spend_total", "cost of goods": "cogs", "fulfilment": "fulfilment",
             "payment fees": "fees", "refunds": "refunds"}
    net_before = p.total(p.prev, "net_rev")
    now = {name: row[col] / row["net_rev"] for name, col in parts.items()}
    before = {name: p.total(p.prev, col) / net_before for name, col in parts.items()}
    if cm_pct["status"] in BAD:
        driver = max(parts, key=lambda name: now[name] - before[name])
        out.append(f"Contribution margin is {_pct(cm_pct['actual'])} of net revenue, against {_pct(cm_pct['target'])}. "
                   f"The main driver is {driver} at {_pct(now[driver])} of net revenue, against "
                   f"{_pct(before[driver])} over the previous {p.t} {p.unit}s "
                   f"({(now[driver] - before[driver]) * 100:+.1f} pts).")
    if gm["status"] in BAD:
        disc_now = row["discounts"] / row["gross_rev"]
        disc_before = p.total(p.prev, "discounts") / p.total(p.prev, "gross_rev")
        if disc_now - disc_before >= 0.01:
            out.append(f"Gross margin slipped to {_pct(gm['actual'])} (target {_pct(gm['target'])}) because discounts "
                       f"rose to {_pct(disc_now)} of gross sales from {_pct(disc_before)}. Check which codes ran and "
                       f"whether they paid for themselves.")
        else:
            out.append(f"Gross margin slipped to {_pct(gm['actual'])} (target {_pct(gm['target'])}) with discounts "
                       f"steady, so cost of goods rose to {_pct(now['cost of goods'])} of net revenue from "
                       f"{_pct(before['cost of goods'])}. Check the product mix and any supplier price changes.")
    return out[:3] or [f"Profit is on track: contribution margin {_money(row['cm'])}, "
                       f"{_pct(cm_pct['actual'])} of net revenue."]


RULES = {"Revenue": revenue, "Site & conversion": site, "Acquisition": acquisition,
         "Retention": retention, "Profit": profit}


def build(results: dict[str, pd.DataFrame], data: PeriodData, keys: list[str]) -> pd.DataFrame:
    """One row per period, section and action number."""
    rows = []
    for key in keys:
        p = _Period(key, results, data)
        for section in SECTIONS:
            for n, text in enumerate(RULES[section](p), start=1):
                rows.append((data.grain, key, section, n, text))
    return pd.DataFrame(rows, columns=["grain", "key", "section", "n", "text"])
