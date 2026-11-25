import os
import pandas as pd
from pathlib import Path

import paths


REQUIRED_COLUMNS = [
    '$Particulars', '$Led_Parent', '$Led_Group', '$Led_BaseGroup',
    '$Party_LedName', '$Led_PAN',
    'ExpenseAmount', 'TDSAmount', 'TDS_Deposited', 'Difference in TDS'
]

COLUMN_RENAME = {
    '$Particulars'     : 'Expense Head',
    '$Led_Parent'      : 'Ledger Parent',
    '$Led_Group'       : 'Ledger Group',
    '$Led_BaseGroup'   : 'Base Group',
    '$Party_LedName'   : 'Party Name',
    '$Led_PAN'         : 'PAN',
    'ExpenseAmount'    : 'Expense Amount',
    'TDSAmount'        : 'TDS Books',
    'TDS_Deposited'    : 'TDS Winman',
    'Difference in TDS': 'Difference'
}


def get_analysis_files(company_name: str, fy: str) -> list:
    """
    Returns list of analysis Excel files for the company-year
    sorted by latest first.
    """
    analysis_dir = paths.analysis_dir(company_name, fy)
    if not analysis_dir.exists():
        return []
    files = sorted(
        analysis_dir.glob("TDS_&Expense_Analysis_*.xlsx"),
        reverse=True
    )
    return [f.name for f in files]


def delete_analysis_file(company_name: str, fy: str, file_name: str) -> bool:
    """Delete one analysis Excel run-file for the company-year. Returns True when a
    file was removed. `file_name` must be a bare name from get_analysis_files()."""
    name = os.path.basename(str(file_name or "").strip())
    if not name:
        return False
    fp = paths.analysis_dir(company_name, fy) / name
    if fp.exists():
        fp.unlink()
        return True
    return False


def load_analysis(company_name: str, fy: str, file_name: str) -> pd.DataFrame:
    """
    Loads Final_Merged_Report sheet from selected analysis file.
    Returns cleaned DataFrame.
    """
    file_path = paths.analysis_dir(company_name, fy) / file_name

    if not file_path.exists():
        raise FileNotFoundError(f"Analysis file not found: {file_path}")

    df = pd.read_excel(file_path, sheet_name="Final_Merged_Report")

    # Check required columns
    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"Missing columns in Final_Merged_Report: {missing}")

    # Keep only needed columns
    df = df[REQUIRED_COLUMNS].copy()

    # Rename columns
    df.rename(columns=COLUMN_RENAME, inplace=True)
    
    # Add PAN Status column
    df['PAN Status'] = df['PAN'].apply(
        lambda x: 'Missing' if pd.isna(x) or str(x).strip() in ['', 'Missing', 'nan']
        else 'Available'
    )

    # Add TDS Status column
    df['TDS Status'] = df['TDS Books'].apply(
        lambda x: 'TDS Deducted' if pd.to_numeric(x, errors='coerce') != 0
        else 'No TDS'
    )

    # Remove Primary Group — now using Ledger Group and Ledger Parent directly

    # Ensure numeric columns
    for col in ['Expense Amount', 'TDS Books', 'TDS Winman', 'Difference']:
        df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)
    # Books TDS is a credit (negative) in Tally -> show positive
    df['TDS Books'] = df['TDS Books'] * -1

    return df
    
def load_all(company_name: str, fy: str, file_name: str) -> dict:
    """
    Loads all three sheets from analysis file.
    Returns dict with keys: expense, purchase, sales
    """
    file_path = paths.analysis_dir(company_name, fy) / file_name

    if not file_path.exists():
        raise FileNotFoundError(f"Analysis file not found: {file_path}")

    result = {}

    
    # ── Expense & TDS ─────────────────────────────────────────────────────────
    try:
        df = pd.read_excel(file_path, sheet_name="Final_Merged_Report")
        missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
        if not missing:
            df = df[REQUIRED_COLUMNS].copy()
            df.rename(columns=COLUMN_RENAME, inplace=True)
            df['PAN Status'] = df['PAN'].apply(
                lambda x: 'Missing' if pd.isna(x) or
                str(x).strip() in ['', 'Missing', 'nan'] else 'Available'
            )
            df['TDS Status'] = df['TDS Books'].apply(
                lambda x: 'TDS Deducted' if pd.to_numeric(x, errors='coerce') != 0
                else 'No TDS'
            )
            for col in ['Expense Amount', 'TDS Books', 'TDS Winman', 'Difference']:
                df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)
            # Books TDS is a credit (negative) in Tally -> show positive
            df['TDS Books'] = df['TDS Books'] * -1
            result['expense'] = df
    except Exception as e:
        print(f"DEBUG expense error: {e}")
        result['expense'] = pd.DataFrame()

    # ── Purchase ──────────────────────────────────────────────────────────────
    try:
        pur = pd.read_excel(file_path, sheet_name="Purchase_Analysis")
        pur.columns = [str(c).strip() for c in pur.columns]
        for col in pur.select_dtypes(include='number').columns:
            pur[col] = pd.to_numeric(pur[col], errors='coerce').fillna(0)
        # Books TDS is a credit (negative) in Tally -> show positive
        if 'TDSAmount' in pur.columns:
            pur['TDSAmount'] = pur['TDSAmount'] * -1
        result['purchase'] = pur
    except Exception as e:
        print(f"DEBUG purchase error: {e}")
        result['purchase'] = pd.DataFrame()

    # ── Sales ─────────────────────────────────────────────────────────────────
    try:
        sal = pd.read_excel(file_path, sheet_name="Sales_Analysis")
        sal.columns = [str(c).strip() for c in sal.columns]
        for col in sal.select_dtypes(include='number').columns:
            sal[col] = pd.to_numeric(sal[col], errors='coerce').fillna(0)
        result['sales'] = sal
    except Exception as e:
        print(f"DEBUG sales error: {e}")
        result['sales'] = pd.DataFrame()

    return result


def get_scrutiny_files(company_name: str, fy: str) -> list:
    """Returns list of scrutiny Excel files sorted latest first."""
    analysis_dir = paths.analysis_dir(company_name, fy)
    if not analysis_dir.exists():
        return []
    files = sorted(analysis_dir.glob("Ledger_Scrutiny_Report*.xlsx"), reverse=True)
    return [f.name for f in files]


