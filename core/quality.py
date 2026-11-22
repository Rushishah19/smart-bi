"""Data quality: a 0-100 score (before vs after cleaning) and outlier detection."""
from __future__ import annotations

import datetime as dt
import numbers
import re
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from .cleaner import NULL_TOKENS

# How much each check counts towards the overall score (sums to 1).
WEIGHTS = {"completeness": 0.4, "consistency": 0.3, "uniqueness": 0.2, "tidiness": 0.1}


@dataclass
class QualityReport:
    score: float                      # 0-100
    checks: dict[str, float]          # each check 0-100
    issues: list[str] = field(default_factory=list)


def _is_missing(v) -> bool:
    if v is None:
        return True
    if isinstance(v, float) and np.isnan(v):
        return True
    if v is pd.NaT:
        return True
    return isinstance(v, str) and v.strip().lower() in NULL_TOKENS


NUM_TEXT_RE = re.compile(r"^\(?-?[\$€£₹]?\s*-?[\d,]*\.?\d+\s*%?\)?$")
DATE_TEXT_RE = re.compile(r"^(\d{1,4}[-/.]\d{1,2}[-/.]\d{1,4}|\d{1,2}\s+[A-Za-z]{3,9}\.?\s+\d{2,4}|[A-Za-z]{3,9}\.?\s+\d{1,2},?\s+\d{2,4})$")


def _kind(v) -> str:
    """Type of one cell: number, date, number_text ('$1,200'), date_text ('22 Jun 2025') or text."""
    if isinstance(v, bool):
        return "text"
    if isinstance(v, numbers.Number):
        return "number"
    if isinstance(v, (pd.Timestamp, dt.date, np.datetime64)):
        return "date"
    s = str(v).strip()
    if NUM_TEXT_RE.match(s):
        return "number_text"
    if DATE_TEXT_RE.match(s):
        return "date_text"
    return "text"


def _shape(s: str) -> str:
    """Format pattern of a string: '22 Jun 2025' -> '99 Aaa 9999'."""
    return re.sub(r"[a-z]", "a", re.sub(r"[A-Z]", "A", re.sub(r"\d", "9", s)))


def _column_consistency(vals: pd.Series) -> tuple[float, list[str]]:
    """0-1 score for one column plus the problems found."""
    vals = vals.head(5000)
    kinds = vals.map(_kind).value_counts(normalize=True)
    main, share = kinds.index[0], float(kinds.iloc[0])
    score, problems = share, []
    if share < 0.98:
        problems.append("mixed types")
    if main in ("number_text", "date_text"):
        score *= 0.5
        problems.append("numbers stored as text" if main == "number_text" else "dates stored as text")
    if main == "date_text":
        shapes = vals.astype(str).str.strip().map(_shape).value_counts(normalize=True)
        if len(shapes) > 1:
            score *= 1 - 0.5 * (1 - float(shapes.iloc[0]))
            problems.append(f"{len(shapes)} different date formats")
    if main == "text":
        s = vals.astype(str).str.strip()
        if 0 < s.nunique() <= 50 and s.str.lower().nunique() < s.nunique():
            canon = s.groupby(s.str.lower()).transform(lambda x: x.value_counts().idxmax())
            off = float((s != canon).mean())
            score *= 1 - off
            problems.append(f"inconsistent capitalisation ({off:.0%} of values)")
    return score, problems


def assess(df: pd.DataFrame) -> QualityReport:
    """Score a table on completeness, type consistency, duplicate rows and stray whitespace."""
    if df.empty or df.shape[1] == 0:
        return QualityReport(0.0, {k: 0.0 for k in WEIGHTS}, ["The table is empty."])

    issues: list[str] = []
    cells = df.size
    missing_mask = df.apply(lambda col: col.map(_is_missing))
    missing = int(missing_mask.values.sum())
    completeness = 1 - missing / cells
    if missing:
        worst = missing_mask.mean().sort_values(ascending=False)
        worst = worst[worst > 0].head(3)
        issues.append(f"{missing:,} blank or placeholder cells ({missing / cells:.0%}); most in "
                      + ", ".join(f"'{c}' ({p:.0%})" for c, p in worst.items()) + ".")

    # Consistency: right type, one format, one spelling per value
    shares = []
    for c in df.columns:
        vals = df[c][~missing_mask[c]]
        if vals.empty:
            continue
        col_score, problems = _column_consistency(vals)
        shares.append(col_score)
        if problems:
            issues.append(f"'{c}': " + ", ".join(problems) + ".")
    consistency = float(np.mean(shares)) if shares else 1.0

    dups = int(df.astype(str).duplicated().sum())
    uniqueness = 1 - dups / max(len(df), 1)
    if dups:
        issues.append(f"{dups:,} duplicate row(s).")

    text = df.apply(lambda col: col.map(lambda v: isinstance(v, str) and v.strip() != ""))
    n_text = int(text.values.sum())
    messy = int(df.apply(lambda col: col.map(
        lambda v: isinstance(v, str) and (v != v.strip() or "  " in v))).values.sum())
    tidiness = 1 - messy / n_text if n_text else 1.0
    if messy:
        issues.append(f"{messy:,} text value(s) with extra spaces.")

    checks = {"completeness": completeness, "consistency": consistency,
              "uniqueness": uniqueness, "tidiness": tidiness}
    score = 100 * sum(WEIGHTS[k] * v for k, v in checks.items())
    return QualityReport(round(score, 1), {k: round(100 * v, 1) for k, v in checks.items()}, issues)


@dataclass
class OutlierInfo:
    column: str
    count: int
    low: float                        # values below this are outliers
    high: float                       # values above this are outliers
    examples: list[float]


def find_outliers(df: pd.DataFrame, columns: list[str]) -> list[OutlierInfo]:
    """IQR rule (1.5 × IQR beyond the quartiles) on each numeric column; most outliers first."""
    out = []
    for c in columns:
        s = pd.to_numeric(df[c], errors="coerce").dropna()
        if len(s) < 10:
            continue
        q1, q3 = s.quantile([0.25, 0.75])
        iqr = q3 - q1
        if iqr == 0:
            continue
        low, high = q1 - 1.5 * iqr, q3 + 1.5 * iqr
        bad = s[(s < low) | (s > high)]
        if len(bad):
            extremes = bad.reindex((bad - s.median()).abs().sort_values(ascending=False).index)
            out.append(OutlierInfo(c, len(bad), float(low), float(high), [float(v) for v in extremes.head(3)]))
    return sorted(out, key=lambda o: -o.count)


def outlier_mask(df: pd.DataFrame, infos: list[OutlierInfo]) -> pd.Series:
    """True for rows that are an outlier in any of the given columns."""
    mask = pd.Series(False, index=df.index)
    for o in infos:
        s = pd.to_numeric(df[o.column], errors="coerce")
        mask |= (s < o.low) | (s > o.high)
    return mask
