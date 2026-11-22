from core import profiler


def test_sample_roles(sample_profiles):
    roles = {p.name: p.role for p in sample_profiles}
    assert roles["Order ID"] == "id"
    assert roles["Order Date"] == "date"
    assert roles["Region"] == "dimension"
    assert roles["Revenue"] == "measure"


def test_sum_vs_average(sample_profiles):
    agg = {p.name: p.stats.get("agg") for p in sample_profiles if p.role == "measure"}
    assert agg["Revenue"] == "sum"
    assert agg["Discount"] == "mean"


def test_by_role(sales):
    profs = profiler.profile(sales)
    assert [p.name for p in profiler.by_role(profs, "measure")] == ["Units", "Revenue"]
