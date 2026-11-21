"""Step 2 (Scan): classify every column so the recommender knows what it can chart."""
from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

ID_HINTS = ("id", "code", "number", "no", "#", "key", "sku", "phone", "zip", "postal")


@dataclass
class ColumnProfile:
    name: str
    role: str            # measure | dimension | date | id | text
    dtype: str
    missing_pct: float
    unique: int
    sample: list = field(default_factory=list)
    stats: dict = field(default_factory=dict)


def _looks_like_id(name: str, s: pd.Series) -> bool:
    n = name.lower()
    hinted = any(n == h or n.endswith(" " + h) or n.endswith("_" + h) or n.startswith(h + "_") for h in ID_HINTS)
    if hinted:
        return True
    s = s.dropna()
    if len(s) <= 20 or s.nunique() < 0.95 * len(s):
        return False
    if pd.api.types.is_numeric_dtype(s):  # unique integers packed into a tight range = row numbers
        return (s.max() - s.min()) <= 3 * len(s)
    return s.astype(str).str.len().mean() <= 20  # short unique codes, not sentences


AVG_HINTS = ("rate", "pct", "percent", "%", "discount", "price", "score", "rating", "avg", "average",
             "margin", "age", "salary", "wage", "ratio", "temperature", "satisfaction", "nps")


def _default_agg(name: str, s: pd.Series) -> str:
    """Amounts (revenue, units) add up; rates/prices/scores should be averaged."""
    n = name.lower()
    if any(h in n for h in AVG_HINTS):
        return "mean"
    if len(s) and s.min() >= 0 and s.max() <= 1 and (s % 1 != 0).any():
        return "mean"  # looks like a 0–1 fraction
    return "sum"


def profile(df: pd.DataFrame) -> list[ColumnProfile]:
    out = []
    n = max(len(df), 1)
    for c in df.columns:
        s = df[c]
        nn = s.dropna()
        uniq = int(nn.nunique())
        miss = round(100 * (1 - len(nn) / n), 1)
        sample = nn.astype(str).unique()[:4].tolist()
        stats: dict = {}

        if pd.api.types.is_datetime64_any_dtype(s):
            role = "date"
            if len(nn):
                stats = {"min": nn.min().date().isoformat(), "max": nn.max().date().isoformat(),
                         "span_days": int((nn.max() - nn.min()).days)}
        elif pd.api.types.is_numeric_dtype(s) and not pd.api.types.is_bool_dtype(s):
            is_int = (nn % 1 == 0).all() if len(nn) else False
            if is_int and _looks_like_id(c, nn):
                role = "id"
            elif uniq <= 12 and is_int and len(nn) > 30 and nn.min() >= 0 and nn.max() <= 12 and "year" not in c.lower():
                role = "dimension"   # e.g. rating 1-5, quarter 1-4
            else:
                role = "measure"
                stats = {"sum": float(nn.sum()), "mean": float(nn.mean()), "min": float(nn.min()),
                         "max": float(nn.max()), "std": float(nn.std()) if len(nn) > 1 else 0.0,
                         "agg": _default_agg(c, nn)}
        else:
            if uniq <= max(30, int(0.05 * n)) and uniq >= 1:
                role = "dimension"
                stats = {"top": nn.astype(str).value_counts().head(5).to_dict()}
            elif nn.astype(str).str.len().mean() <= 20 and _looks_like_id(c, nn):
                role = "id"
            else:
                role = "text"
        out.append(ColumnProfile(c, role, str(s.dtype), miss, uniq, sample, stats))
    return out


def by_role(profiles: list[ColumnProfile], role: str) -> list[ColumnProfile]:
    return [p for p in profiles if p.role == role]
