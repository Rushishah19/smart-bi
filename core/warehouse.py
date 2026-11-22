"""Load step: turn the clean table into a star schema (fact + dimensions) and save it as SQLite."""
from __future__ import annotations

import os
import re
import sqlite3
import tempfile
from dataclasses import dataclass, field

import pandas as pd

from .profiler import ColumnProfile


@dataclass
class Table:
    name: str
    df: pd.DataFrame
    primary_key: str | None = None
    foreign_keys: dict[str, str] = field(default_factory=dict)  # column -> referenced table


def snake(name: str) -> str:
    s = re.sub(r"[^0-9a-zA-Z]+", "_", str(name)).strip("_").lower()
    return ("c_" + s if s[:1].isdigit() else s) or "col"


def _date_dim(dates: pd.Series) -> pd.DataFrame:
    d = pd.to_datetime(dates.dropna().dt.normalize().unique())
    d = pd.Series(sorted(d))
    return pd.DataFrame({
        "date_key": d.dt.strftime("%Y%m%d").astype(int),
        "date": d.dt.strftime("%Y-%m-%d"),
        "year": d.dt.year, "quarter": d.dt.quarter, "month": d.dt.month,
        "month_name": d.dt.strftime("%B"), "day": d.dt.day, "weekday": d.dt.strftime("%A"),
    })


def star_schema(df: pd.DataFrame, profiles: list[ColumnProfile], fact_name: str = "fact_data") -> list[Table]:
    """Dimension columns become dim_<name> tables, dates share one dim_date, measures/IDs/text stay in the fact."""
    roles = {p.name: p.role for p in profiles}
    fact = pd.DataFrame(index=df.index)
    fact["row_id"] = range(1, len(df) + 1)
    tables: list[Table] = []
    fks: dict[str, str] = {}

    date_cols = [c for c in df.columns if roles.get(c) == "date"]
    if date_cols:
        all_dates = pd.concat([pd.to_datetime(df[c], errors="coerce") for c in date_cols])
        if all_dates.notna().any():
            tables.append(Table("dim_date", _date_dim(all_dates), "date_key"))

    for c in df.columns:
        role, col = roles.get(c, "text"), snake(c)
        if role == "dimension":
            vals = sorted(df[c].dropna().astype(str).unique())
            key = f"{col}_key"
            dim = pd.DataFrame({key: range(1, len(vals) + 1), col: vals})
            tables.append(Table(f"dim_{col}", dim, key))
            fact[key] = df[c].astype(str).map(dict(zip(vals, dim[key]))).where(df[c].notna())
            fks[key] = f"dim_{col}"
        elif role == "date" and date_cols:
            key = f"{col}_key"
            d = pd.to_datetime(df[c], errors="coerce")
            fact[key] = d.dt.strftime("%Y%m%d").where(d.notna()).astype("Int64")
            fks[key] = "dim_date"
        else:
            fact[col] = df[c]

    tables.insert(0, Table(fact_name, fact.reset_index(drop=True), "row_id", fks))
    return tables


def _sql_type(s: pd.Series) -> str:
    if pd.api.types.is_bool_dtype(s):
        return "INTEGER"
    if pd.api.types.is_integer_dtype(s):
        return "INTEGER"
    if pd.api.types.is_float_dtype(s):
        return "INTEGER" if s.dropna().mod(1).eq(0).all() and s.name.endswith("_key") else "REAL"
    if pd.api.types.is_datetime64_any_dtype(s):
        return "TEXT"
    nn = s.dropna()
    if len(nn) and nn.map(lambda v: isinstance(v, (int, float)) and not isinstance(v, bool)).all():
        return "REAL"
    return "TEXT"


def ddl(tables: list[Table]) -> str:
    """CREATE TABLE statements, dimensions first so foreign keys resolve."""
    out = []
    for t in sorted(tables, key=lambda t: bool(t.foreign_keys)):
        cols = []
        for c in t.df.columns:
            line = f'    "{c}" {_sql_type(t.df[c])}'
            if c == t.primary_key:
                line += " PRIMARY KEY"
            cols.append(line)
        for c, ref in t.foreign_keys.items():
            ref_pk = next(x.primary_key for x in tables if x.name == ref)
            cols.append(f'    FOREIGN KEY ("{c}") REFERENCES "{ref}" ("{ref_pk}")')
        out.append(f'CREATE TABLE "{t.name}" (\n' + ",\n".join(cols) + "\n);")
    return "\n\n".join(out)


def _py(v):
    if v is None or v is pd.NA or v is pd.NaT:
        return None
    if isinstance(v, float) and pd.isna(v):
        return None
    if isinstance(v, pd.Timestamp):
        return v.strftime("%Y-%m-%d %H:%M:%S") if (v.hour or v.minute or v.second) else v.strftime("%Y-%m-%d")
    if hasattr(v, "item"):          # numpy scalar -> python
        return v.item()
    return v


def to_sqlite_bytes(tables: list[Table]) -> bytes:
    """Build the database in a temp file and return its bytes (for a download button)."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        con = sqlite3.connect(path)
        con.execute("PRAGMA foreign_keys = ON")
        con.executescript(ddl(tables))
        for t in sorted(tables, key=lambda t: bool(t.foreign_keys)):
            cols = ", ".join(f'"{c}"' for c in t.df.columns)
            marks = ", ".join("?" for _ in t.df.columns)
            rows = [tuple(_py(v) for v in r) for r in t.df.itertuples(index=False, name=None)]
            con.executemany(f'INSERT INTO "{t.name}" ({cols}) VALUES ({marks})', rows)
        con.commit()
        con.close()
        with open(path, "rb") as f:
            return f.read()
    finally:
        os.remove(path)


def example_query(tables: list[Table]) -> str:
    """A ready-to-run query joining the fact to its dimensions."""
    fact = tables[0]
    measure = next((c for c in fact.df.columns if c != "row_id" and c not in fact.foreign_keys
                    and _sql_type(fact.df[c]) == "REAL"), None)
    dim_fk = next((c for c, ref in fact.foreign_keys.items() if ref != "dim_date"), None)
    if not measure or not dim_fk:
        return f'SELECT * FROM "{fact.name}" LIMIT 10;'
    ref = fact.foreign_keys[dim_fk]
    label = dim_fk[:-4]
    return (f'SELECT d."{label}", SUM(f."{measure}") AS total_{measure}\n'
            f'FROM "{fact.name}" f\nJOIN "{ref}" d ON d."{dim_fk}" = f."{dim_fk}"\n'
            f'GROUP BY d."{label}"\nORDER BY total_{measure} DESC;')