def load_scrutiny_report(company_name: str, fy: str, file_name: str) -> dict:
    """Loads all sheets from scrutiny Excel. Returns dict of sheet_name: DataFrame."""
    file_path = paths.analysis_dir(company_name, fy) / file_name
    if not file_path.exists():
        return {}
    try:
        xl = pd.ExcelFile(file_path)
        result = {}
        for sheet in xl.sheet_names:
            if sheet == 'Index':
                continue
            # Read each sheet independently so one short/empty sheet (e.g. a report
            # with only the home-button row) can't abort the whole report load.
            try:
                df = pd.read_excel(xl, sheet_name=sheet, header=1)
                df.columns = [str(c).strip() for c in df.columns]
            except Exception:
                df = pd.DataFrame()
            result[sheet] = df
        return result
    except Exception as e:
        print(f"Scrutiny load error: {e}")
        return {}


def get_master_ledgers(company_name: str, fy: str) -> list:
    """
    Returns balance sheet ledger names from RP_Ledgers.json (fast).
    Falls back to Conso_MasterData.csv if JSON not found.
    """
    import json
    json_path = paths.consolidated_dir(company_name, fy) / "RP_Ledgers.json"
    if json_path.exists():
        try:
            with open(json_path) as f:
                return json.load(f)
        except Exception:
            pass
    # Fallback
    INCLUDE_GROUPS = {
        'Sundry Debtors', 'Sundry Creditors',
        'Loans (Liability)', 'Loans & Advances (Asset)',
        'Capital Account', 'Investments',
        'Secured Loans', 'Unsecured Loans',
        'Bank Accounts', 'Bank OD Accounts'
    }
    path = paths.consolidated_dir(company_name, fy) / "Conso_MasterData.csv"
    if not path.exists():
        return []
    try:
        df = pd.read_csv(path)
        df.columns = [c.strip() for c in df.columns]
        filtered = df[df['$_PrimaryGroup'].isin(INCLUDE_GROUPS)]
        return sorted(filtered['$Name'].dropna().unique().tolist())
    except Exception:
        return []


def load_related_party_report(company_name: str, fy: str, file_name: str, selected_ledgers: tuple) -> pd.DataFrame:
    """
    Builds related party report — one row per PAN (or ledger if no PAN).
    Columns: Party, Ledger Names, Opening Balance, Closing Balance,
             Total Sales, Total Purchases, expense heads...
    """
    selected_ledgers = list(selected_ledgers)
    if not selected_ledgers:
        return pd.DataFrame()

    file_path = paths.analysis_dir(company_name, fy) / file_name

    # ── Master Data — Opening/Closing Balance ─────────────────────────────────
    master_path = paths.consolidated_dir(company_name, fy) / "Conso_MasterData.csv"
    master_df   = pd.read_csv(master_path)
    master_df.columns = [c.strip() for c in master_df.columns]
    master_df   = master_df[master_df['$Name'].isin(selected_ledgers)].copy()
    print(f"DEBUG master rows matched: {len(master_df)}")
    print(f"DEBUG selected: {selected_ledgers}")
    print(f"DEBUG master names sample: {master_df['$Name'].tolist()[:5]}")
    master_df['$OpeningBalance'] = pd.to_numeric(master_df['$OpeningBalance'], errors='coerce').fillna(0)
    master_df['$ClosingBalance'] = pd.to_numeric(master_df['$ClosingBalance'], errors='coerce').fillna(0)
    master_df['$PAN'] = master_df['$PAN'].astype(str).str.strip()

    # ── Sales ─────────────────────────────────────────────────────────────────
    try:
        sal_df = pd.read_excel(file_path, sheet_name="Sales_Analysis")
        sal_df.columns = [c.strip() for c in sal_df.columns]
        sal_df = sal_df[sal_df['PartyLedgerName'].isin(selected_ledgers)].copy()
        num_cols = [c for c in sal_df.columns if c not in ['PartyLedgerName', '$Led_PAN']]
        for col in num_cols:
            sal_df[col] = pd.to_numeric(sal_df[col], errors='coerce').fillna(0)
        sal_df['Total_Sales'] = sal_df[num_cols].sum(axis=1)
        sal_summary = sal_df.groupby('PartyLedgerName', as_index=False)['Total_Sales'].sum()
    except Exception:
        sal_summary = pd.DataFrame(columns=['PartyLedgerName', 'Total_Sales'])

    # ── Purchases ─────────────────────────────────────────────────────────────
    try:
        pur_df = pd.read_excel(file_path, sheet_name="Purchase_Analysis")
        pur_df.columns = [c.strip() for c in pur_df.columns]
        pur_df = pur_df[pur_df['PartyLedgerName'].isin(selected_ledgers)].copy()
        pur_df['PurchaseAmount'] = pd.to_numeric(pur_df['PurchaseAmount'], errors='coerce').fillna(0)
        pur_summary = pur_df.groupby('PartyLedgerName', as_index=False)['PurchaseAmount'].sum()
        pur_summary.rename(columns={'PurchaseAmount': 'Total_Purchases'}, inplace=True)
    except Exception:
        pur_summary = pd.DataFrame(columns=['PartyLedgerName', 'Total_Purchases'])

    # ── Expenses ──────────────────────────────────────────────────────────────
    try:
        exp_df = pd.read_excel(file_path, sheet_name="Final_Merged_Report")
        exp_df.columns = [c.strip() for c in exp_df.columns]
        exp_df = exp_df[exp_df['$Party_LedName'].isin(selected_ledgers)].copy()
        exp_df['$Amount'] = pd.to_numeric(exp_df['ExpenseAmount'], errors='coerce').fillna(0)
        exp_pivot = exp_df.pivot_table(
            index='$Party_LedName',
            columns='$Particulars',
            values='$Amount',
            aggfunc='sum',
            fill_value=0
        ).reset_index()
        exp_pivot.columns.name = None
        exp_pivot.rename(columns={'$Party_LedName': 'PartyLedgerName'}, inplace=True)
    except Exception:
        exp_pivot = pd.DataFrame(columns=['PartyLedgerName'])

    # ── Merge all ─────────────────────────────────────────────────────────────
    report = master_df[['$Name', '$PAN', '$OpeningBalance', '$ClosingBalance']].copy()
    report.rename(columns={'$Name': 'PartyLedgerName', '$PAN': 'PAN'}, inplace=True)

    report = report.merge(sal_summary,  on='PartyLedgerName', how='left')
    report = report.merge(pur_summary,  on='PartyLedgerName', how='left')
    report = report.merge(exp_pivot,    on='PartyLedgerName', how='left')

    for col in ['Total_Sales', 'Total_Purchases']:
        report[col] = pd.to_numeric(report[col], errors='coerce').fillna(0)

    # ── Group by PAN ──────────────────────────────────────────────────────────
    report['PAN'] = report['PAN'].fillna('').astype(str).str.strip()
    has_pan  = report[~report['PAN'].isin(['', 'nan', 'None', 'NaN'])].copy()
    no_pan   = report[report['PAN'].isin(['', 'nan', 'None', 'NaN'])].copy()
    print(f"DEBUG PAN value: '{report['PAN'].tolist()}'")
    print(f"DEBUG has_pan rows: {len(has_pan)}")
    print(f"DEBUG no_pan rows: {len(no_pan)}")

    num_cols = [c for c in report.columns if c not in ['PartyLedgerName', 'PAN']]

    pan_grouped = has_pan.groupby('PAN', as_index=False).agg(
        PartyLedgerName=('PartyLedgerName', lambda x: ' | '.join(sorted(set(x.dropna())))),
        **{col: (col, 'sum') for col in num_cols if col in has_pan.columns}
    )

    final = pd.concat([pan_grouped, no_pan], ignore_index=True)

    # Reorder columns
    fixed_cols = ['PAN', 'PartyLedgerName', '$OpeningBalance', '$ClosingBalance',
                  'Total_Sales', 'Total_Purchases']
    exp_cols   = [c for c in final.columns if c not in fixed_cols]
    final      = final[[c for c in fixed_cols if c in final.columns] + exp_cols]
    final      = final.fillna(0)

    return final
    
