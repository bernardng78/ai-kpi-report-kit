"""Design tokens shared by the workbook and the HTML report.

Ink, surfaces and status colours follow one small system: text always wears
ink tokens, status colours only ever mean status, and every status ships with
its label so colour never carries meaning alone.
"""
from __future__ import annotations

FONT = "Arial"  # workbook font; the HTML report uses the system sans

INK = "0B0B0B"
INK_2 = "52514E"
MUTED = "898781"
GRID = "E1E0D9"
BASELINE = "C3C2B7"
SURFACE = "FCFCFB"
PANEL = "F0EFEC"
ACCENT = "2A78D6"       # the one data series colour (actuals)
INPUT_BLUE = "0000FF"   # inputs typed or pasted in, by spreadsheet convention
SETTING_FILL = "FFF6CC"  # cells a reader may change

# status -> (solid colour for marks and icons, light tint for cell fills)
STATUS = {
    "On track": ("0CA30C", "DBF1DB"),
    "Watch": ("FAB219", "FEF0D1"),
    "Off track": ("D03B3B", "F8E2E2"),
    "On plan": (MUTED, "F1F1F0"),
    "Above plan": (MUTED, "F1F1F0"),
    "Below plan": (MUTED, "F1F1F0"),
    "n/a": (MUTED, "FFFFFF"),
}

NUMBER_FORMAT = {
    "money": '"€"#,##0',
    "money2": '"€"#,##0.00',
    "int": "#,##0",
    "pct1": "0.0%",
    "pct2": "0.00%",
    "ratio": '0.00"x"',
}
PERF_FORMAT = "+0.0%;-0.0%;0.0%"
