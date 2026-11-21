"""Step 1 (Extract + Clean): load an Excel sheet and clean it, logging every change."""
from __future__ import annotations

import re
import warnings

import numpy as np
import pandas as pd

NULL_TOKENS = {"", "na", "n/a", "nan", "null", "none", "-", "--", "?", "#n/a", "missing"}
CURRENCY_RE = re.compile(r"[\$€£₹,\s]")


def list_sheets(file) -> list[str]:
    return pd.ExcelFile(file).sheet_names


def _find_header_row(raw: pd.DataFrame, max_scan: int = 15) -> int:
    """Pick the first row (within the top rows) that looks like a header: mostly filled, mostly text."""
    best_row, best_score = 0, -1.0
    for i in range(min(max_scan, len(raw))):
        row = raw.iloc[i]
        filled = row.notna().mean()
        texty = row.dropna().map(lambda v: isinstance(v, str)).mean() if row.notna().any() else 0
        score = filled * 0.6 + texty * 0.4
        if score > best_score + 0.05:
            best_row, best_score = i, score
        if filled > 0.8 and texty > 0.8:
            return i
    return best_row


def _clean_col_name(name, idx: int) -> str:
    if name is None or (isinstance(name, float) and np.isnan(name)) or str(name).startswith("Unnamed"):
        return f"Column_{idx + 1}"
    return re.sub(r"\s+", " ", str(name)).strip()


def _dedupe(names: list[str]) -> list[str]:
    seen: dict[str, int] = {}
    out = []
    for n in names:
        if n in seen:
            seen[n] += 1
            out.append(f"{n}_{seen[n]}")
        else:
            seen[n] = 0
            out.append(n)
    return out


def _try_numeric(s: pd.Series) -> tuple[pd.Series | None, bool]:
    """Convert strings like '$1,200', '45%', '(300)' to numbers if >=90% of values parse."""
    txt = s.dropna().astype(str).str.strip()
    if txt.empty:
        return None, False
    is_pct = txt.str.endswith("%").mean() > 0.5
    cleaned = (
        txt.str.replace(CURRENCY_RE, "", regex=True)
        .str.replace("%", "", regex=False)
        .str.replace(r"^\((.*)\)$", r"-\1", regex=True)
    )
    num = pd.to_numeric(cleaned, errors="coerce")
    if num.notna().mean() < 0.9:
        return None, False
    full = pd.Series(np.nan, index=s.index, dtype="float64")
    full.loc[num.index] = num / 100 if is_pct else num
    return full, is_pct


def _try_datetime(s: pd.Series) -> pd.Series | None:
    txt = s.dropna().astype(str).str.strip()
    if txt.empty or txt.str.fullmatch(r"-?\d+(\.\d+)?").mean() > 0.5:
        return None  # plain numbers are not dates
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        dt = pd.to_datetime(txt, errors="coerce", format="mixed")
    if dt.notna().mean() < 0.9:
        return None
    full = pd.Series(pd.NaT, index=s.index, dtype="datetime64[ns]")
    full.loc[dt.index] = dt
    return full


def clean(file, sheet_name=0, is_csv: bool = False) -> tuple[pd.DataFrame, list[str]]:
    """Return (clean_df, log). `file` can be a path or a file-like object."""
    log: list[str] = []
    if is_csv:
        try:
            raw = pd.read_csv(file, header=None, encoding_errors="replace")
        except Exception:
            if hasattr(file, "seek"):
                file.seek(0)
            raw = pd.read_csv(file, header=None, sep=None, engine="python", encoding_errors="replace")
        log.append(f"Loaded {raw.shape[0]} rows × {raw.shape[1]} columns (CSV).")
    else:
        raw = pd.read_excel(file, sheet_name=sheet_name, header=None)
        log.append(f"Loaded {raw.shape[0]} rows × {raw.shape[1]} columns (raw).")

    # Drop fully-empty rows/cols before header detection
    raw = raw.dropna(how="all").dropna(axis=1, how="all").reset_index(drop=True)

    hdr = _find_header_row(raw)
    if hdr > 0:
        log.append(f"Detected header on row {hdr + 1}; skipped {hdr} title/blank rows above it.")
    cols = _dedupe([_clean_col_name(c, i) for i, c in enumerate(raw.iloc[hdr])])
    df = raw.iloc[hdr + 1:].copy()
    df.columns = cols
    df = df.reset_index(drop=True)

    # Normalise text cells and null tokens
    for c in df.columns:
        col = df[c]
        if col.dtype == object or pd.api.types.is_string_dtype(col):
            stripped = col.map(lambda v: re.sub(r"\s+", " ", v).strip() if isinstance(v, str) else v)
            mask = stripped.map(lambda v: isinstance(v, str) and v.lower() in NULL_TOKENS)
            if mask.any():
                log.append(f"'{c}': turned {int(mask.sum())} placeholder values (e.g. 'N/A', '-') into blanks.")
            df[c] = stripped.mask(mask, np.nan)

    # Drop empties again (header detection may leave some)
    before = df.shape
    df = df.dropna(how="all").dropna(axis=1, how="all")
    if df.shape != before:
        log.append(f"Removed {before[0] - df.shape[0]} empty rows and {before[1] - df.shape[1]} empty columns.")

    # Type inference
    for c in df.columns:
        col = df[c]
        if pd.api.types.is_numeric_dtype(col) and not pd.api.types.is_bool_dtype(col):
            df[c] = pd.to_numeric(col, errors="coerce")
            continue
        if pd.api.types.is_datetime64_any_dtype(col):
            continue
        # Mixed object column: datetime objects from Excel?
        if col.dropna().map(lambda v: isinstance(v, (pd.Timestamp, np.datetime64)) or hasattr(v, "year")).mean() > 0.9:
            df[c] = pd.to_datetime(col, errors="coerce")
            log.append(f"'{c}': converted to dates.")
            continue
        num, pct = _try_numeric(col)
        if num is not None:
            df[c] = num
            log.append(f"'{c}': converted text to numbers{' (percent → decimal)' if pct else ''}.")
            continue
        dt = _try_datetime(col)
        if dt is not None:
            df[c] = dt
            log.append(f"'{c}': converted text to dates.")
            continue
        # Standardise casing for low-cardinality text (e.g. 'east', 'EAST ' -> 'East')
        s = col.dropna().astype(str)
        if 0 < s.nunique() <= 50:
            lowered = s.str.lower().nunique()
            if lowered < s.nunique():
                canon = s.groupby(s.str.lower()).agg(lambda x: x.value_counts().idxmax())
                df[c] = col.map(lambda v: canon[str(v).lower()] if isinstance(v, str) else v)
                log.append(f"'{c}': merged {s.nunique() - lowered} values that differed only by capitalisation.")
        df[c] = df[c].astype(object).where(df[c].notna(), None)

    dups = int(df.duplicated().sum())
    if dups:
        df = df.drop_duplicates()
        log.append(f"Removed {dups} duplicate rows.")

    df = df.reset_index(drop=True)
    log.append(f"Clean result: {df.shape[0]} rows × {df.shape[1]} columns.")
    return df, log
