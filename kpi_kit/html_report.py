"""Write the shareable HTML report: one file, three tabs (weekly, monthly, quarterly).

It shows the same numbers as the workbook (both come from targets.py and the
tests hold them equal), laid out for a client to read: headline tiles, then
each section's KPIs, a trend chart and the actions.
"""
from __future__ import annotations

import json
from html import escape
from pathlib import Path

import numpy as np
import pandas as pd

from .config import DEFAULT_BAND, GRAIN_LABEL, WINDOWS, Config
from .facts import GRAINS, PeriodData
from .kpis import KPI_BY_ID, KPIS, SECTIONS

TILES = ["net_rev", "orders", "cr", "mer", "ncac", "cm_pct"]
SECTION_CHART = {"Revenue": "net_rev", "Site & conversion": "cr", "Acquisition": "ncac",
                 "Retention": "repeat_90d", "Profit": "cm_pct"}
CHART_PERIODS = {"week": 13, "month": 13, "quarter": 5}
STATUS_CLASS = {"On track": "good", "Watch": "warn", "Off track": "bad", "On plan": "neutral",
                "Above plan": "neutral", "Below plan": "neutral", "n/a": "neutral"}
ICON = {
    "good": '<path d="M3.5 8.5l3 3 6-7" />',
    "warn": '<path d="M8 3.2v5.6M8 11.6v.4" />',
    "bad": '<path d="M4.5 4.5l7 7M11.5 4.5l-7 7" />',
    "neutral": '<path d="M4 8h8" />',
}
PERIOD_WORD = {"week": "Week", "month": "Month", "quarter": "Quarter"}


def fmt(value: float, kind: str) -> str:
    if value is None or not np.isfinite(value):
        return "–"
    if kind == "money":
        return f"€{value:,.0f}"
    if kind == "money2":
        return f"€{value:,.2f}"
    if kind == "int":
        return f"{value:,.0f}"
    if kind == "pct1":
        return f"{value * 100:.1f}%"
    if kind == "pct2":
        return f"{value * 100:.2f}%"
    return f"{value:.2f}x"


def signed(value: float) -> str:
    if value is None or not np.isfinite(value):
        return "–"
    return f"{'+' if value >= 0 else '−'}{abs(value) * 100:.1f}%"


def chip(status: str) -> str:
    cls = STATUS_CLASS[status]
    return (f'<span class="chip {cls}"><svg viewBox="0 0 16 16" aria-hidden="true">{ICON[cls]}</svg>'
            f'{escape(status)}</span>')


def _spark(values: list[float]) -> str:
    vals = [v for v in values if np.isfinite(v)]
    if len(vals) < 2:
        return ""
    w, h, pad = 120, 28, 3
    lo, hi = min(vals), max(vals)
    span = hi - lo or 1
    pts = [(pad + i * (w - 2 * pad) / (len(values) - 1), h - pad - (v - lo) / span * (h - 2 * pad))
           for i, v in enumerate(values) if np.isfinite(v)]
    path = " ".join(f"{'M' if i == 0 else 'L'}{x:.1f},{y:.1f}" for i, (x, y) in enumerate(pts))
    x, y = pts[-1]
    return (f'<svg class="spark" viewBox="0 0 {w} {h}" aria-hidden="true"><path d="{path}" />'
            f'<circle cx="{x:.1f}" cy="{y:.1f}" r="3.5" /></svg>')


def _nice_ticks(lo: float, hi: float, n: int = 4) -> list[float]:
    span = hi - lo or abs(hi) or 1
    raw = span / n
    mag = 10 ** np.floor(np.log10(raw))
    step = min((s * mag for s in (1, 2, 2.5, 5, 10) if s * mag >= raw), default=raw)
    first = np.floor(lo / step) * step
    ticks = [first + i * step for i in range(n + 3)]
    return [t for t in ticks if t <= hi + step * 0.999][: n + 2]


def _tick_label(v: float, kind: str, step: float) -> str:
    if kind in ("money", "money2"):
        return f"€{v / 1000:,.0f}K" if abs(v) >= 1000 else f"€{v:,.0f}"
    if kind in ("pct1", "pct2"):
        return f"{v * 100:.{2 if step < 0.001 else 1}f}%"
    if kind == "int":
        return f"{v:,.0f}"
    return f"{v:.1f}x"


