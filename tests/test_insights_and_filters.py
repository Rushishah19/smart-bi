import pandas as pd

from core import filters, insights, profiler


def test_findings_spot_leader_and_trend(sales):
    found = insights.key_findings(sales, profiler.profile(sales))
    texts = " ".join(f.text for f in found)
    assert "'West' leads Region" in texts
    assert any(f.kind == "trend" for f in found)
    assert [f.strength for f in found] == sorted((f.strength for f in found), reverse=True)


def test_findings_empty_table():
    assert insights.key_findings(pd.DataFrame(), []) == []


def test_percent_measures_shown_as_percent(sample_clean, sample_profiles):
    found = insights.key_findings(*[sample_clean[0], sample_profiles])
    discount = [f.text for f in found if "Discount" in f.text]
    assert all("%" in t for t in discount)


def test_filters(sales):
    spec = filters.FilterSpec("Order Date", ("2025-02-01", "2025-03-31"), {"Region": ["West"]})
    out = filters.apply(sales, spec)
    assert set(out["Region"]) == {"West"}
    assert out["Order Date"].min() >= pd.Timestamp("2025-02-01")
    assert out["Order Date"].max() < pd.Timestamp("2025-04-01")
    assert "Region: West" in filters.describe(spec)


def test_empty_filter_keeps_everything(sales):
    assert len(filters.apply(sales, filters.FilterSpec())) == len(sales)
