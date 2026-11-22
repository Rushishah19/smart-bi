import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core import cleaner, profiler  # noqa: E402

SAMPLE = ROOT / "sample" / "messy_sales.xlsx"


@pytest.fixture(scope="session")
def sample_clean():
    df, log = cleaner.clean(SAMPLE, "Sales")
    return df, log


@pytest.fixture(scope="session")
def sample_profiles(sample_clean):
    return profiler.profile(sample_clean[0])


@pytest.fixture
def sales():
    """Small, predictable table: West clearly leads, revenue rises every month."""
    rng = np.random.default_rng(0)
    n = 120
    months = pd.date_range("2025-01-01", periods=6, freq="MS")
    region = np.array(["West", "East", "North", "South"])[np.arange(n) % 4]
    date = months[np.arange(n) % 6] + pd.to_timedelta(np.arange(n) % 20, unit="D")
    units = rng.integers(1, 20, n)
    boost = np.where(region == "West", 3.0, 1.0) * (1 + (np.arange(n) % 6) * 0.2)
    return pd.DataFrame({"Order Date": date, "Region": region, "Units": units,
                         "Revenue": (units * 100 * boost).round(2)})