def _chart(chart_id: str, kpi_id: str, frame: pd.DataFrame, keys: list[str], unit: str) -> str:
    kpi = KPI_BY_ID[kpi_id]
    actual = [float(frame.at[k, "actual"]) for k in keys]
    target = [float(frame.at[k, "target"]) for k in keys]
    vals = [v for v in actual + target if np.isfinite(v)]
    lo, hi = min(vals), max(vals)
    pad_v = (hi - lo) * 0.15 or abs(hi) * 0.1
    ticks = _nice_ticks(lo - pad_v, hi + pad_v)
    y0, y1 = ticks[0], ticks[-1]
    step = ticks[1] - ticks[0]
    W, H, L, R, T, B = 640, 220, 58, 96, 14, 30
    pw, ph = W - L - R, H - T - B

    def x(i: int) -> float:
        return L + (i * pw / (len(keys) - 1) if len(keys) > 1 else pw / 2)

    def y(v: float) -> float:
        return T + ph - (v - y0) / (y1 - y0) * ph

    def path(values: list[float]) -> str:
        segs, pen = [], "M"
        for i, v in enumerate(values):
            if np.isfinite(v):
                segs.append(f"{pen}{x(i):.1f},{y(v):.1f}")
                pen = "L"
            else:
                pen = "M"
        return " ".join(segs)

    grid = "".join(f'<line class="grid" x1="{L}" x2="{L + pw}" y1="{y(t):.1f}" y2="{y(t):.1f}" />'
                   f'<text class="tick" x="{L - 8}" y="{y(t) + 4:.1f}" text-anchor="end">{_tick_label(t, kpi.fmt, step)}</text>'
                   for t in ticks)
    label_at = sorted({0, len(keys) // 2, len(keys) - 1})
    xlabels = "".join(f'<text class="tick" x="{x(i):.1f}" y="{H - 8}" text-anchor="middle">{escape(keys[i])}</text>'
                      for i in label_at)
    end_a, end_t = actual[-1], target[-1]
    ends = f'<text class="end strong" x="{x(len(keys) - 1) + 10:.1f}" y="{y(end_a) + 4:.1f}">{fmt(end_a, kpi.fmt)}</text>'
    if np.isfinite(end_t) and abs(y(end_t) - y(end_a)) > 15:  # skip the target label when the two would collide
        ends += f'<text class="end" x="{x(len(keys) - 1) + 10:.1f}" y="{y(end_t) + 4:.1f}">{fmt(end_t, kpi.fmt)}</text>'
    dot = f'<circle class="dot" cx="{x(len(keys) - 1):.1f}" cy="{y(end_a):.1f}" r="4.5" />'
    payload = json.dumps({"labels": keys, "fmt": kpi.fmt, "x": [round(x(i), 1) for i in range(len(keys))],
                          "series": [{"name": "Actual", "values": actual}, {"name": "Target", "values": target}]},
                         allow_nan=True).replace("NaN", "null")
    rows = "".join(f"<tr><td>{escape(k)}</td><td>{fmt(a, kpi.fmt)}</td><td>{fmt(t, kpi.fmt)}</td></tr>"
                   for k, a, t in zip(keys, actual, target))
    return f"""
<figure class="chart" id="{chart_id}">
  <figcaption><span class="title">{escape(kpi.label)} against target, last {len(keys)} {unit}s</span>
    <span class="legend"><span class="key actual"></span>Actual<span class="key target"></span>Target</span></figcaption>
  <div class="plot">
    <svg viewBox="0 0 {W} {H}" role="img" aria-label="{escape(kpi.label)} against target over the last {len(keys)} {unit}s">
      {grid}{xlabels}
      <line class="axis" x1="{L}" x2="{L + pw}" y1="{T + ph}" y2="{T + ph}" />
      <path class="line target" d="{path(target)}" />
      <path class="line actual" d="{path(actual)}" />
      {dot}{ends}
      <line class="cross" x1="0" x2="0" y1="{T}" y2="{T + ph}" />
      <rect class="hit" x="{L - 10}" y="{T}" width="{pw + 20}" height="{ph}" tabindex="0" />
    </svg>
    <div class="tip" role="status"></div>
  </div>
  <script type="application/json">{payload}</script>
  <details><summary>Show as table</summary>
    <table class="mini"><thead><tr><th>{PERIOD_WORD.get(unit, unit).title()}</th><th>Actual</th><th>Target</th></tr></thead>
    <tbody>{rows}</tbody></table></details>
</figure>"""


def _panel(grain: str, key: str, data: PeriodData, results: dict[str, pd.DataFrame], actions: pd.DataFrame,
           cfg: Config) -> str:
    keys = list(data.table.index)
    pos = keys.index(key)
    lag = WINDOWS[grain]["lag"]
    start, end = data.table.loc[key, ["start", "end"]]
    statuses = [results[k.id].at[key, "status"] for k in KPIS if k.direction != "neutral"]
    counts = {s: statuses.count(s) for s in ("Off track", "Watch", "On track")}
    summary = " ".join(f'{chip(s)}<span class="count">{n}</span>' for s, n in counts.items())

    tiles = []
    for kid in TILES:
        k, f = KPI_BY_ID[kid], results[kid]
        r = f.loc[key]
        spark_keys = keys[max(0, pos - 11):pos + 1]
        good = (r["perf"] >= 0) if np.isfinite(r["perf"]) else True
        tiles.append(f"""
<div class="tile">
  <div class="label">{escape(k.label)}</div>
  <div class="valrow"><span class="value">{fmt(r['actual'], k.fmt)}</span>{_spark([float(f.at[s, 'actual']) for s in spark_keys])}</div>
  <div class="delta {'up' if good else 'down'}">{signed(r['perf'])} vs target {fmt(r['target'], k.fmt)}</div>
  <div class="foot">{chip(r['status'])}</div>
</div>""")

    sections = []
    chart_keys = keys[max(0, pos - CHART_PERIODS[grain] + 1):pos + 1]
    for section in SECTIONS:
        rows = []
        for k in [k for k in KPIS if k.section == section]:
            r = results[k.id].loc[key]
            ly = results[k.id]["actual"].iloc[pos - lag] if pos >= lag else np.nan
            band = r["band"] if np.isfinite(r["band"]) else DEFAULT_BAND
            swing = f"±{band * 50:.1f}%" if np.isfinite(r["perf"]) else "–"  # half the band
            rows.append(f"<tr><th scope='row'>{escape(k.label)}</th><td>{fmt(r['actual'], k.fmt)}</td>"
                        f"<td>{fmt(r['target'], k.fmt)}</td><td>{signed(r['perf'])}</td><td>{chip(r['status'])}</td>"
                        f"<td class='swing'>{swing}</td><td>{fmt(ly, k.fmt)}</td></tr>")
        acts = actions[(actions["grain"] == grain) & (actions["key"] == key) & (actions["section"] == section)]
        items = "".join(f"<li>{escape(t)}</li>" for t in acts["text"])
        chart = _chart(f"c-{grain}-{SECTIONS.index(section)}", SECTION_CHART[section], results[SECTION_CHART[section]],
                       chart_keys, grain)
        sections.append(f"""
<section class="card">
  <h2>{escape(section)}</h2>
  <div class="scroll"><table class="kpis">
    <thead><tr><th>KPI</th><th>Actual</th><th>Target</th><th>vs target</th><th>Status</th><th>Normal swing</th><th>Last year</th></tr></thead>
    <tbody>{''.join(rows)}</tbody></table></div>
  {chart}
  <h3>What to do</h3>
  <ul class="actions">{items}</ul>
</section>""")

    return f"""
<div class="panel" id="panel-{grain}" role="tabpanel" aria-labelledby="tab-{grain}"{'' if grain == 'week' else ' hidden'}>
  <header class="head">
    <h1>{GRAIN_LABEL[grain]} KPI report</h1>
    <p class="meta">{escape(cfg.brand)} · {PERIOD_WORD[grain]} {escape(key)} · {start:%d %b} – {end:%d %b %Y} ·
      synthetic data</p>
    <div class="summary">{summary}</div>
  </header>
  <div class="tiles">{''.join(tiles)}</div>
  {''.join(sections)}
</div>"""


def build_html(path: Path, cfg: Config, periods: dict[str, PeriodData], results: dict[str, dict],
               actions: pd.DataFrame, defaults: dict[str, str]) -> None:
    tabs = "".join(f'<button role="tab" id="tab-{g}" aria-controls="panel-{g}" aria-selected="{str(g == "week").lower()}">'
                   f'{GRAIN_LABEL[g]}</button>' for g in GRAINS)
    panels = "".join(_panel(g, defaults[g], periods[g], results[g], actions, cfg) for g in GRAINS)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(PAGE.replace("{{TITLE}}", f"{escape(cfg.brand)} KPI report")
                    .replace("{{TABS}}", tabs).replace("{{PANELS}}", panels), encoding="utf-8")


PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{{TITLE}}</title>
<style>
:root {
  color-scheme: light;
  --page: #f9f9f7; --surface: #fcfcfb; --ink: #0b0b0b; --ink-2: #52514e; --muted: #898781;
  --grid: #e1e0d9; --axis: #c3c2b7; --ring: rgba(11,11,11,0.10); --accent: #2a78d6; --target: #898781;
  --good: #0ca30c; --warn: #fab219; --bad: #d03b3b; --neutral: #898781;
  --good-tint: rgba(12,163,12,0.12); --warn-tint: rgba(250,178,25,0.20); --bad-tint: rgba(208,59,59,0.12);
  --neutral-tint: rgba(137,135,129,0.12); --up: #006300; --down: #b42323;
}
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    color-scheme: dark;
    --page: #0d0d0d; --surface: #1a1a19; --ink: #f0efec; --ink-2: #c3c2b7; --muted: #898781;
    --grid: #2c2c2a; --axis: #383835; --ring: rgba(255,255,255,0.10); --accent: #3987e5; --target: #898781;
    --good-tint: rgba(12,163,12,0.22); --warn-tint: rgba(250,178,25,0.22); --bad-tint: rgba(208,59,59,0.26);
    --neutral-tint: rgba(137,135,129,0.20); --up: #0ca30c; --down: #ec6b6b;
  }
}
:root[data-theme="dark"] {
  color-scheme: dark;
  --page: #0d0d0d; --surface: #1a1a19; --ink: #f0efec; --ink-2: #c3c2b7; --muted: #898781;
  --grid: #2c2c2a; --axis: #383835; --ring: rgba(255,255,255,0.10); --accent: #3987e5; --target: #898781;
  --good-tint: rgba(12,163,12,0.22); --warn-tint: rgba(250,178,25,0.22); --bad-tint: rgba(208,59,59,0.26);
  --neutral-tint: rgba(137,135,129,0.20); --up: #0ca30c; --down: #ec6b6b;
}
* { box-sizing: border-box; }
body { margin: 0; background: var(--page); color: var(--ink);
  font: 15px/1.5 system-ui, -apple-system, "Segoe UI", sans-serif; }
