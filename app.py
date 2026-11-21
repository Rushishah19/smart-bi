"""Smart BI Builder — upload Excel → clean → scan → ask → recommend charts → export for Power BI / Tableau.

Run:  streamlit run app.py
"""
import io
import pandas as pd
import streamlit as st

from core import cleaner, profiler, recommender, charts, exporters

st.set_page_config(page_title="Smart BI Builder", page_icon="📊", layout="wide")
st.title("📊 Smart BI Builder")
st.caption("Upload a messy Excel sheet → get clean data and the best charts for Power BI or Tableau.")

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


try:
    df, log = run_clean(file_bytes, sheet, is_csv=is_csv)
except Exception as e:
    st.error(f"Failed to process and clean file: {e}")
    st.stop()

# ---------- 2. CLEAN ----------
st.header("2 · Cleaning report")
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

m1, m2, m3, m4 = st.columns(4)
m1.metric("Rows", f"{len(df):,}")
m2.metric("Measures", len(profiler.by_role(profiles, "measure")))
m3.metric("Categories", len(profiler.by_role(profiles, "dimension")))
m4.metric("Date columns", len(profiler.by_role(profiles, "date")))

recs = recommender.recommend(df, profiles)
if not recs:
    st.warning("Couldn't find chartable columns. Check the column roles above (you need at least one Measure or Category).")
    st.stop()

# ---------- 4. ASK THE USER ----------
st.header("4 · What do you want to learn?")
ranked = recommender.suggested_goals(recs)
st.write("Based on the scan, these questions have the **strongest answers** in your data (best first):")
goal_opts = [g for g, _ in ranked]
goals = st.multiselect(
    "Pick one or more", goal_opts, default=goal_opts[:2],
    format_func=lambda g: f"{recommender.GOALS[g]}  —  signal {dict(ranked)[g]:.0f}/100")

measures = [p.name for p in profiles if p.role == "measure"]
focus = st.multiselect("Any specific numbers you care about? (optional)", measures)

pool = [r for r in recs if r.goal in goals and (not focus or r.y in focus or r.x in focus or r.y is None)]
top_n = st.slider("How many charts to suggest", 3, 15, 6)
pool = pool[:top_n]

# ---------- 5. RECOMMEND + PREVIEW ----------
st.header("5 · Recommended charts")
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
            st.plotly_chart(charts.build(df, r), width="stretch", key=f"fig_{i}")
        except Exception as e:  # keep the app alive if one chart fails
            st.error(f"Preview failed: {e}")
        if keep:
            chosen.append(r)

# ---------- 6. LOAD / EXPORT ----------
st.header("6 · Export for Power BI / Tableau")
base = up.name.rsplit(".", 1)[0]
e1, e2, e3 = st.columns(3)
e1.download_button("⬇️ Excel package (Data + Chart Plan + Log)",
                   exporters.excel_package(df, chosen, log), f"{base}_bi_ready.xlsx")
e2.download_button("⬇️ Clean CSV", exporters.csv_bytes(df), "clean_data.csv", "text/csv")
e3.download_button("⬇️ Chart plan (JSON)", exporters.chart_plan_json(chosen), f"{base}_chart_plan.json")

with st.expander("Power BI: Power Query (M) + DAX measures"):
    st.code(exporters.powerquery_m(df, roles), language="powerquery")
    st.code(exporters.dax_measures(chosen), language="dax")
with st.expander("Tableau: how to use the export"):
    st.markdown("1. **Connect → Microsoft Excel**, open the `_bi_ready.xlsx`, drag the **Data** sheet to the canvas.\n"
                "2. Open the **Chart Plan** sheet as your build list: put *X / Axis* on Columns, *Y / Values* on Rows, "
                "*Legend / Color* on Color, and set the mark type shown.")
