"""Store settings, cost assumptions and target windows.

Every number here is an assumption about the demo store. Change them here and
rebuild; the README lists them for readers who never open the code.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class Config:
    brand: str = "Demo Store"
    currency_symbol: str = "€"
    timezone: str = "Europe/Copenhagen"
    vat_rate: float = 0.25                 # shelf prices include 25% VAT
    payment_fee_pct: float = 0.019         # of the order total incl. VAT
    payment_fee_fixed: float = 0.25        # per order
    fulfilment_per_order: float = 5.20     # pick, pack and ship, ex VAT
    fulfilment_per_extra_unit: float = 0.90
    missing_cost_share: float = 0.40       # unit cost as a share of net price when a SKU has no cost row
    history_start: date = date(2023, 10, 30)  # first day in the exports (a Monday)
    customer_metrics_from: date = date(2024, 4, 29)  # 26 weeks in: earlier "new" customers may be old ones
    as_of: date = date(2026, 10, 25)          # last complete day (a Sunday)
    seed: int = 7


# How each grain builds its target: same period last year (the anchor), scaled by
# how the last few periods compare with the same periods a year earlier.
#   lag       periods in a year
#   anchor    half-width of the anchor window around the same period last year
#   trailing  periods in the growth comparison
#   band      prior periods used to size the amber/red bands
WINDOWS = {
    "week": {"lag": 52, "anchor": 1, "trailing": 13, "band": 13},
    "month": {"lag": 12, "anchor": 0, "trailing": 3, "band": 6},
    "quarter": {"lag": 4, "anchor": 0, "trailing": 2, "band": 4},
}

# Sheet-level settings. The workbook's formulas read these from its Settings tab.
GROWTH_MIN = 0.67     # growth factor clamp (-33% to +50%), so a launch year or one odd period
GROWTH_MAX = 1.5      # can't set a silly target
BAND_FLOOR = 0.02     # bands never tighter than ±2%...
BAND_CAP = 0.40       # ...or looser than ±40%
DEFAULT_BAND = 0.10   # used until a KPI has a full band window of history

# Cohort offset for the 90-day repeat rate: the cohort that first bought one
# offset earlier has had about 90 days to come back by the end of the period.
COHORT_OFFSET = {"week": 13, "month": 3, "quarter": 1}

GRAIN_LABEL = {"week": "Weekly", "month": "Monthly", "quarter": "Quarterly"}
