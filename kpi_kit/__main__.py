"""Command line.

    python -m kpi_kit demo                 generate the synthetic exports, then build the reports
    python -m kpi_kit build --raw DIR      build the reports from exports already in DIR
"""
from __future__ import annotations

import argparse
import time
from pathlib import Path

import pandas as pd

from . import actions, clean, facts, html_report, synth, targets, workbook
from .config import Config


def build(raw: Path, out: Path, cfg: Config) -> dict[str, str]:
    data = clean.load_all(raw, cfg)
    periods = facts.build(data, cfg)
    results = {g: targets.compute(periods[g].table, g) for g in facts.GRAINS}
    keys = {g: targets.targeted_periods(results[g]) for g in facts.GRAINS}
    acts = pd.concat([actions.build(results[g], periods[g], keys[g]) for g in facts.GRAINS], ignore_index=True)
    defaults = {g: keys[g][-1] for g in facts.GRAINS}  # the latest complete period of each grain
    workbook.build_workbook(out / "kpi-report.xlsx", cfg, periods, acts, data.checks, defaults)
    html_report.build_html(out / "kpi-report.html", cfg, periods, results, acts, defaults)
    return defaults


def main() -> None:
    parser = argparse.ArgumentParser(prog="kpi_kit", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    demo = sub.add_parser("demo", help="generate synthetic exports, then build")
    run = sub.add_parser("build", help="build from existing exports")
    for p in (demo, run):
        p.add_argument("--raw", type=Path, default=Path("data/raw"), help="folder of raw exports")
        p.add_argument("--out", type=Path, default=Path("output"), help="folder for the reports")
    args = parser.parse_args()

    cfg = Config()
    started = time.time()
    if args.command == "demo":
        counts = synth.generate(cfg, args.raw)
        print(f"Wrote {len(counts)} synthetic exports to {args.raw}/")
    defaults = build(args.raw, args.out, cfg)
    print(f"Built {args.out / 'kpi-report.xlsx'} and {args.out / 'kpi-report.html'} in {time.time() - started:.1f}s")
    print("Default periods: " + ", ".join(f"{g} {k}" for g, k in defaults.items()))


if __name__ == "__main__":
    main()