def load_purchase_grouped(company_name: str, fy: str, file_name: str) -> pd.DataFrame:
    """Loads Purchase_Analysis and regroups to Party+PAN level with 194Q check."""
    file_path = paths.analysis_dir(company_name, fy) / file_name
    df = pd.read_excel(file_path, sheet_name="Purchase_Analysis")
    df.columns = [str(c).strip() for c in df.columns]
    for col in df.select_dtypes(include='number').columns:
        df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)

    df['$Led_PAN'] = df['$Led_PAN'].fillna('').astype(str).str.strip()
    grouped = df.groupby(['PartyLedgerName', '$Led_PAN'], as_index=False, dropna=False).agg(
        PurchaseAmount=('PurchaseAmount', 'sum'),
        TDSAmount=('TDSAmount', 'sum'),
        TDS_Ledger=('TDS Ledger', lambda x: ' | '.join(sorted(set(
            str(v).strip() for v in x if str(v).strip() not in ['', 'nan', 'None']
        ))))
    )

    # Load Winman
    try:
        winman = pd.read_excel(file_path, sheet_name="Winman_TDS_Register")
        winman.columns = [str(c).strip() for c in winman.columns]
        winman['PAN'] = winman['PAN'].astype(str).str.strip()
        winman['TDS_Deposited'] = pd.to_numeric(winman['TDS_Deposited'], errors='coerce').fillna(0)
        winman_grp = winman.groupby('PAN', as_index=False)['TDS_Deposited'].sum()
    except Exception:
        winman_grp = pd.DataFrame(columns=['PAN', 'TDS_Deposited'])

    grouped = grouped.merge(winman_grp, left_on='$Led_PAN', right_on='PAN', how='left')
    grouped['TDS_Deposited'] = pd.to_numeric(grouped['TDS_Deposited'], errors='coerce').fillna(0)
    grouped.drop(columns=['PAN'], errors='ignore', inplace=True)
    # Books TDS is a credit (negative) in Tally -> show positive
    grouped['TDSAmount'] = grouped['TDSAmount'] * -1

    return grouped


# ══════════════════════════════════════════════════════════════════════════════
# TDS Compliance — Report Builder (bucketed party-view Excel export)
# ══════════════════════════════════════════════════════════════════════════════
NOT_FOR_REPORT = "Not for report"
STANDALONE = "Standalone"
_MAX_ROWS_PER_SHEET = 500

# Party-view column order for each report sheet — Party Name leads (party view),
# Expected TDS sits right after Expense Amount. Remarks left blank for the CA.
_REPORT_COLS = ['Party Name', 'Expense Head', 'PAN', 'Expense Amount', 'Expected TDS',
                'TDS Books', 'TDS Winman', 'Difference', 'Remarks']
_REPORT_AMT_COLS = {'Expense Amount', 'TDS Books', 'TDS Winman', 'Difference', 'Expected TDS'}

# Same status palette as the on-screen TDS Compliance view.
_CLR_PAN = "FFF8E1"      # yellow  — PAN missing
_CLR_NOTDED = "FFEBEE"   # red     — TDS expected but not deducted
_CLR_WINMAN = "E1BEE7"   # purple  — TDS Books vs Winman (deposited) mismatch
_CLR_DIFF = "FFF3E0"     # orange  — TDS deducted but difference != 0
_CLR_OK = "E8F5E9"       # green   — all OK
_INR_FMT = ('[>=10000000]##\\,##\\,##\\,##0.00;'
            '[>=100000]##\\,##\\,##0.00;##,##0.00')


def list_expense_heads(all_data: dict) -> list:
    """Sorted unique Expense Head ledgers from the loaded analysis (for bucketing)."""
    df = (all_data or {}).get('expense')
    if df is None or df.empty or 'Expense Head' not in df.columns:
        return []
    return sorted({str(h).strip() for h in df['Expense Head'].dropna()
                   if str(h).strip() not in ('', 'nan')})


# ── bucket allocation persistence (per company + FY) ─────────────────────────
def report_buckets_path(company_name: str, fy: str):
    return paths.config_path(company_name, fy, "tds_report_buckets.json")


