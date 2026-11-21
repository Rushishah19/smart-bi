"""Step 4 (Load): hand the clean data + chart plan to Power BI / Tableau."""
from __future__ import annotations

import io
import json

import pandas as pd

from .recommender import ChartRec

M_TYPES = {"measure": "type number", "date": "type date", "dimension": "type text", "id": "type text", "text": "type text"}


def excel_package(df: pd.DataFrame, recs: list[ChartRec], log: list[str]) -> bytes:
    """One workbook both tools can open: Data sheet + Chart Plan + Cleaning Log."""
    buf = io.BytesIO()
    plan = pd.DataFrame([{
        "Chart": r.title, "Power BI visual": r.powerbi_visual, "Tableau mark": r.tableau_mark,
        "X / Axis": r.x, "Y / Values": r.y or "(count of rows)", "Legend / Color": r.color,
        "Aggregation": r.agg, "Date grain": r.date_grain, "Why it matters": r.insight, "Score": r.score,
    } for r in recs])
    with pd.ExcelWriter(buf, engine="openpyxl") as xw:
        df.to_excel(xw, sheet_name="Data", index=False)
        plan.to_excel(xw, sheet_name="Chart Plan", index=False)
        pd.DataFrame({"Cleaning step": log}).to_excel(xw, sheet_name="Cleaning Log", index=False)
        for ws in xw.book.worksheets:
            for col in ws.columns:
                width = max(len(str(c.value or "")) for c in col[:200])
                ws.column_dimensions[col[0].column_letter].width = min(max(10, width + 2), 60)
            ws.freeze_panes = "A2"
    return buf.getvalue()


def powerquery_m(df: pd.DataFrame, roles: dict[str, str], csv_name: str = "clean_data.csv") -> str:
    """Power Query (M) script: Get Data > Blank Query > Advanced Editor, then paste."""
    types = ",\n        ".join(f'{{"{c}", {M_TYPES.get(roles.get(c, "text"), "type text")}}}' for c in df.columns)
    return f'''let
    // Change this path to where you saved {csv_name}
    Source = Csv.Document(File.Contents("C:\\\\Data\\\\{csv_name}"), [Delimiter=",", Encoding=65001, QuoteStyle=QuoteStyle.Csv]),
    Promoted = Table.PromoteHeaders(Source, [PromoteAllScalars=true]),
    Typed = Table.TransformColumnTypes(Promoted, {{
        {types}
    }}, "en-US")
in
    Typed
'''


def dax_measures(recs: list[ChartRec], table: str = "clean_data") -> str:
    seen, lines = set(), [f"// Paste each measure via Modeling > New measure (table: {table})"]
    for r in recs:
        col = r.color if r.chart == "heatmap" else r.y  # heatmap keeps its measure in `color`
        if col and r.agg in ("sum", "mean") and (col, r.agg) not in seen:
            seen.add((col, r.agg))
            fn = "SUM" if r.agg == "sum" else "AVERAGE"
            lines.append(f"{'Total' if fn == 'SUM' else 'Avg'} {col} = {fn}('{table}'[{col}])")
    lines.append(f"Row Count = COUNTROWS('{table}')")
    return "\n".join(lines)


def chart_plan_json(recs: list[ChartRec]) -> str:
    return json.dumps([r.to_dict() for r in recs], indent=2, default=str)


def csv_bytes(df: pd.DataFrame) -> bytes:
    return df.to_csv(index=False, date_format="%Y-%m-%d").encode("utf-8-sig")
