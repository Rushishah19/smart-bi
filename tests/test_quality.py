import pandas as pd

from core import cleaner, quality
from conftest import SAMPLE


def test_cleaning_improves_score(sample_clean):
    before = quality.assess(cleaner.read_table(SAMPLE, "Sales"))
    after = quality.assess(sample_clean[0])
    assert after.score > before.score
    assert before.checks["consistency"] < 90
    assert any("numbers stored as text" in i for i in before.issues)


def test_perfect_table_scores_100():
    df = pd.DataFrame({"a": [1, 2, 3], "b": ["x", "y", "z"]})
    r = quality.assess(df)
    assert r.score == 100
    assert r.issues == []


def test_detects_blanks_duplicates_and_spaces():
    df = pd.DataFrame({"a": [1, 1, None, 4], "b": ["x", "x", " y ", "N/A"]})
    r = quality.assess(df)
    assert r.checks["completeness"] < 100
    assert r.checks["uniqueness"] < 100
    assert r.checks["tidiness"] < 100


def test_empty_table():
    assert quality.assess(pd.DataFrame()).score == 0


def test_outliers():
    df = pd.DataFrame({"v": [10, 11, 12, 10, 11, 12, 10, 11, 12, 10, 500]})
    found = quality.find_outliers(df, ["v"])
    assert len(found) == 1 and found[0].count == 1 and found[0].examples == [500.0]
    assert quality.outlier_mask(df, found).sum() == 1


def test_no_outliers_in_flat_column():
    df = pd.DataFrame({"v": [5] * 20})
    assert quality.find_outliers(df, ["v"]) == []