def load_report_buckets(company_name: str, fy: str) -> dict:
    """{'assignments': {head: bucket_label}, 'groups': [name, ...]}.

    Configs written before groups were nameable carry an `n_groups` integer
    instead; groups_of() turns that into 'Group 1'..'Group N' so old files
    keep working untouched."""
    import json
    p = report_buckets_path(company_name, fy)
    if p.exists():
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(d, dict):
                b = {"assignments": dict(d.get("assignments", {}))}
                if d.get("groups") is not None:
                    b["groups"] = list(d.get("groups") or [])
                else:
                    b["n_groups"] = int(d.get("n_groups", 0) or 0)
                b["groups"] = groups_of(b)
                b.pop("n_groups", None)
                return b
        except Exception:
            pass
    return {"assignments": {}, "groups": []}


def save_report_buckets(company_name: str, fy: str, buckets: dict):
    paths.atomic_write_json(report_buckets_path(company_name, fy), {
        "assignments": dict((buckets or {}).get("assignments", {})),
        "groups": groups_of(buckets),
    })


def _clean(s) -> str:
    """Trim and collapse inner whitespace — CSV cells arrive padded.

    Blank cells reach us as NaN/NA (a fresh row in st.data_editor, or an Arrow
    string column), and str(nan) is 'nan' — which would otherwise become a
    group named "nan". Treat every null as empty."""
    try:
        if s is None or pd.isna(s):
            return ""
    except (TypeError, ValueError):
        pass
    return " ".join(str(s).split())


_RESERVED_LOWER = {STANDALONE.lower(), NOT_FOR_REPORT.lower()}


def groups_of(buckets: dict) -> list:
    """Ordered, de-duplicated group names for this allocation.

    Falls back to the legacy `n_groups` integer so allocations saved before
    groups could be named still load. Reserved bucket words and blanks are
    dropped; the first spelling of a name wins on a case-insensitive clash."""
    b = buckets or {}
    raw = b.get("groups")
    if raw is None:
        return [f"Group {i}" for i in range(1, int(b.get("n_groups", 0) or 0) + 1)]
    out, seen = [], set()
    for g in raw:
        g = _clean(g)
        low = g.lower()
        if not g or low in _RESERVED_LOWER or low in seen:
            continue
        seen.add(low)
        out.append(g)
    return out


def bucket_options(groups) -> list:
    """Dropdown options for the Bucket column."""
    return [STANDALONE, NOT_FOR_REPORT] + list(groups or [])


def compute_report_units(all_heads: list, buckets: dict) -> list:
    """Ordered list of report sheets to build:
       [{'title', 'ledgers': [heads], 'type': 'Group'|'Standalone'}].
       Groups first (in order, empty groups skipped), then each standalone head.
       Heads assigned to 'Not for report' (or unknown) are excluded."""
    assign = (buckets or {}).get("assignments", {}) or {}
    units = []
    for gl in groups_of(buckets):
        leds = [h for h in all_heads if assign.get(h) == gl]
        if leds:
            units.append({"title": gl, "ledgers": leds, "type": "Group"})
    for h in all_heads:
        b = assign.get(h, STANDALONE)
        if b == STANDALONE:                      # default + explicit standalone
            units.append({"title": h, "ledgers": [h], "type": "Standalone"})
    return units


# ── bucket list CSV round-trip (download → edit in Excel → upload) ───────────
# ── auto-suggested groups from ledger-name similarity ────────────────────────
# Words that sit on half the ledgers in an Indian trial balance and carry no
# grouping signal. Without dropping these, "…Charges" swallows the whole list.
_SUG_NOISE = {
    "charges", "charge", "chgs", "chg", "expenses", "expense", "exp", "expns",
    "fees", "fee", "fe",       # as generic as "charges" — Audit/Licence/Professional
    "ac", "account", "paid", "payable", "to", "for", "on", "of", "the",
    "and", "misc", "miscellaneous", "other", "others", "mfg", "manufacturing",
    "general", "sundry", "new", "old", "total", "cost", "amount", "value",
    "a", "c", "s",                      # leftovers from "A/c." and possessives
}
# Tax qualifiers. A ledger may legitimately START with one ("GST Expenses"),
# but trailing ones are variant markers — "… Non Gst", "… IGST", "… GST 5%" —
# and grouping on them puts Advertisement, Audit Fees and Bank Charges in one
# sheet. So these are dropped everywhere except the first position.
_SUG_QUALIFIER = {"gst", "igst", "cgst", "sgst", "utgst", "vat", "cess", "non"}
_SUG_MIN_STEM = 5        # below this length, stems must match exactly
_SUG_MIN_MEMBERS = 2     # a leading-phrase group needs at least this many heads
_SUG_MIN_FREE = 3        # a word found mid/end-name needs more evidence than a
                         # leading one, or incidental words pair up ledgers that
                         # merely mention "Branch" or "Purchase"
_SUG_MAX_LEAD = 3        # longest leading phrase considered as a group key


def _sug_tokens(name: str) -> list:
    """Significant lowercase word stems of a ledger name.

    Bracketed text goes first: in a Tally TB it is almost always a qualifier or
    an identifier — "( TN 30 BJ 1507 )", "( IGST Purchase )" — never the
    grouping signal, and its fragments otherwise dominate the clustering."""
    import re
    s = re.sub(r"[\(\[\{][^\)\]\}]*[\)\]\}]?", " ", str(name).lower())
    s = re.sub(r"[‘’']s\b", "", s)          # possessive: Staff's -> Staff
    s = re.sub(r"\ba\s*/\s*c\b\.?", " ", s)           # "A/c." is not two tokens
    s = s.replace("&", " and ")
    s = re.sub(r"[^a-z0-9\s]", " ", s)
    out = []
    for t in s.split():
        if len(t) > 3 and t.endswith("s"):
            t = t[:-1]
        # Single letters survive on purpose — "R & M" is a very common group.
        if not t or t in _SUG_NOISE or t.isdigit():
            continue
        if t in _SUG_QUALIFIER and out:      # only meaningful in first position
            continue
        out.append(t)
    return out


