"""Smart BI Builder — upload Excel/CSV → clean → score quality → scan → filter → findings → charts → export.

Run:  streamlit run app.py
"""
import io

import pandas as pd
import streamlit as st

from core import charts, cleaner, exporters, filters, insights, profiler, quality, recommender, warehouse

st.set_page_config(page_title="Smart BI Builder", page_icon="📊", layout="wide")
st.title("📊 Smart BI Builder")
st.caption("Upload a messy Excel or CSV file → get clean data, key findings and the best charts for Power BI or Tableau.")

# ---------- 1. EXTRACT ----------
st.header("1 · Upload")
up = st.file_uploader("Data file (Excel or CSV)", type=["xlsx", "xls", "xlsm", "csv"])
if not up:
    st.info("Upload an Excel (.xlsx / .xls) or CSV file to begin.")
    st.stop()

file_bytes = up.getvalue()
is_csv = up.name.lower().endswith(".csv")

if is_csv:
    sheet = "CSV"
else:
    try:
        sheets = cleaner.list_sheets(io.BytesIO(file_bytes))
        sheet = st.selectbox("Sheet", sheets) if len(sheets) > 1 else sheets[0]
    except Exception as e:
        st.error(f"Could not read Excel file sheets: {e}")
        st.stop()


@st.cache_data(show_spinner="Cleaning…")
def run_clean(data: bytes, sheet, is_csv: bool = False):
    return cleaner.clean(io.BytesIO(data), sheet, is_csv=is_csv)


def _safe_read_raw_table(data: bytes, sheet, is_csv: bool = False) -> pd.DataFrame:
    if hasattr(cleaner, "read_table"):
        return cleaner.read_table(io.BytesIO(data), sheet, is_csv=is_csv)
    if is_csv:
        raw = pd.read_csv(io.BytesIO(data), header=None, encoding_errors="replace")
    else:
        raw = pd.read_excel(io.BytesIO(data), sheet_name=sheet, header=None)
    raw = raw.dropna(how="all").dropna(axis=1, how="all").reset_index(drop=True)
    hdr = cleaner._find_header_row(raw) if hasattr(cleaner, "_find_header_row") else 0
    df = raw.iloc[hdr + 1:].copy()
    return df.reset_index(drop=True)


@st.cache_data(show_spinner="Scoring data quality…")
def run_quality(data: bytes, sheet, is_csv: bool, clean_df: pd.DataFrame):
    raw_df = _safe_read_raw_table(data, sheet, is_csv=is_csv)
    before = quality.assess(raw_df)
    after = quality.assess(clean_df)
    return before, after


try:
    df, log = run_clean(file_bytes, sheet, is_csv=is_csv)
except Exception as e:
    st.error(f"Failed to process and clean file: {e}")
    st.stop()
log = list(log)

# ---------- 2. CLEAN + QUALITY ----------
st.header("2 · Cleaning report")
try:
    before, after = run_quality(file_bytes, sheet, is_csv, df)
except Exception as e:
    before, after = None, None
    st.warning(f"Quality assessment could not be generated: {e}")

if before and after:
    q1, q2, q3 = st.columns([1, 1, 2])
    q1.metric("Quality before", f"{before.score:.0f}/100")
    q2.metric("Quality after", f"{after.score:.0f}/100", delta=f"{after.score - before.score:+.1f}")
    q3.dataframe(pd.DataFrame({"Before": before.checks, "After": after.checks}).rename(index=str.capitalize),
                 width="stretch", height=180)
    with st.expander("Problems found in the original file", expanded=False):
        for issue in before.issues or ["No problems found."]:
            st.write("• " + issue)
        if after.issues:
            st.markdown("**Still present after cleaning:**")
            for issue in after.issues:
                st.write("• " + issue)

c1, c2 = st.columns([1, 2])
with c1:
    for line in log:
        st.write("✅ " + line)
with c2:
    st.dataframe(df.head(50), width="stretch", height=300)

# ---------- 3. SCAN ----------
st.header("3 · What's in your data")
profiles = profiler.profile(df)
roles = {p.name: p.role for p in profiles}
role_label = {"measure": "🔢 Measure", "dimension": "🏷️ Category", "date": "📅 Date", "id": "🔑 ID", "text": "📝 Free text"}

