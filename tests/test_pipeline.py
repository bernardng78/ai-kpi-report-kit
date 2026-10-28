import numpy as np

from kpi_kit.config import GROWTH_MAX, GROWTH_MIN, WINDOWS
from kpi_kit.kpis import SECTIONS


def check(data, name):
    return next(result for _, c, result in data.checks.rows if c == name)


def test_cleaning_handles_the_mess(data):
    assert "orders appear in both files" in check(data, "Orders in two exports")
    assert data.orders["Name"].is_unique
    assert not data.orders["email"].str.endswith("@demostore.test").any()
    assert "100.0%" in check(data, "Reconciles with orders")
    assert "Missing cost: KIT-LAYER" in [c for _, c, _ in data.checks.rows]
    assert data.ga4["date"].nunique() == 1092
    assert set(data.ads["platform"]) == {"meta", "google", "tiktok"}


def test_periods_are_complete(periods):
    week = periods["week"].table
    assert len(week) == 156
    assert week.index[0] == "2023-W44" and week.index[-1] == "2026-W43"
    assert (week["end"] - week["start"]).dt.days.eq(6).all()
    assert periods["month"].table.index[-1] == "2026-09"
    assert periods["quarter"].table.index[-1] == "2026-Q3"
    assert np.allclose(week["net_rev"], week["gross_rev"] - week["refunds"])


def test_customer_metrics_wait_for_enough_history(periods, cfg):
    week = periods["week"].table
    early = week["start"] < np.datetime64(cfg.customer_metrics_from)
    assert week.loc[early, "new_customers"].isna().all()
    assert week.loc[~early, "new_customers"].notna().all()


def test_net_revenue_target_matches_the_written_method(periods, results):
    """Re-derive one target and band by hand, exactly as the README describes them."""
    table = periods["week"].table
    w = WINDOWS["week"]
    i = table.index.get_loc("2026-W43")
    net = table["net_rev"].to_numpy()
    anchor = net[i - w["lag"] - w["anchor"]:i - w["lag"] + w["anchor"] + 1].mean()
    growth = net[i - w["trailing"]:i].sum() / net[i - w["lag"] - w["trailing"]:i - w["lag"]].sum()
    expected = anchor * min(GROWTH_MAX, max(GROWTH_MIN, growth))
    row = results["week"]["net_rev"].loc["2026-W43"]
    assert np.isclose(row["target"], expected)
    assert np.isclose(row["perf"], row["actual"] / expected - 1)
    perf = results["week"]["net_rev"]["perf"].to_numpy()[i - w["band"]:i]
    q1, q3 = np.quantile(perf, [0.25, 0.75])
    assert np.isclose(row["band"], q3 - q1)


def test_lower_is_better_flips_the_sign(results):
    row = results["week"]["ncac"].loc["2026-W43"]
    assert row["actual"] > row["target"] and row["perf"] < 0


def test_the_planted_story_is_caught(results, all_actions):
    week = {k: results["week"][k].loc["2026-W43", "status"] for k in ["cr", "ncac", "net_rev"]}
    assert week == {"cr": "Off track", "ncac": "Off track", "net_rev": "On track"}
    texts = " ".join(all_actions.query("grain == 'week' and key == '2026-W43'")["text"])
    assert "Mobile conversion fell" in texts and "2026-W41" in texts
    assert "from Meta prospecting" in texts
    month = " ".join(all_actions.query("grain == 'month' and key == '2026-09'")["text"])
    assert "Alpine Shell Jacket" in month


def test_every_section_ends_with_actions(results, all_actions):
    for grain, res in results.items():
        latest = res["net_rev"].dropna(subset=["target"]).index[-1]
        got = set(all_actions.query("grain == @grain and key == @latest")["section"])
        assert got == set(SECTIONS), grain
    assert all_actions.groupby(["grain", "key", "section"]).size().max() <= 3