def _sug_same(a: str, b: str) -> bool:
    """Prefix-tolerant stem equality — electrical/electricity, staff/staffs."""
    if a == b:
        return True
    lo, hi = (a, b) if len(a) <= len(b) else (b, a)
    return len(lo) >= _SUG_MIN_STEM and hi.startswith(lo)


def _sug_prefix(members: list) -> str:
    """Longest leading text every member shares, trimmed to a word boundary.

    Rendered from a mixed-case member where there is one, so a lone SHOUTING
    ledger does not name the group."""
    import re
    ms = [" ".join(str(m).split()) for m in members]
    if len(ms) < 2:
        return ""
    src = next((m for m in ms if not m.isupper()), ms[0])
    n = len(src)
    for m in ms:
        i = 0
        while i < min(n, len(m)) and src[i].lower() == m[i].lower():
            i += 1
        n = i
        if not n:
            return ""
    lead = src[:n]
    if n < len(src) and not src[n].isspace():     # back off to a whole word
        lead = lead[:lead.rfind(" ")] if " " in lead else ""
    return re.sub(r"[\s\-&,:/]+$", "", lead).strip()


def _sug_covers(text: str, key: tuple) -> bool:
    """Does this label actually contain every word the cluster was keyed on?"""
    ts = _sug_tokens(text)
    return all(any(_sug_same(t, stem) for t in ts) for stem in key)


def _sug_trim_tail(name: str) -> str:
    """Drop trailing filler from a ledger name so it reads as a group name:
    "Printing & Stationery Account" -> "Printing & Stationery"."""
    import re
    words = " ".join(str(name).split()).split(" ")
    while words:
        w = re.sub(r"[^a-z0-9]", "", words[-1].lower())
        if w and w not in _SUG_NOISE and w not in _SUG_QUALIFIER and not w.isdigit():
            break
        words.pop()
    return re.sub(r"[\s\-&,:/]+$", "", " ".join(words)).strip()


def _sug_label(key: tuple, members: list) -> str:
    """Name a cluster.

    Preference order: the literal text every member shares (keeps punctuation
    the stems threw away — "R & M", "Advertisement Expenses Account"); then the
    shortest member trimmed of trailing filler, when the shared text alone drops
    part of the name ("Printing" -> "Printing & Stationery"); then the shared
    words themselves, for names that only agree at the end ("Maintenance")."""
    import re
    from collections import defaultdict
    lead = _sug_prefix(members)
    if lead and _sug_covers(lead, key):
        return lead
    if lead:
        cand = _sug_trim_tail(min(members, key=len))
        if cand.lower().startswith(lead.lower()) and _sug_covers(cand, key):
            return cand
        if len(lead) >= 3:
            return lead
    words = []
    for stem in key:
        forms = defaultdict(int)
        for m in members:
            for w in re.sub(r"[^A-Za-z0-9\s&]", " ", str(m)).split():
                wl = w.lower()
                wl = wl[:-1] if len(wl) > 3 and wl.endswith("s") else wl
                if _sug_same(wl, stem):
                    forms[w] += 1
        words.append(max(forms, key=forms.get) if forms else stem.title())
    return " ".join(words)


def suggest_groups(all_heads: list) -> dict:
    """{head: suggested group name} for heads that cluster by name.

    Greedy set cover: the phrase covering the most unclaimed heads wins, takes
    them, and the search repeats on what is left — so a head lands in its
    largest sensible group and never in two. Heads that cluster with nothing
    are absent from the result and stay Standalone."""
    from collections import defaultdict
    heads = [h for h in (all_heads or []) if str(h).strip()]
    vocab = []

    def canon(tok):
        for v in vocab:
            if _sug_same(tok, v):
                return v
        vocab.append(tok)
        return tok

    toks = {h: [canon(t) for t in _sug_tokens(h)] for h in heads}
    lead_cand, free_cand = defaultdict(set), defaultdict(set)
    for h, ts in toks.items():
        for n in range(1, min(_SUG_MAX_LEAD, len(ts)) + 1):
            lead_cand[tuple(ts[:n])].add(h)     # anchored at the start
        for t in ts:
            free_cand[(t,)].add(h)              # anywhere in the name
        for i in range(len(ts) - 1):
            free_cand[(ts[i], ts[i + 1])].add(h)

    unclaimed, out, seen_labels = set(heads), {}, {}
    # Leading phrases first: in a Tally TB the name leads and the qualifiers
    # trail, so "Advertisement Expenses Account …" must beat a stray shared
    # word. Only then do free-position words run, which is what still finds
    # Building/Computer/Vehicle "Maintenance".
    for cand, floor in ((lead_cand, _SUG_MIN_MEMBERS), (free_cand, _SUG_MIN_FREE)):
        while True:
            best_key, best_live, best_score = None, None, None
            for key in sorted(cand):       # sorted keeps ties deterministic
                # a lone single letter is never a group ("M V Srinivasan" is not
                # kin to "R & M - Computers"); "R" + "M" together still is
                if len(key) == 1 and len(key[0]) < 2:
                    continue
                live = cand[key] & unclaimed
                if len(live) < floor:
                    continue
                score = (len(live), len(key))   # more heads, then longer phrase
                if best_score is None or score > best_score:
                    best_key, best_live, best_score = key, live, score
            if best_key is None:
                break
            label = _clean(_sug_label(best_key, sorted(best_live)))
            if label and label.lower() not in _RESERVED_LOWER:
                # reuse the spelling already chosen for this name
                label = seen_labels.setdefault(label.lower(), label)
                for h in best_live:
                    out[h] = label
            unclaimed -= best_live
    return out


def apply_suggestions(all_heads: list, buckets: dict):
    """Fill every head still on Standalone with its suggested group, creating
    the groups as needed. Manual choices and 'Not for report' exclusions are
    left untouched, so this is safe to press twice. -> (new_buckets, n_filled)"""
    sug = suggest_groups(all_heads)
    assign = dict((buckets or {}).get("assignments", {}) or {})
    groups = list(groups_of(buckets))
    by_lower = {g.lower(): g for g in groups}
    filled = 0
    for h in all_heads:
        if assign.get(h, STANDALONE) != STANDALONE:
            continue                      # never overwrite a deliberate choice
        g = _clean(sug.get(h))
        if not g or g.lower() in _RESERVED_LOWER:
            continue
        if g.lower() not in by_lower:
            by_lower[g.lower()] = g
            groups.append(g)
        assign[h] = by_lower[g.lower()]
        filled += 1
    return {"assignments": assign, "groups": groups}, filled


