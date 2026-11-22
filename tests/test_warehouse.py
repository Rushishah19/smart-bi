import sqlite3

from core import profiler, warehouse


def _db(tmp_path, tables):
    path = tmp_path / "test.db"
    path.write_bytes(warehouse.to_sqlite_bytes(tables))
    return sqlite3.connect(path)


def test_star_schema_shape(sample_clean, sample_profiles):
    tables = {t.name: t for t in warehouse.star_schema(sample_clean[0], sample_profiles)}
    assert {"fact_data", "dim_date", "dim_region", "dim_product_category", "dim_rep"} <= set(tables)
    fact = tables["fact_data"]
    assert len(fact.df) == len(sample_clean[0])
    assert fact.foreign_keys["region_key"] == "dim_region"
    assert "revenue" in fact.df.columns and "region" not in fact.df.columns


def test_sqlite_round_trip(tmp_path, sample_clean, sample_profiles):
    df = sample_clean[0]
    tables = warehouse.star_schema(df, sample_profiles)
    con = _db(tmp_path, tables)
    assert con.execute("PRAGMA foreign_key_check").fetchall() == []
    total = con.execute("SELECT SUM(revenue) FROM fact_data").fetchone()[0]
    assert abs(total - df["Revenue"].sum()) < 0.01
    rows = con.execute(warehouse.example_query(tables)).fetchall()
    by_region = df.groupby("Region")["Revenue"].sum()
    assert {r[0]: round(r[1], 2) for r in rows} == {k: round(v, 2) for k, v in by_region.items()}


def test_snake():
    assert warehouse.snake("Product Category") == "product_category"
    assert warehouse.snake("2024 Sales ($)") == "c_2024_sales"


def test_no_dimensions(tmp_path, sales):
    data = sales[["Units", "Revenue"]]
    tables = warehouse.star_schema(data, profiler.profile(data))
    assert len(tables) == 1
    con = _db(tmp_path, tables)
    assert con.execute("SELECT COUNT(*) FROM fact_data").fetchone()[0] == len(data)
