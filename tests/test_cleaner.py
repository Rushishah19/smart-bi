import io

import pandas as pd
import pytest

from core import cleaner


def _xlsx(rows):
    buf = io.BytesIO()
    pd.DataFrame(rows).to_excel(buf, header=False, index=False)
    buf.seek(0)
    return buf


def test_converts_currency_percent_and_dates():
    f = _xlsx([["Report title", None, None],
               ["Date", "Amount", "Rate"],
               ["2025-01-05", "$1,200.50", "45%"],
               ["06 Feb 2025", "(300)", "10%"],
               ["2025-03-01", "$50", "5%"]])
    df, log = cleaner.clean(f)
    assert list(df.columns) == ["Date", "Amount", "Rate"]
    assert df["Amount"].tolist() == [1200.5, -300.0, 50.0]
    assert df["Rate"].tolist() == pytest.approx([0.45, 0.10, 0.05])
    assert pd.api.types.is_datetime64_any_dtype(df["Date"])
    assert any("header on row 2" in line for line in log)


def test_placeholders_casing_and_duplicates():
    f = _xlsx([["Region", "Sales"],
               ["west", 10], ["West", 20], ["WEST", 30], ["East", 5],
               ["N/A", 1], ["East", 5]])
    df, log = cleaner.clean(f)
    assert set(df["Region"].dropna()) == {"West", "East"}
    assert df["Region"].isna().sum() == 1
    assert len(df) == 5  # one duplicate 'East, 5' removed
    assert any("duplicate" in line for line in log)


def test_csv_with_semicolons():
    data = b"Name;Score\nAna;10\nBo;20\nCy;30\n"
    df, log = cleaner.clean(io.BytesIO(data), is_csv=True)
    assert list(df.columns) == ["Name", "Score"]
    assert df["Score"].tolist() == [10, 20, 30]


def test_empty_file_raises():
    with pytest.raises(ValueError):
        cleaner.clean(io.BytesIO(b"\n\n"), is_csv=True)


def test_read_table_keeps_raw_values():
    f = _xlsx([["Amount"], ["$1,200"], ["$5"]])
    raw = cleaner.read_table(f)
    assert raw["Amount"].tolist() == ["$1,200", "$5"]


def test_sample_file(sample_clean):
    df, _ = sample_clean
    assert df.shape == (400, 8)
    assert not df.duplicated().any()
