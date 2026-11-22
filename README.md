# Smart BI Builder

[![tests](https://github.com/Rushishah19/smart-bi/actions/workflows/tests.yml/badge.svg)](https://github.com/Rushishah19/smart-bi/actions/workflows/tests.yml)

Upload a messy Excel sheet or CSV file. The app cleans it, scores its data quality before and after, works out what each column holds, writes up the key findings, asks what you want to learn, ranks the best charts by how strong a pattern each one shows, and exports everything ready for **Power BI**, **Tableau** or **SQL**.

## Flow

```
 Excel (.xlsx / .xls / .xlsm) or CSV file
    │
 [1] EXTRACT   cleaner.clean()        read sheet or CSV, auto-detect header row
    │
 [2] CLEAN     cleaner.clean()        trim text, N/A → blank, "$1,200"/"45%" → numbers,
    │                                 text → dates, fix casing, drop empty rows/cols & duplicates
    │          quality.assess()       0–100 quality score before vs after (completeness,
    │                                 consistency, duplicates, stray spaces) + list of problems
    │
 [3] SCAN      profiler.profile()     tag each column: Measure / Category / Date / ID / Text
    │                                 + decide Sum vs Average (revenue adds up, discount % doesn't)
    │          quality.find_outliers() flag unusual values; user chooses whether to drop them
    │
 [4] FILTER    filters.apply()        sidebar date range + category filters for everything below
    │
 [5] FINDINGS  insights.key_findings() plain-English facts: leaders, latest change, best period,
    │                                 concentration, strongest relationship, data gaps
    │
 [6] TRANSFORM recommender.recommend() aggregate the data, score every possible chart 0–100
    │                                 (trend strength, gap between groups, correlation, skew)
    │
 [7] ASK       app.py                 "What do you want to learn?" options ordered by signal
    │                                 → user picks goals + numbers that matter
    │
 [8] PREVIEW   charts.build()         Plotly preview + plain-English insight for each chart
    │
 [9] LOAD      exporters.*            BI-ready .xlsx (Data + Chart Plan + Cleaning Log), CSV,
               warehouse.*            Power Query M script, DAX measures, chart-plan JSON,
                                      SQLite star schema (fact + dimension tables) + SQL
```

## Run it

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate    Mac/Linux: source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```
Then open http://localhost:8501 and upload `sample/messy_sales.xlsx` to try it.

## Run the tests

```bash
pip install -r requirements-dev.txt
pytest -q
```
The same tests run on GitHub Actions (Python 3.9 and 3.12) on every push.

## Project layout

| File | Role |
|---|---|
| `app.py` | Streamlit UI that walks the user through the steps |
| `core/cleaner.py` | Extract + clean, with a log of every change |
| `core/profiler.py` | Column type and role detection |
| `core/quality.py` | Data quality score and outlier detection |
| `core/filters.py` | Date range and category filters |
| `core/insights.py` | Key findings in plain English |
| `core/recommender.py` | Chart scoring, insights, Power BI / Tableau mapping |
| `core/charts.py` | Plotly previews |
| `core/exporters.py` | Excel package, CSV, M script, DAX, JSON |
| `core/warehouse.py` | Star schema + SQLite database export |
| `tests/` | pytest suite for every `core/` module |

## Using the output

**Power BI:** use Get Data → Excel and pick the `Data` sheet, or load the CSV with the M script provided. Add the DAX measures, then build each row of the `Chart Plan` sheet.
**Tableau:** use Connect → Microsoft Excel and drag in `Data`. Each Chart Plan row tells you what goes on Columns, Rows and Color, and which mark type to use.
**SQL:** open the `.db` file in any SQLite tool (DB Browser for SQLite, DBeaver, `sqlite3`). Measures live in `fact_data`; each category column has a `dim_<name>` table and dates link to `dim_date` (year, quarter, month, weekday). The app shows the `CREATE TABLE` statements and an example join query.

## Changelog

### v3.0
- **Data quality score**: 0–100 before vs after cleaning, broken down into completeness, consistency (numbers/dates stored as text, mixed date formats, inconsistent capitalisation), duplicates and stray spaces, with a list of every problem found
- **Outlier detection**: unusual values flagged per numeric column (IQR rule) with their normal range; the user decides whether to remove them
- **Key findings**: plain-English facts ranked by strength, e.g. which category leads and by how much, the latest month-on-month change, the best period, concentration and the strongest relationship
- **Filters**: sidebar date range and category filters that apply to findings and every chart; exports can include all rows or only the filtered ones
- **SQLite star schema export**: a fact table plus `dim_*` tables and a shared `dim_date`, with primary/foreign keys, the `CREATE TABLE` script and a ready-to-run example query
- **Tests + CI**: pytest suite for every `core/` module, run by GitHub Actions on every push
- **Fixes**: CSVs separated by semicolons, tabs or pipes are now split into columns correctly (in v2.0 they loaded as a single column); capitalisation ties now keep the "Title Case" spelling; empty files show a clear error; removed a Plotly deprecation warning shown under every chart

### v2.0
- **CSV support**: upload `.csv` files as well as `.xlsm`; the separator (comma, semicolon, tab) is detected automatically and unreadable characters are replaced instead of crashing
- **Error handling**: unreadable or corrupt files show a clear message instead of crashing the app
- **More reliable uploads**: the file is read into memory once and reused, which works better with Streamlit's caching
- **App config**: `.streamlit/config.toml` sets the port, headless mode, a 500 MB upload limit and turns off usage stats

### v1.0
- Full pipeline for Excel files (`.xlsx`, `.xls`): extract → clean → scan → score charts → ask → preview → export
- Automatic cleaning with a log of every change: header detection, text trimming, number/percent/date conversion, casing fixes, empty row/column and duplicate removal
- Column role detection (Measure / Category / Date / ID / Text) with Sum vs Average logic, editable by the user
- Chart scoring 0–100 by signal strength, with goals ranked by how strong their answers are
- Plotly previews with plain-English insights and Power BI / Tableau mapping
- Exports: BI-ready Excel package, clean CSV, chart-plan JSON, Power Query M script, DAX measures

## Roadmap

1. **LLM question step**: send the column profile (not the raw data) to an LLM API so users can type questions like "why did sales drop in Q3?"
2. **Native files**: generate a Tableau `.twb` (XML) and a Power BI `.pbip` project, so the charts are already built when the file opens
3. **PostgreSQL load**: write the star schema straight into a PostgreSQL database (SQLite export is done)
4. **Multi-sheet joins**: detect shared keys between sheets and merge them
5. **Deploy**: publish free on Streamlit Community Cloud
