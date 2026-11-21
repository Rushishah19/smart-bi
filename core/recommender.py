"""Step 3 (Transform + Recommend): score every sensible chart and explain why it's interesting.

Each recommendation carries a 0-100 score built from how much signal the data actually shows
(group spread, trend strength, correlation, skew), so the user is offered the *best* charts first.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from itertools import combinations

import numpy as np
import pandas as pd

from .profiler import ColumnProfile, by_role

# The questions we ask the user, mapped to the chart families that answer them.
GOALS = {
    "trend": "How things change over time",
    "compare": "Compare categories (which is biggest / smallest)",
    "composition": "What makes up the total (share / mix)",
    "relationship": "How two numbers relate to each other",
    "distribution": "How values are spread out (outliers, ranges)",
    "kpi": "Headline numbers (KPI cards)",
}


@dataclass
class ChartRec:
    goal: str
    chart: str            # line | bar | stacked_bar | donut | scatter | histogram | heatmap | kpi
    title: str
    x: str | None
    y: str | None
    color: str | None
    agg: str              # sum | mean | count | none
    score: float
    insight: str
    date_grain: str | None = None
    powerbi_visual: str = ""
    tableau_mark: str = ""

    def to_dict(self):
        return asdict(self)


PBI = {"line": "Line chart", "bar": "Clustered bar chart", "stacked_bar": "Stacked column chart",
       "donut": "Donut chart", "scatter": "Scatter chart", "histogram": "Column chart (binned axis)",
       "heatmap": "Matrix with conditional formatting", "kpi": "Card"}
TAB = {"line": "Line", "bar": "Bar", "stacked_bar": "Bar (Color = series)", "donut": "Pie",
       "scatter": "Circle", "histogram": "Bar on a bin field", "heatmap": "Square (highlight table)",
       "kpi": "Text (BAN)"}


def _fmt(v: float) -> str:
    a = abs(v)
    if a >= 1e9: return f"{v/1e9:.1f}B"
    if a >= 1e6: return f"{v/1e6:.1f}M"
    if a >= 1e3: return f"{v/1e3:.1f}K"
    return f"{v:,.2f}".rstrip("0").rstrip(".")


def _grain(span_days: int) -> str:
    if span_days > 3 * 365: return "Y"
    if span_days > 120: return "M"
    if span_days > 21: return "W"
    return "D"


GRAIN_NAME = {"Y": "year", "M": "month", "W": "week", "D": "day"}


def _agg(m: ColumnProfile) -> str:
    return m.stats.get("agg", "sum")


def _label(a: str) -> str:
    return "Total" if a == "sum" else "Average"


def _spread(df, dim, measure, a) -> float:
    g = df.groupby(dim)[measure].agg(a)
    return float(g.std() / abs(g.mean())) if len(g) > 1 and g.mean() else 0.0


def _rec(goal, chart, **kw) -> ChartRec:
    return ChartRec(goal=goal, chart=chart, powerbi_visual=PBI[chart], tableau_mark=TAB[chart], **kw)


def recommend(df: pd.DataFrame, profiles: list[ColumnProfile]) -> list[ChartRec]:
    measures = by_role(profiles, "measure")
    dims = [d for d in by_role(profiles, "dimension") if 2 <= d.unique <= 30]
    dates = by_role(profiles, "date")
    recs: list[ChartRec] = []

    # KPI cards
    for m in measures[:4]:
        a = _agg(m)
        total = df[m.name].agg(a)
        recs.append(_rec("kpi", "kpi", title=f"{_label(a)} {m.name}", x=None, y=m.name, color=None, agg=a,
                         score=55 + min(20, 5 * len(measures)), insight=f"{_label(a)} {m.name} is {_fmt(total)}."))

    # Trends over time
    for d in dates:
        grain = _grain(d.stats.get("span_days", 0))
        for m in measures:
            a = _agg(m)
            sub = df[[d.name, m.name]].dropna()
            ts = sub.groupby(sub[d.name].dt.to_period(grain).dt.start_time)[m.name].agg(a).sort_index()
            if len(ts) < 3:
                continue
            x = np.arange(len(ts))
            r = abs(np.corrcoef(x, ts.values)[0, 1]) if ts.std() > 0 else 0
            change = (ts.iloc[-1] - ts.iloc[0]) / abs(ts.iloc[0]) * 100 if ts.iloc[0] else 0
            direction = "up" if change > 0 else "down"
            peak = ts.idxmax()
            score = 70 + 25 * r
            recs.append(_rec("trend", "line", title=f"{_label(a)} {m.name} by {GRAIN_NAME[grain]}", x=d.name, y=m.name,
                             color=None, agg=a, date_grain=grain, score=score,
                             insight=f"{m.name} went {direction} {abs(change):.0f}% from first to last {GRAIN_NAME[grain]}; "
                                     f"peak was {peak.date()} ({_fmt(ts.max())})."))
            for k, dim in enumerate(sorted((x for x in dims if x.unique <= 8), key=lambda x: -_spread(df, x.name, m.name, a))):
                recs.append(_rec("trend", "line", title=f"{_label(a)} {m.name} by {GRAIN_NAME[grain]} split by {dim.name}",
                                 x=d.name, y=m.name, color=dim.name, agg=a, date_grain=grain,
                                 score=score - 8 - 6 * k, insight=f"Shows whether each {dim.name} follows the overall trend."))
        recs.append(_rec("trend", "line", title=f"Record count by {GRAIN_NAME[_grain(d.stats.get('span_days', 0))]}",
                         x=d.name, y=None, color=None, agg="count", date_grain=_grain(d.stats.get("span_days", 0)),
                         score=55, insight="Volume of records over time (orders, tickets, events…)."))

    # Comparisons & composition
    for dim in dims:
        for m in measures:
            a = _agg(m)
            g = df.groupby(dim.name, dropna=True)[m.name].agg(a).sort_values(ascending=False)
            if len(g) < 2 or g.sum() == 0:
                continue
            share_top = g.iloc[0] / g.sum() * 100
            cv = g.std() / abs(g.mean()) if g.mean() else 0
            share_txt = f" ({share_top:.0f}% of total)" if a == "sum" else ""
            recs.append(_rec("compare", "bar", title=f"{_label(a)} {m.name} by {dim.name}", x=dim.name, y=m.name,
                             color=None, agg=a, score=min(95, 60 + 30 * min(cv, 1)),
                             insight=f"'{g.index[0]}' leads with {_fmt(g.iloc[0])}{share_txt}; "
                                     f"'{g.index[-1]}' is lowest at {_fmt(g.iloc[-1])}."))
            if a == "sum" and dim.unique <= 6 and (g >= 0).all():
                recs.append(_rec("composition", "donut", title=f"Share of {m.name} by {dim.name}", x=dim.name,
                                 y=m.name, color=None, agg="sum", score=55 + 25 * min(cv, 1),
                                 insight=f"'{g.index[0]}' makes up {share_top:.0f}% of total {m.name}."))
        recs.append(_rec("compare", "bar", title=f"Count of records by {dim.name}", x=dim.name, y=None, color=None,
                         agg="count", score=50, insight=f"Most common {dim.name}: '{list(dim.stats.get('top', {'-': 0}))[0]}'."))

    for d1, d2 in combinations([d for d in dims if d.unique <= 12], 2):
        for m in [x for x in measures if _agg(x) == "sum"][:2]:
            pv = df.pivot_table(index=d1.name, columns=d2.name, values=m.name, aggfunc="sum")
            spread = pv.stack().std() / abs(pv.stack().mean()) if pv.size and pv.stack().mean() else 0
            recs.append(_rec("composition", "stacked_bar", title=f"{m.name} by {d1.name} and {d2.name}", x=d1.name,
                             y=m.name, color=d2.name, agg="sum", score=55 + 20 * min(spread, 1),
                             insight=f"Breaks each {d1.name} down by {d2.name}."))
            recs.append(_rec("compare", "heatmap", title=f"{m.name}: {d1.name} × {d2.name}", x=d2.name, y=d1.name,
                             color=m.name, agg="sum", score=50 + 25 * min(spread, 1),
                             insight="Spot the hottest and coldest combinations at a glance."))

    # Relationships
    for a, b in combinations(measures, 2):
        sub = df[[a.name, b.name]].dropna()
        if len(sub) < 10 or sub[a.name].std() == 0 or sub[b.name].std() == 0:
            continue
        r = sub[a.name].corr(sub[b.name])
        strength = "strong" if abs(r) > 0.7 else "moderate" if abs(r) > 0.4 else "weak"
        recs.append(_rec("relationship", "scatter", title=f"{b.name} vs {a.name}", x=a.name, y=b.name,
                         color=dims[0].name if dims and dims[0].unique <= 8 else None, agg="none",
                         score=40 + 55 * abs(r),
                         insight=f"{strength.capitalize()} {'positive' if r > 0 else 'negative'} relationship (r = {r:.2f})."))

    # Distributions
    for m in measures:
        s = df[m.name].dropna()
        if len(s) < 10:
            continue
        skew = float(s.skew())
        q1, q3 = s.quantile([.25, .75])
        outliers = int(((s < q1 - 1.5 * (q3 - q1)) | (s > q3 + 1.5 * (q3 - q1))).sum())
        recs.append(_rec("distribution", "histogram", title=f"Distribution of {m.name}", x=m.name, y=None, color=None,
                         agg="count", score=45 + min(30, 10 * abs(skew)) + min(15, outliers),
                         insight=f"Median {_fmt(s.median())}, range {_fmt(s.min())}–{_fmt(s.max())}; "
                                 f"{outliers} outlier(s){', right-skewed' if skew > 1 else ', left-skewed' if skew < -1 else ''}."))

    recs.sort(key=lambda r: r.score, reverse=True)
    for r in recs:
        r.score = round(min(r.score, 99), 0)
    return recs


def suggested_goals(recs: list[ChartRec]) -> list[tuple[str, float]]:
    """Rank the questions to ask the user by how strong the best chart for each goal is."""
    best: dict[str, float] = {}
    for r in recs:
        best[r.goal] = max(best.get(r.goal, 0), r.score)
    return sorted(best.items(), key=lambda kv: kv[1], reverse=True)