# ── bucket list CSV round-trip (download → edit in Excel → upload) ───────────
BUCKET_LIST_COLS = ["Expense Head", "Bucket"]        # required on upload
BUCKET_LIST_EXPORT_COLS = ["Expense Head", "Bucket", "Suggested"]


def bucket_list_csv_bytes(all_heads: list, buckets: dict) -> bytes:
    """Current allocation as a round-trippable CSV. utf-8-sig so Excel opens
    Indian ledger names without mangling them.

    Carries the auto-suggested group as a third column so the whole thing can
    be pasted onto Bucket in Excel; the parser ignores columns it does not
    need, so the file uploads back unchanged."""
    assign = (buckets or {}).get("assignments", {}) or {}
    valid = set(bucket_options(groups_of(buckets)))
    sug = suggest_groups(all_heads)
    rows = [{"Expense Head": h,
             "Bucket": (assign.get(h) if assign.get(h) in valid else STANDALONE),
             "Suggested": sug.get(h, "")}
            for h in all_heads]
    csv = pd.DataFrame(rows, columns=BUCKET_LIST_EXPORT_COLS).to_csv(index=False)
    return csv.encode("utf-8-sig")


def parse_bucket_list_csv(src, all_heads: list, buckets: dict):
    """Merge an uploaded bucket list into `buckets`; returns (new_buckets, stats).

    Any Bucket value that is not 'Standalone' or 'Not for report' is taken as a
    group name and created on the fly, so a group is made simply by typing the
    same name against several heads. Heads absent from the CSV keep whatever
    bucket they already had (merge, not replace)."""
    df = pd.read_csv(src, dtype=str).fillna("")
    cols = {str(c).strip().lower(): c for c in df.columns}
    missing = [c for c in BUCKET_LIST_COLS if c.lower() not in cols]
    if missing:
        raise ValueError(
            "CSV must have the columns " + ", ".join(BUCKET_LIST_COLS) +
            " — missing " + ", ".join(missing) + ".")
    head_col, buck_col = cols["expense head"], cols["bucket"]

    known = {_clean(h).lower(): h for h in all_heads}
    assign = dict((buckets or {}).get("assignments", {}) or {})
    groups = list(groups_of(buckets))
    by_lower = {g.lower(): g for g in groups}

    updated, unknown, new_groups, seen_heads = 0, [], [], set()
    for head_raw, buck_raw in zip(df[head_col], df[buck_col]):
        head_raw = _clean(head_raw)
        if not head_raw:
            continue
        head = known.get(head_raw.lower())
        if head is None:                     # renamed ledger, or another FY's list
            unknown.append(head_raw)
            continue
        seen_heads.add(head)
        val = _clean(buck_raw) or STANDALONE
        low = val.lower()
        if low == STANDALONE.lower():
            bucket = STANDALONE
        elif low == NOT_FOR_REPORT.lower():
            bucket = NOT_FOR_REPORT
        else:
            bucket = by_lower.get(low)
            if bucket is None:               # a new group, named in the CSV
                bucket = val
                by_lower[low] = val
                groups.append(val)
                new_groups.append(val)
        if assign.get(head, STANDALONE) != bucket:
            updated += 1
        assign[head] = bucket

    stats = {"rows": int(len(df)), "matched": len(seen_heads), "updated": updated,
             "new_groups": new_groups, "unknown": sorted(set(unknown))}
    return {"assignments": assign, "groups": groups}, stats


# ── Excel builder ────────────────────────────────────────────────────────────
def _expected_tds(head, pan, amount, tds_rules) -> object:
    """Row-level Expected TDS — mirrors the on-screen party-view logic."""
    import tds_rules_engine
    rule = (tds_rules or {}).get(str(head).strip())
    if not rule or not rule.get('section') or rule.get('type') == 'Unmapped':
        return ''
    section = rule.get('section')
    rate = rule.get('rate')
    typ = rule.get('type', 'TDS')
    if typ == 'NON-TDS':
        return 0.0
    if section == '192':
        return ''
    pan = str(pan or '')
    if section == '194C':
        rate = 0.01 if (len(pan) >= 4 and pan[3] == 'P') else 0.02
    amt = float(amount or 0)
    threshold = tds_rules_engine.get_flat_threshold(section)
    if threshold and amt <= threshold:
        return 'Below Threshold'
    if section == '194Q':
        excess = max(amt - 5000000, 0)
        return round(excess * rate, 2) if rate else 0.0
    return round(amt * rate, 2) if rate else 0.0


def _row_fill(tds_books, tds_winman, difference, expected, pan_status) -> str:
    """Status colour for one party row (same rules as the viewer, plus a distinct
    purple when TDS Books != TDS Winman/deposited)."""
    if pan_status == 'Missing':
        return _CLR_PAN
    try:
        tb = float(tds_books or 0)
    except Exception:
        tb = 0.0
    if tb == 0 and expected not in ('', None, 'Below Threshold', 'Unmapped'):
        try:
            if float(expected) > 0:
                return _CLR_NOTDED
        except Exception:
            pass
    try:
        tw = float(tds_winman or 0)
    except Exception:
        tw = 0.0
    if round(tb - tw, 2) != 0:
        return _CLR_WINMAN
    try:
        if tb > 0 and float(difference or 0) != 0:
            return _CLR_DIFF
    except Exception:
        pass
    return _CLR_OK


