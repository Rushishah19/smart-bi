# Smart BI Builder

Upload a messy Excel sheet. The app cleans it, works out what each column holds, asks what you want to learn, ranks the best charts by how strong a pattern each one shows, and exports everything ready for **Power BI** or **Tableau**.

## Flow

```
 Excel file
    │
 [1] EXTRACT   cleaner.clean()        read sheet, auto-detect header row
    │
 [2] CLEAN     cleaner.clean()        trim text, N/A → blank, "$1,200"/"45%" → numbers,
    │                                 text → dates, fix casing, drop empty rows/cols & duplicates
    │
 [3] SCAN      profiler.profile()     tag each column: Measure / Category / Date / ID / Text
    │                                 + decide Sum vs Average (revenue adds up, discount % doesn't)
    │
 [4] TRANSFORM recommender.recommend() aggregate the data, score every possible chart 0–100
    │                                 (trend strength, gap between groups, correlation, skew)
    │
 [5] ASK       app.py                 "What do you want to learn?" options ordered by signal
    │                                 → user picks goals + numbers that matter
    │
 [6] PREVIEW   charts.build()         Plotly preview + plain-English insight for each chart
    │
 [7] LOAD      exporters.*            BI-ready .xlsx (Data + Chart Plan + Cleaning Log), CSV,
                                      Power Query M script, DAX measures, chart-plan JSON
```

## Run it

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate    Mac/Linux: source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```
Then open http://localhost:8501 and upload `sample/messy_sales.xlsx` to try it.

## Project layout

| File | Role |
|---|---|
| `app.py` | Streamlit UI that walks the user through the steps |
| `core/cleaner.py` | Extract + clean, with a log of every change |
| `core/profiler.py` | Column type and role detection |
| `core/recommender.py` | Chart scoring, insights, Power BI / Tableau mapping |
| `core/charts.py` | Plotly previews |
| `core/exporters.py` | Excel package, CSV, M script, DAX, JSON |

## Using the output

**Power BI:** use Get Data → Excel and pick the `Data` sheet, or load the CSV with the M script provided. Add the DAX measures, then build each row of the `Chart Plan` sheet.
**Tableau:** use Connect → Microsoft Excel and drag in `Data`. Each Chart Plan row tells you what goes on Columns, Rows and Color, and which mark type to use.

## Roadmap

1. **LLM question step**: send the column profile (not the raw data) to an LLM API so users can type questions like "why did sales drop in Q3?"
2. **Native files**: generate a Tableau `.twb` (XML) and a Power BI `.pbip` project, so the charts are already built when the file opens
3. **Database load**: write the cleaned data to SQLite/PostgreSQL as a star schema (fact + dimension tables)
4. **Multi-sheet joins**: detect shared keys between sheets and merge them
5. **Tests + deploy**: pytest on the `core/` modules, then deploy free on Streamlit Community Cloud
