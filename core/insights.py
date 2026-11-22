"""Key findings: short, plain-English facts pulled from the data, strongest first."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .profiler import ColumnProfile, by_role
from .recommender import GRAIN_NAME, _agg, _fmt, _grain, _label


@dataclass
class Finding:
    kind: str        # trend | leader | concentration | relationship | data
    text: str
    strength: float  # 0-100, used for ranking


def _val(m: ColumnProfile, v: float) -> str:
    """Show 0-1 fractions (discount, margin) as percentages."""
    if 0 <= m.stats.get("min", -1) and m.stats.get("max", 2) <= 1:
        return f"{v:.0%}"
    return _fmt(v)


def _period_label(ts: pd.Timestamp, grain: str) -> str:
    return {"Y": f"{ts:%Y}", "M": f"{ts:%b %Y}", "W": f"week of {ts:%d %b %Y}", "D": f"{ts:%d %b %Y}"}[grain]


def _trends(df, dates, measures) -> list[Finding]:
    out = []
    for d in dates[:1]:
        grain = _grain(d.stats.get("span_days", 0))
        for m in measures[:3]:
            a = _agg(m)
            sub = df[[d.name, m.name]].dropna()
            ts = sub.groupby(sub[d.name].dt.to_period(grain).dt.start_time)[m.name].agg(a).sort_index()
            if len(ts) < 3:
                continue
            last, prev = ts.iloc[-1], ts.iloc[-2]
            if prev:
                chg = (last - prev) / abs(prev) * 100
                out.append(Finding("trend", f"{_label(a)} {m.name} was {_val(m, last)} in {_period_label(ts.index[-1], grain)}, "
                                            f"{'up' if chg >= 0 else 'down'} {abs(chg):.0f}% on the previous {GRAIN_NAME[grain]}.",
                                   min(95, 55 + abs(chg) / 2)))
            best = ts.idxmax()
            out.append(Finding("trend", f"Best {GRAIN_NAME[grain]} for {m.name}: {_period_label(best, grain)} "
                                        f"({_val(m, ts.max())}, {ts.max() / ts.mean():.1f}× the average {GRAIN_NAME[grain]}).",
                               min(85, 45 + 20 * (ts.max() / ts.mean() - 1))))
    return out


def _leaders(df, dims, measures) -> list[Finding]:
    out = []
    for m in measures[:3]:
        a = _agg(m)
        best = None
        for dim in dims:
            g = df.groupby(dim.name)[m.name].agg(a).dropna().sort_values(ascending=False)
            if len(g) < 2 or g.iloc[-1] <= 0:
                continue
            ratio = g.iloc[0] / g.iloc[-1]
            if best is None or ratio > best[0]:
                best = (ratio, dim, g)
        if best is None:
            continue
        ratio, dim, g = best
        share = f" ({g.iloc[0] / g.sum():.0%} of the total)" if a == "sum" else ""
        out.append(Finding("leader", f"'{g.index[0]}' leads {dim.name} on {_label(a).lower()} {m.name} with "
                                     f"{_val(m, g.iloc[0])}{share}, {ratio:.1f}× the lowest ('{g.index[-1]}').",
                           min(95, 50 + 15 * np.log2(max(ratio, 1)))))
    return out


def _concentration(df, dims, measures) -> list[Finding]:
    out = []
    sums = [m for m in measures if _agg(m) == "sum"][:2]
    for dim in [d for d in dims if d.unique >= 5]:
        for m in sums:
            g = df.groupby(dim.name)[m.name].sum().sort_values(ascending=False)
            g = g[g > 0]
            if len(g) < 5 or g.sum() == 0:
                continue
            top_n = max(1, int(round(len(g) * 0.2)))
            share = g.iloc[:top_n].sum() / g.sum()
            if share >= 0.35:
                out.append(Finding("concentration", f"The top {top_n} of {len(g)} {dim.name} values bring in "
                                                    f"{share:.0%} of total {m.name}.", 40 + 50 * share))
    return out


def _relationships(df, measures) -> list[Finding]:
    best = None
    for i, a in enumerate(measures):
        for b in measures[i + 1:]:
            sub = df[[a.name, b.name]].dropna()
            if len(sub) < 10 or sub[a.name].std() == 0 or sub[b.name].std() == 0:
                continue
            r = sub[a.name].corr(sub[b.name])
            if best is None or abs(r) > abs(best[0]):
                best = (r, a, b)
    if best is None or abs(best[0]) < 0.4:
        return []
    r, a, b = best
    word = "rises" if r > 0 else "falls"
    return [Finding("relationship", f"When {a.name} goes up, {b.name} usually {word} too (r = {r:.2f}).",
                    40 + 50 * abs(r))]


def _data_notes(df, profiles) -> list[Finding]:
    gaps = sorted((p for p in profiles if p.missing_pct >= 10), key=lambda p: -p.missing_pct)
    return [Finding("data", f"'{p.name}' is blank in {p.missing_pct:.0f}% of rows, so treat it with care.",
                    30 + p.missing_pct / 3) for p in gaps[:2]]


def key_findings(df: pd.DataFrame, profiles: list[ColumnProfile], limit: int = 8) -> list[Finding]:
    """Up to `limit` findings, strongest first, at most 3 of any one kind."""
    if df.empty:
        return []
    measures = by_role(profiles, "measure")
    dims = [d for d in by_role(profiles, "dimension") if 2 <= d.unique <= 30]
    dates = by_role(profiles, "date")
    found = (_trends(df, dates, measures) + _leaders(df, dims, measures) + _concentration(df, dims, measures)
             + _relationships(df, measures) + _data_notes(df, profiles))
    found.sort(key=lambda f: -f.strength)
    out, per_kind = [], {}
    for f in found:
        if per_kind.get(f.kind, 0) < 3:
            out.append(f)
            per_kind[f.kind] = per_kind.get(f.kind, 0) + 1
    return out[:limit]