def _party_view(df, ledgers, tds_rules):
    """One row per (Expense Head, Party, PAN) for the given heads, amounts summed,
    Expected TDS computed per row, sorted by Party Name. Blank Remarks."""
    sub = df[df['Expense Head'].isin(ledgers)].copy()
    if sub.empty:
        return sub
    sub['PAN'] = sub['PAN'].fillna('').astype(str).str.strip()
    g = sub.groupby(['Expense Head', 'Party Name', 'PAN'], as_index=False, dropna=False).agg(
        **{'Expense Amount': ('Expense Amount', 'sum'),
           'TDS Books': ('TDS Books', 'sum'),
           'TDS Winman': ('TDS Winman', 'sum'),
           'Difference': ('Difference', 'sum')})
    # TDS Books shown as a positive figure in the report (× -1 per requirement).
    g['TDS Books'] = g['TDS Books'] * -1
    g['PAN Status'] = g['PAN'].apply(
        lambda x: 'Missing' if str(x).strip() in ('', 'Missing', 'nan') else 'Available')
    g['Expected TDS'] = [_expected_tds(h, p, a, tds_rules)
                         for h, p, a in zip(g['Expense Head'], g['PAN'], g['Expense Amount'])]
    g['Remarks'] = ''
    g = g.sort_values(['Party Name', 'Expense Head']).reset_index(drop=True)
    return g


def _safe_sheet_name(name, used):
    import re
    s = re.sub(r'[\\/?*\[\]:]', ' ', str(name)).strip()[:31] or 'Sheet'
    base, i = s, 2
    while s.lower() in used:
        suf = f" ({i})"
        s = base[:31 - len(suf)] + suf
        i += 1
    used.add(s.lower())
    return s


# ── Summary sheets (PAN-wise + exceptions) ───────────────────────────────────
_PAN_SUMMARY_COLS = ['PAN', 'Party Name(s)', 'Total Expense', 'Expected TDS',
                     'TDS Books', 'TDS Winman', 'Variance', 'Status']
_PAN_SUMMARY_AMT = {'Total Expense', 'Expected TDS', 'TDS Books', 'TDS Winman', 'Variance'}
_EXC_COLS = ['Report', 'Party Name', 'Expense Head', 'PAN', 'Expense Amount',
             'Expected TDS', 'TDS Books', 'TDS Winman', 'Difference', 'Reason']
_EXC_AMT = {'Expense Amount', 'Expected TDS', 'TDS Books', 'TDS Winman', 'Difference'}
_STATUS_FILL = {'PAN missing': _CLR_PAN, 'Not deducted': _CLR_NOTDED,
                'Books ≠ Winman': _CLR_WINMAN, 'Short deduction': _CLR_DIFF, 'OK': _CLR_OK}


def _pan_status(pan, books, winman, expected):
    """Overall status for a PAN in the summary (worst-case, text form)."""
    if str(pan).strip() in ('', 'Missing', 'nan'):
        return 'PAN missing'
    try:
        b, w, e = float(books or 0), float(winman or 0), float(expected or 0)
    except Exception:
        b = w = e = 0.0
    if e > 0 and round(b, 2) == 0:
        return 'Not deducted'
    if round(b - w, 2) != 0:
        return 'Books ≠ Winman'
    if round(b - e, 2) != 0:
        return 'Short deduction'
    return 'OK'


def _row_reason(tds_books, tds_winman, difference, expected, pan_status):
    """Text reason a party row is NOT ok (same rules as _row_fill); '' when OK."""
    if pan_status == 'Missing':
        return 'PAN missing'
    try:
        tb = float(tds_books or 0)
    except Exception:
        tb = 0.0
    if tb == 0 and expected not in ('', None, 'Below Threshold', 'Unmapped'):
        try:
            if float(expected) > 0:
                return 'TDS expected but not deducted'
        except Exception:
            pass
    try:
        tw = float(tds_winman or 0)
    except Exception:
        tw = 0.0
    if round(tb - tw, 2) != 0:
        return 'TDS Books ≠ Winman (deposited)'
    try:
        if tb > 0 and float(difference or 0) != 0:
            return 'Difference ≠ 0'
    except Exception:
        pass
    return ''