with st.expander("Column roles (change any the scanner got wrong)", expanded=False):
    cols = st.columns(3)
    for i, p in enumerate(profiles):
        roles[p.name] = cols[i % 3].selectbox(
            f"{p.name}  ·  {p.unique} unique, {p.missing_pct}% blank",
            list(role_label), index=list(role_label).index(p.role),
            format_func=role_label.get, key=f"role_{p.name}")
for p in profiles:
    p.role = roles[p.name]

# Outliers: flag them and let the user decide whether to keep them
measures_all = [p.name for p in profiles if p.role == "measure"]
outliers = quality.find_outliers(df, measures_all)
if outliers:
    with st.expander(f"⚠️ Unusual values found in {len(outliers)} column(s)", expanded=False):
        st.dataframe(pd.DataFrame([{
            "Column": o.column, "Outliers": o.count,
            "Normal range": f"{o.low:,.2f} – {o.high:,.2f}",
            "Most extreme": ", ".join(f"{v:,.2f}" for v in o.examples)} for o in outliers]),
            width="stretch", hide_index=True)
        drop_cols = st.multiselect("Remove outlier rows for these columns (leave empty to keep everything)",
                                   [o.column for o in outliers])
        if drop_cols:
            mask = quality.outlier_mask(df, [o for o in outliers if o.column in drop_cols])
            df = df[~mask].reset_index(drop=True)
            log.append(f"Removed {int(mask.sum())} outlier row(s) in {', '.join(drop_cols)}.")
            st.caption(f"Removed {int(mask.sum())} row(s). Charts, findings and exports use the remaining {len(df):,}.")

m1, m2, m3, m4 = st.columns(4)
m1.metric("Rows", f"{len(df):,}")
m2.metric("Measures", len(profiler.by_role(profiles, "measure")))
m3.metric("Categories", len(profiler.by_role(profiles, "dimension")))
m4.metric("Date columns", len(profiler.by_role(profiles, "date")))

# ---------- FILTERS (sidebar) ----------
st.sidebar.header("🔎 Filters")
st.sidebar.caption("Apply to key findings and every chart.")
spec = filters.FilterSpec()
date_cols = [p.name for p in profiles if p.role == "date" and df[p.name].notna().any()]
if date_cols:
    spec.date_col = st.sidebar.selectbox("Date column", date_cols) if len(date_cols) > 1 else date_cols[0]
    lo, hi = df[spec.date_col].min().date(), df[spec.date_col].max().date()
    picked = st.sidebar.date_input(f"{spec.date_col} range", (lo, hi), min_value=lo, max_value=hi)
    if isinstance(picked, (tuple, list)) and len(picked) == 2 and (picked[0], picked[1]) != (lo, hi):
        spec.date_range = (picked[0], picked[1])
for p in profiles:
    if p.role == "dimension" and 2 <= df[p.name].nunique() <= 30:
        opts = sorted(df[p.name].dropna().unique(), key=str)
        spec.categories[p.name] = st.sidebar.multiselect(p.name, opts, placeholder="All")

view = filters.apply(df, spec)
active = filters.describe(spec)
if active:
    st.info(f"Filtered to {len(view):,} of {len(df):,} rows · {active}")
if view.empty:
    st.warning("No rows match the filters. Loosen them in the sidebar.")
    st.stop()

# Re-profile the filtered rows (keeping the user's role choices) so scores reflect what's on screen
view_profiles = profiler.profile(view)
for p in view_profiles:
    p.role = roles[p.name]

# ---------- 4. KEY FINDINGS ----------
st.header("4 · Key findings")
found = insights.key_findings(view, view_profiles)
if found:
    icon = {"trend": "📈", "leader": "🏆", "concentration": "🎯", "relationship": "🔗", "data": "⚠️"}
    cols = st.columns(2)
    for i, f in enumerate(found):
        cols[i % 2].markdown(f"{icon.get(f.kind, '•')} {f.text}")
else:
    st.caption("No strong patterns found. Try another filter or check the column roles.")