main { max-width: 1080px; margin: 0 auto; padding: 24px 16px 64px; }
nav[role="tablist"] { display: flex; gap: 4px; border-bottom: 1px solid var(--grid); margin-bottom: 20px; }
nav button { font: inherit; color: var(--ink-2); background: none; border: 0; padding: 10px 14px; cursor: pointer;
  border-bottom: 2px solid transparent; margin-bottom: -1px; }
nav button[aria-selected="true"] { color: var(--ink); border-bottom-color: var(--ink); font-weight: 600; }
nav button:focus-visible, .hit:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
h1 { font-size: 26px; line-height: 1.2; margin: 0 0 4px; font-weight: 650; }
.meta { color: var(--ink-2); margin: 0 0 12px; }
.summary { display: flex; flex-wrap: wrap; align-items: center; gap: 6px 4px; margin-bottom: 20px; }
.summary .count { font-weight: 600; margin-right: 12px; font-variant-numeric: tabular-nums; }
.chip { display: inline-flex; align-items: center; gap: 5px; padding: 2px 9px 2px 6px; border-radius: 999px;
  font-size: 13px; line-height: 20px; white-space: nowrap; color: var(--ink); }
.chip svg { width: 14px; height: 14px; fill: none; stroke-width: 2.2; stroke-linecap: round; stroke-linejoin: round; }
.chip.good { background: var(--good-tint); } .chip.good svg { stroke: var(--good); }
.chip.warn { background: var(--warn-tint); } .chip.warn svg { stroke: #9a6a00; }
.chip.bad { background: var(--bad-tint); } .chip.bad svg { stroke: var(--bad); }
.chip.neutral { background: var(--neutral-tint); } .chip.neutral svg { stroke: var(--neutral); }
:root[data-theme="dark"] .chip.warn svg { stroke: var(--warn); }
@media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) .chip.warn svg { stroke: var(--warn); } }
.tiles { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px; margin-bottom: 20px; }
@media (max-width: 520px) { .tiles { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
.tile, .card { background: var(--surface); border: 1px solid var(--ring); border-radius: 12px; }
.tile { padding: 14px 14px 12px; display: flex; flex-direction: column; gap: 2px; min-width: 0; }
.tile .label { color: var(--ink-2); font-size: 13px; }
.tile .value { font-size: 26px; font-weight: 600; line-height: 1.25; }
.tile .delta { font-size: 13px; color: var(--ink-2); }
.tile .delta.up::first-letter { color: var(--up); } .tile .delta.down::first-letter { color: var(--down); }
.tile .valrow { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.tile .foot { margin-top: 8px; }
.spark { width: 56px; height: 24px; flex: none; }
.spark path { fill: none; stroke: var(--muted); stroke-width: 1.5; }
.spark circle { fill: var(--accent); stroke: var(--surface); stroke-width: 2; }
.card { padding: 18px 20px 16px; margin-bottom: 16px; }
h2 { font-size: 18px; margin: 0 0 10px; font-weight: 650; }
h3 { font-size: 14px; margin: 14px 0 6px; color: var(--ink-2); font-weight: 600; }
.scroll { overflow-x: auto; }
table { border-collapse: collapse; width: 100%; font-variant-numeric: tabular-nums; }
.kpis th, .kpis td { padding: 7px 10px; border-bottom: 1px solid var(--grid); text-align: right; white-space: nowrap; }
.kpis th:first-child { text-align: left; font-weight: 500; }
.kpis td:nth-child(5), .kpis thead th:nth-child(5) { text-align: left; }
.kpis td.swing { color: var(--ink-2); }
.kpis thead th { color: var(--ink-2); font-weight: 500; font-size: 13px; }
.actions { margin: 0; padding-left: 20px; } .actions li { margin: 4px 0; }
.chart { margin: 14px 0 0; }
figcaption { display: flex; flex-wrap: wrap; justify-content: space-between; gap: 6px 16px; font-size: 13px;
  color: var(--ink-2); margin-bottom: 4px; }
figcaption .title { color: var(--ink); font-weight: 500; }
.legend { display: inline-flex; align-items: center; gap: 6px; }
.key { display: inline-block; width: 16px; height: 2px; border-radius: 1px; margin-left: 8px; }
.key.actual { background: var(--accent); } .key.target { background: var(--target); }
.plot { position: relative; }
.plot svg { width: 100%; height: auto; display: block; overflow: visible; }
.grid { stroke: var(--grid); stroke-width: 1; } .axis { stroke: var(--axis); stroke-width: 1; }
.tick { fill: var(--muted); font-size: 11px; font-variant-numeric: tabular-nums; }
.end { fill: var(--ink-2); font-size: 12px; } .end.strong { fill: var(--ink); font-weight: 600; }
.line { fill: none; stroke-width: 2; stroke-linejoin: round; stroke-linecap: round; }
.line.actual { stroke: var(--accent); } .line.target { stroke: var(--target); }
.dot { fill: var(--accent); stroke: var(--surface); stroke-width: 2; }
.cross { stroke: var(--axis); stroke-width: 1; visibility: hidden; }
.hit { fill: transparent; cursor: crosshair; }
.tip { position: absolute; pointer-events: none; visibility: hidden; background: var(--surface); color: var(--ink);
  border: 1px solid var(--ring); border-radius: 8px; padding: 6px 10px; font-size: 13px; white-space: nowrap;
  box-shadow: 0 4px 14px rgba(0,0,0,0.12); transform: translate(-50%, calc(-100% - 10px)); }
.tip .when { color: var(--ink-2); font-size: 12px; }
.tip .row { display: flex; align-items: center; gap: 8px; }
.tip .row b { font-variant-numeric: tabular-nums; }
.tip .row span.k { width: 12px; height: 2px; display: inline-block; }
details { margin-top: 6px; font-size: 13px; color: var(--ink-2); }
summary { cursor: pointer; }
.mini { margin-top: 6px; max-width: 360px; }
.mini th, .mini td { padding: 3px 8px; border-bottom: 1px solid var(--grid); text-align: right; }
.mini th:first-child, .mini td:first-child { text-align: left; }
footer { color: var(--muted); font-size: 13px; margin-top: 24px; }
@media (max-width: 560px) { h1 { font-size: 22px; } .card { padding: 14px 12px; } .tile .value { font-size: 22px; } }
</style>
</head>
<body>
<main>
<nav role="tablist" aria-label="Report period">{{TABS}}</nav>
{{PANELS}}
<footer>Targets come from the brand's own history: the same period last year scaled by current growth. Each KPI's
normal swing comes from its own past misses: a miss within it is on track, up to twice it is watch, beyond that is off
track. Built with Claude Code from raw store, ad and analytics exports.</footer>
</main>
<script>
(() => {
  const tabs = [...document.querySelectorAll('[role="tab"]')];
  tabs.forEach(t => t.addEventListener('click', () => {
    tabs.forEach(o => { o.setAttribute('aria-selected', String(o === t));
      document.getElementById(o.getAttribute('aria-controls')).hidden = o !== t; });
  }));
  const money = new Intl.NumberFormat('en-IE', { style: 'currency', currency: 'EUR', maximumFractionDigits: 0 });
  const money2 = new Intl.NumberFormat('en-IE', { style: 'currency', currency: 'EUR', minimumFractionDigits: 2 });
  const fmt = (v, kind) => {
    if (v === null || v === undefined) return '–';
    if (kind === 'money') return money.format(v);
    if (kind === 'money2') return money2.format(v);
    if (kind === 'int') return Math.round(v).toLocaleString('en-GB');
    if (kind === 'pct1') return (v * 100).toFixed(1) + '%';
    if (kind === 'pct2') return (v * 100).toFixed(2) + '%';
    return v.toFixed(2) + 'x';
  };
  document.querySelectorAll('figure.chart').forEach(fig => {
    const data = JSON.parse(fig.querySelector('script[type="application/json"]').textContent);
    const svg = fig.querySelector('svg'), hit = fig.querySelector('.hit'), cross = fig.querySelector('.cross');
    const tip = fig.querySelector('.tip');
    const colors = [getComputedStyle(fig).getPropertyValue('--accent'), getComputedStyle(fig).getPropertyValue('--target')];
    let index = data.labels.length - 1;
    const show = i => {
      index = i;
      const box = svg.getBoundingClientRect(), scale = box.width / svg.viewBox.baseVal.width;
      cross.setAttribute('x1', data.x[i]); cross.setAttribute('x2', data.x[i]);
      cross.style.visibility = 'visible';
      tip.replaceChildren();
      const when = document.createElement('div'); when.className = 'when'; when.textContent = data.labels[i];
      tip.append(when);
      data.series.forEach((s, j) => {
        const row = document.createElement('div'); row.className = 'row';
        const key = document.createElement('span'); key.className = 'k'; key.style.background = colors[j];
        const val = document.createElement('b'); val.textContent = fmt(s.values[i], data.fmt);
        const name = document.createElement('span'); name.textContent = s.name;
        row.append(key, val, name); tip.append(row);
      });
      tip.style.left = (data.x[i] * scale) + 'px'; tip.style.top = (14 * scale) + 'px';
      tip.style.visibility = 'visible';
    };
    const hide = () => { cross.style.visibility = 'hidden'; tip.style.visibility = 'hidden'; };
    const nearest = evt => {
      const box = svg.getBoundingClientRect(), x = (evt.clientX - box.left) * svg.viewBox.baseVal.width / box.width;
      let best = 0; data.x.forEach((px, i) => { if (Math.abs(px - x) < Math.abs(data.x[best] - x)) best = i; });
      return best;
    };
    hit.addEventListener('pointermove', e => show(nearest(e)));
    hit.addEventListener('pointerleave', hide);
    hit.addEventListener('focus', () => show(index));
    hit.addEventListener('blur', hide);
    hit.addEventListener('keydown', e => {
      if (e.key === 'ArrowLeft') { show(Math.max(0, index - 1)); e.preventDefault(); }
      if (e.key === 'ArrowRight') { show(Math.min(data.labels.length - 1, index + 1)); e.preventDefault(); }
    });
  });
})();
</script>
</body>
</html>
"""