def build_bucket_report_excel(company_name: str, fy: str, all_data: dict,
                              buckets: dict) -> bytes:
    """Build the bucketed party-view TDS report workbook. Returns xlsx bytes."""
    import io
    import tds_rules_engine
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
    from openpyxl.utils import get_column_letter

    df = (all_data or {}).get('expense')
    if df is None or df.empty:
        raise ValueError("No expense/TDS data loaded to report on.")

    all_heads = list_expense_heads(all_data)
    units = compute_report_units(all_heads, buckets)
    if not units:
        raise ValueError("No ledgers selected for the report — assign at least one "
                         "head to Standalone or a Group.")

    tds_rules = tds_rules_engine.get_effective_rules(company_name, fy, all_heads) or {}

    thin = Side(style="thin", color="BBBBBB")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)
    hfill = PatternFill("solid", fgColor="1F4E79")
    hfont = Font(bold=True, color="FFFFFF", name="Segoe UI", size=10)
    home_font = Font(color="FFFFFF", bold=True, name="Segoe UI", size=10)
    link_font = Font(color="1F4E79", underline="single", name="Segoe UI")

    wb = Workbook()
    wb.remove(wb.active)
    index_ws = wb.create_sheet("Index")
    used_names = {"index"}
    index_entries = []          # (sheet_name, title, type, ledgers_str, rows)

    def _sheet(sname, cols, records, amt_cols, wrap_cols, fill_fn):
        """Write one styled sheet: Home row, header, coloured/bordered data,
        Indian number format on amounts, auto-width, frozen header."""
        ws = wb.create_sheet(sname)
        hc = ws.cell(row=1, column=1, value="🏠 Home")
        hc.hyperlink = "#Index!A1"
        hc.font = home_font
        hc.fill = hfill
        hc.alignment = Alignment(horizontal="center")
        ws.row_dimensions[1].height = 20
        for c, col in enumerate(cols, start=1):
            hcell = ws.cell(row=2, column=c, value=col)
            hcell.fill = hfill
            hcell.font = hfont
            hcell.border = border
            hcell.alignment = Alignment(horizontal="center", vertical="center",
                                        wrap_text=True)
        for ri, rec in enumerate(records, start=3):
            fx = fill_fn(rec) if fill_fn else None
            fill = PatternFill("solid", fgColor=fx) if fx else None
            for c, col in enumerate(cols, start=1):
                val = rec.get(col, '')
                if isinstance(val, float) and pd.isna(val):
                    val = ''
                cell = ws.cell(row=ri, column=c, value=(None if val == '' else val))
                cell.border = border
                if fill:
                    cell.fill = fill
                if col in amt_cols and isinstance(val, (int, float)):
                    cell.number_format = _INR_FMT
                cell.alignment = Alignment(vertical="top", wrap_text=col in wrap_cols)
        for c, col in enumerate(cols, start=1):
            maxlen = len(col)
            for r in range(3, ws.max_row + 1):
                v = ws.cell(row=r, column=c).value
                if v is not None:
                    maxlen = max(maxlen, min(len(str(v)), 40))
            ws.column_dimensions[get_column_letter(c)].width = min(max(maxlen + 3, 10), 45)
        ws.freeze_panes = "A3"

    def _party_fill(rec):
        return _row_fill(rec.get('TDS Books'), rec.get('TDS Winman'),
                         rec.get('Difference'), rec.get('Expected TDS'),
                         rec.get('PAN Status'))

    # Party-view per unit (computed once, reused for the per-unit + summary sheets).
    unit_pvs = [(u, _party_view(df, u["ledgers"], tds_rules)) for u in units]
    comb = [pv.assign(Report=u["title"]) for u, pv in unit_pvs if not pv.empty]
    combined = pd.concat(comb, ignore_index=True) if comb else pd.DataFrame()

    # ── Summary 1: PAN-wise TDS summary (one row per PAN) ────────────────────
    # ── Summary 2: Exceptions — every 'not OK' party row with a reason ───────
    if not combined.empty:
        _c = combined.copy()
        _c['_ExpNum'] = pd.to_numeric(_c['Expected TDS'], errors='coerce').fillna(0)
        pan_grp = _c.groupby('PAN', as_index=False, dropna=False).agg(**{
            'Party Name(s)': ('Party Name', lambda s: ', '.join(sorted(
                {str(x).strip() for x in s if str(x).strip() not in ('', 'nan')}))[:250]),
            'Total Expense': ('Expense Amount', 'sum'),
            'Expected TDS': ('_ExpNum', 'sum'),
            'TDS Books': ('TDS Books', 'sum'),
            'TDS Winman': ('TDS Winman', 'sum')})
        pan_grp['Variance'] = (pan_grp['TDS Books'] - pan_grp['Expected TDS']).round(2)
        pan_grp['Status'] = [_pan_status(p, b, w, e) for p, b, w, e in zip(
            pan_grp['PAN'], pan_grp['TDS Books'], pan_grp['TDS Winman'], pan_grp['Expected TDS'])]
        pan_grp['PAN'] = pan_grp['PAN'].apply(lambda x: str(x).strip() or '(No PAN)')
        pan_grp = pan_grp.sort_values('PAN').reset_index(drop=True)
        _sn = _safe_sheet_name('PAN-wise TDS Summary', used_names)
        _sheet(_sn, _PAN_SUMMARY_COLS, pan_grp.to_dict('records'), _PAN_SUMMARY_AMT,
               {'Party Name(s)', 'Status'},
               lambda rec: _STATUS_FILL.get(rec.get('Status'), _CLR_OK))
        index_entries.append((_sn, 'PAN-wise TDS Summary', 'Summary',
                              'All reported ledgers', len(pan_grp)))

        _c['Reason'] = [_row_reason(b, w, d, e, ps) for b, w, d, e, ps in zip(
            _c['TDS Books'], _c['TDS Winman'], _c['Difference'],
            _c['Expected TDS'], _c['PAN Status'])]
        exc = _c[_c['Reason'] != ''].sort_values(['Reason', 'Party Name']).reset_index(drop=True)
        _sn2 = _safe_sheet_name('Exceptions (Not OK)', used_names)
        _sheet(_sn2, _EXC_COLS, exc.to_dict('records'), _EXC_AMT,
               {'Report', 'Party Name', 'Expense Head', 'Reason'}, _party_fill)
        index_entries.append((_sn2, 'Exceptions (Not OK)', 'Summary',
                              'All reported ledgers', len(exc)))

    # ── one or more sheets per unit (split at 500 rows) ──────────────────────
    for unit, pv in unit_pvs:
        led_str = ", ".join(unit["ledgers"])
        n = len(pv)
        chunks = [pv.iloc[i:i + _MAX_ROWS_PER_SHEET]
                  for i in range(0, max(n, 1), _MAX_ROWS_PER_SHEET)] or [pv]
        for ci, chunk in enumerate(chunks):
            title = unit["title"] if ci == 0 else f'{unit["title"]} ({ci + 1})'
            sname = _safe_sheet_name(title, used_names)
            _sheet(sname, _REPORT_COLS, chunk.to_dict('records'), _REPORT_AMT_COLS,
                   {'Expense Head', 'Party Name', 'Remarks'}, _party_fill)
            index_entries.append((sname, title, unit["type"], led_str, len(chunk)))

    # ── Index sheet ──────────────────────────────────────────────────────────
    idx_headers = ["S.No", "Report", "Type", "Ledgers included", "Rows", "Remarks"]
    for c, h in enumerate(idx_headers, start=1):
        cell = index_ws.cell(row=1, column=c, value=h)
        cell.fill = hfill
        cell.font = hfont
        cell.border = border
        cell.alignment = Alignment(horizontal="center")
    for i, (sname, title, typ, leds, rows) in enumerate(index_entries, start=1):
        index_ws.cell(row=i + 1, column=1, value=i).border = border
        link = index_ws.cell(row=i + 1, column=2, value=title)
        link.hyperlink = f"#'{sname}'!A1"
        link.font = link_font
        link.border = border
        index_ws.cell(row=i + 1, column=3, value=typ).border = border
        lc = index_ws.cell(row=i + 1, column=4, value=leds)
        lc.border = border
        lc.alignment = Alignment(wrap_text=True, vertical="top")
        index_ws.cell(row=i + 1, column=5, value=rows).border = border
        index_ws.cell(row=i + 1, column=6, value="").border = border
    for c, w in enumerate([6, 34, 12, 50, 8, 24], start=1):
        index_ws.column_dimensions[get_column_letter(c)].width = w
    index_ws.freeze_panes = "A2"

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf.getvalue()