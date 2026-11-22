"""Filters that apply to every chart and finding."""
from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd


@dataclass
class FilterSpec:
    date_col: str | None = None
    date_range: tuple | None = None                            # (start, end), inclusive
    categories: dict[str, list] = field(default_factory=dict)  # column -> values to keep


def apply(df: pd.DataFrame, spec: FilterSpec) -> pd.DataFrame:
    mask = pd.Series(True, index=df.index)
    if spec.date_col and spec.date_range:
        start, end = (pd.Timestamp(v) for v in spec.date_range)
        d = df[spec.date_col]
        mask &= d.isna() | ((d >= start) & (d < end + pd.Timedelta(days=1)))
    for col, keep in spec.categories.items():
        if keep:
            mask &= df[col].isin(keep)
    return df[mask]


def describe(spec: FilterSpec) -> str:
    parts = []
    if spec.date_col and spec.date_range:
        a, b = (pd.Timestamp(v) for v in spec.date_range)
        parts.append(f"{spec.date_col} {a:%d %b %Y} – {b:%d %b %Y}")
    for col, keep in spec.categories.items():
        if keep:
            parts.append(f"{col}: " + ", ".join(map(str, keep[:3])) + ("…" if len(keep) > 3 else ""))
    return "; ".join(parts)