recs = recommender.recommend(view, view_profiles)
if not recs:
    st.warning("Couldn't find chartable columns. Check the column roles above (you need at least one Measure or Category).")
    st.stop()

# ---------- 5. ASK THE USER ----------
st.header("5 · What do you want to learn?")
ranked = recommender.suggested_goals(recs)
st.write("Based on the scan, these questions have the **strongest answers** in your data (best first):")
goal_opts = [g for g, _ in ranked]
goals = st.multiselect(
    "Pick one or more", goal_opts, default=goal_opts[:2],
    format_func=lambda g: f"{recommender.GOALS[g]}  —  signal {dict(ranked)[g]:.0f}/100")

measures = [p.name for p in view_profiles if p.role == "measure"]
focus = st.multiselect("Any specific numbers you care about? (optional)", measures)

pool = [r for r in recs if r.goal in goals and (not focus or r.y in focus or r.x in focus or r.y is None)]
top_n = st.slider("How many charts to suggest", 3, 15, 6)
pool = pool[:top_n]

# ---------- 6. RECOMMEND + PREVIEW ----------
st.header("6 · Recommended charts")
if not pool:
    st.info("No charts match that combination. Try another goal or clear the number filter.")
    st.stop()

chosen = []
for i, r in enumerate(pool):
    with st.container(border=True):
        h1, h2 = st.columns([4, 1])
        h1.subheader(f"{i + 1}. {r.title}")
        keep = h2.checkbox("Include", value=True, key=f"keep_{i}")
        st.markdown(f"**Why:** {r.insight}  \n"
                    f"**Power BI:** {r.powerbi_visual} · **Tableau:** {r.tableau_mark} · **Score:** {r.score:.0f}")
        try:
            st.plotly_chart(charts.build(view, r), key=f"fig_{i}")  # full width by default
        except Exception as e:  # keep the app alive if one chart fails
            st.error(f"Preview failed: {e}")
        if keep:
            chosen.append(r)

# ---------- 7. LOAD / EXPORT ----------
st.header("7 · Export for Power BI / Tableau")
use_filters = bool(active) and st.checkbox("Apply the sidebar filters to the exports", value=False,
                                           help="Off: export every cleaned row so you can filter inside Power BI / Tableau.")
out = view if use_filters else df
base = up.name.rsplit(".", 1)[0]
e1, e2, e3, e4 = st.columns(4)
e1.download_button("⬇️ Excel package (Data + Chart Plan + Log)",
                   exporters.excel_package(out, chosen, log), f"{base}_bi_ready.xlsx")
e2.download_button("⬇️ Clean CSV", exporters.csv_bytes(out), "clean_data.csv", "text/csv")
e3.download_button("⬇️ Chart plan (JSON)", exporters.chart_plan_json(chosen), f"{base}_chart_plan.json")

tables = warehouse.star_schema(out, profiles)
try:
    e4.download_button("⬇️ SQLite database (star schema)", warehouse.to_sqlite_bytes(tables),
                       f"{warehouse.snake(base)}.db", "application/vnd.sqlite3")
except Exception as e:
    e4.error(f"Database export failed: {e}")

with st.expander("SQL: star schema tables, CREATE statements and an example query"):
    st.dataframe(pd.DataFrame([{"Table": t.name, "Rows": len(t.df), "Primary key": t.primary_key,
                                "Links to": ", ".join(sorted(set(t.foreign_keys.values()))) or "—"} for t in tables]),
                 width="stretch", hide_index=True)
    st.code(warehouse.ddl(tables), language="sql")
    st.markdown("**Example query** (total of a measure per category):")
    st.code(warehouse.example_query(tables), language="sql")
with st.expander("Power BI: Power Query (M) + DAX measures"):
    st.code(exporters.powerquery_m(out, roles), language="powerquery")
    st.code(exporters.dax_measures(chosen), language="dax")
with st.expander("Tableau: how to use the export"):
    st.markdown("1. **Connect → Microsoft Excel**, open the `_bi_ready.xlsx`, drag the **Data** sheet to the canvas.\n"
                "2. Open the **Chart Plan** sheet as your build list: put *X / Axis* on Columns, *Y / Values* on Rows, "
                "*Legend / Color* on Color, and set the mark type shown.")
