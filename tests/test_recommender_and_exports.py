import json

from core import charts, exporters, profiler, recommender


def test_recommend_sorted_and_scored(sales):
    recs = recommender.recommend(sales, profiler.profile(sales))
    assert recs
    assert [r.score for r in recs] == sorted((r.score for r in recs), reverse=True)
    assert all(0 <= r.score <= 99 for r in recs)
    assert {"trend", "compare"} <= {r.goal for r in recs}


def test_every_chart_builds(sales):
    recs = recommender.recommend(sales, profiler.profile(sales))
    for r in recs:
        charts.build(sales, r)


def test_exports(sales):
    recs = recommender.recommend(sales, profiler.profile(sales))[:5]
    assert exporters.excel_package(sales, recs, ["log"])[:2] == b"PK"  # xlsx is a zip
    assert len(json.loads(exporters.chart_plan_json(recs))) == 5
    assert "SUM('clean_data'[Revenue])" in exporters.dax_measures(recs)
