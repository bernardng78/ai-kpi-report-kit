from pathlib import Path

import pandas as pd
import pytest

from kpi_kit import actions, clean, facts, synth, targets
from kpi_kit.__main__ import build
from kpi_kit.config import Config


@pytest.fixture(scope="session")
def cfg() -> Config:
    return Config()


@pytest.fixture(scope="session")
def raw(tmp_path_factory, cfg) -> Path:
    path = tmp_path_factory.mktemp("raw")
    synth.generate(cfg, path)
    return path


@pytest.fixture(scope="session")
def data(raw, cfg) -> clean.CleanData:
    return clean.load_all(raw, cfg)


@pytest.fixture(scope="session")
def periods(data, cfg) -> dict[str, facts.PeriodData]:
    return facts.build(data, cfg)


@pytest.fixture(scope="session")
def results(periods) -> dict[str, dict[str, pd.DataFrame]]:
    return {g: targets.compute(periods[g].table, g) for g in facts.GRAINS}


@pytest.fixture(scope="session")
def all_actions(periods, results) -> pd.DataFrame:
    return pd.concat([actions.build(results[g], periods[g], targets.targeted_periods(results[g]))
                      for g in facts.GRAINS], ignore_index=True)


@pytest.fixture(scope="session")
def outputs(raw, cfg, tmp_path_factory) -> Path:
    out = tmp_path_factory.mktemp("out")
    build(raw, out, cfg)
    return out
