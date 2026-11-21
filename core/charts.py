"""Preview a recommendation as a Plotly figure (same spec is exported for Power BI / Tableau)."""
from __future__ import annotations

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

from .recommender import ChartRec


def _agg(df, keys, rec: ChartRec) -> pd.DataFrame:
    if rec.agg == "count" or rec.y is None:
        return df.groupby(keys, dropna=True).size().reset_index(name="Count")
    return df.groupby(keys, dropna=True)[rec.y].agg(rec.agg).reset_index()


def build(df: pd.DataFrame, rec: ChartRec) -> go.Figure:
    y = rec.y if rec.y and rec.agg != "count" else "Count"

    if rec.chart == "kpi":
        val = df[rec.y].agg(rec.agg)
        fig = go.Figure(go.Indicator(mode="number", value=val, title={"text": rec.title}))
        fig.update_layout(height=180)
        return fig

    if rec.chart == "line":
        d = df.dropna(subset=[rec.x]).copy()
        d[rec.x] = d[rec.x].dt.to_period(rec.date_grain or "M").dt.start_time
        keys = [rec.x] + ([rec.color] if rec.color else [])
        fig = px.line(_agg(d, keys, rec), x=rec.x, y=y, color=rec.color, markers=True)
    elif rec.chart == "bar":
        g = _agg(df, [rec.x], rec).sort_values(y, ascending=True)
        fig = px.bar(g, x=y, y=rec.x, orientation="h")
    elif rec.chart == "stacked_bar":
        fig = px.bar(_agg(df, [rec.x, rec.color], rec), x=rec.x, y=y, color=rec.color)
    elif rec.chart == "donut":
        fig = px.pie(_agg(df, [rec.x], rec), names=rec.x, values=y, hole=0.5)
    elif rec.chart == "heatmap":
        pv = df.pivot_table(index=rec.y, columns=rec.x, values=rec.color, aggfunc="sum")
        fig = px.imshow(pv, text_auto=".2s", aspect="auto", color_continuous_scale="Blues")
    elif rec.chart == "scatter":
        fig = px.scatter(df, x=rec.x, y=rec.y, color=rec.color, trendline=None, opacity=0.7)
    elif rec.chart == "histogram":
        fig = px.histogram(df, x=rec.x, nbins=30)
    else:
        raise ValueError(rec.chart)

    fig.update_layout(title=rec.title, height=420, margin=dict(l=10, r=10, t=50, b=10))
    return fig
