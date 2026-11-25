import pyodbc
import warnings
import pandas as pd
import time
import os
import paths

warnings.filterwarnings('ignore')

# pyodbc pools connections by default, so after switching the company in Tally a
# reused connection still reports the OLD one. Must be set before any connect.
pyodbc.pooling = False

import re
ILLEGAL_CHARS_RE = re.compile(r'[\x00-\x08\x0b\x0c\x0e-\x1f]')

def clean_df(df):
    return df.apply(lambda col: col.map(
        lambda v: ILLEGAL_CHARS_RE.sub('', v) if isinstance(v, str) else v
    ))


# Tally's ODBC does not guarantee the CASE of returned column names — the same
# field has come back as both $VoucherTypeName and $vouchertypename on different
# runs, which silently breaks name-based lookups downstream. Every reader routes
# CSVs through normalize_txn_columns() so casing can never matter again.
CANON_TXN_COLS = [
    'Branch', '$VoucherNumber', '$Supplier_VchNo', '$VoucherId', '$Date',
    '$VoucherTypeName', '$VchTypeParent', '$Particulars', '$Amount',
    '$Led_Parent', '$Led_Group', '$Led_BaseGroup', '$Party_LedName',
    '$Led_GSTIN', '$Led_PAN', '$Party_Flag',
]
_CANON_BY_LOWER = {c.lower(): c for c in CANON_TXN_COLS}


def normalize_txn_columns(df):
    """Trim whitespace and restore the canonical CASE of known transaction
    columns. Unknown columns are left untouched. Returns the same df."""
    df.columns = [
        _CANON_BY_LOWER.get(str(c).strip().lower(), str(c).strip())
        for c in df.columns
    ]
    return df


def test_connection():
    try:
        cnxn = pyodbc.connect("DSN=TallyODBC64_9400;UID=;PWD=;", timeout=5)
        cnxn.close()
        return True, "Connected to Tally on port 9400"
    except Exception as e:
        return False, "Connection failed — Please change Tally ODBC port to 9400"


def get_tally_status():
    """What Tally will ACTUALLY extract — the pre-extraction second check.

    The extraction queries carry no date filter, so whatever the selected
    company + current period in Gateway of Tally hold is what comes out. Rather
    than trust metadata, this reads the real thing:

      * date range  -> first/last $Date in DB_Mini (the very collection the
        extraction reads), via TOP 1 + ORDER BY. Instant, no full table pull.
        Tally exposes NO usable "current period" field — every $From/$To/
        $CurrentPeriodFrom variant returns None — and $StartingFrom/$EndingAt
        are the company's BOOK range, not the period. So this is the only
        trustworthy source.
      * companies   -> all loaded names. Note DB_Mini serves only the ACTIVE
        company, and Tally exposes no "which one is active" flag, so when more
        than one is loaded we say so and infer where we safely can.

    Returns a dict (never raises):
        ok, error, companies[], multi, active_guess,
        period_from, period_to      -> the CURRENT PERIOD set in Gateway of Tally
        data_from, data_to          -> first/last voucher actually inside it
    """
    out = {"ok": False, "error": "", "companies": [], "multi": False,
           "active_guess": "", "period_from": "", "period_to": "",
           "data_from": "", "data_to": ""}
    try:
        cnxn = pyodbc.connect("DSN=TallyODBC64_9400;UID=;PWD=;", timeout=5)
    except Exception:
        out["error"] = "Connection failed — Please change Tally ODBC port to 9400"
        return out

    try:
        cur = cnxn.cursor()

        # 1) Companies + the CURRENT PERIOD. $_ThisYearBeg/$_ThisYearEnd are
        #    computed session fields: every row returns the SAME pair because
        #    they reflect the period set in Gateway of Tally (Alt+F2), not the
        #    company's own books. $StartingFrom/$EndingAt ARE per-company books
        #    and are kept only to work out which company is the active one.
        rows = []
        for sql in ("SELECT $Name, $StartingFrom, $EndingAt, $_ThisYearBeg, $_ThisYearEnd FROM Company",
                    "SELECT $Name, $StartingFrom, $EndingAt FROM Company",
                    "SELECT $Name FROM Company"):
            try:
                cur.execute(sql)
                for r in cur.fetchall():
                    if not r or not str(r[0]).strip():
                        continue
                    rows.append({
                        "name": str(r[0]).strip(),
                        "books_from": r[1] if len(r) > 1 else None,
                        "books_to":   r[2] if len(r) > 2 else None,
                        "yr_beg":     r[3] if len(r) > 3 else None,
                        "yr_end":     r[4] if len(r) > 4 else None,
                    })
                break
            except Exception:
                continue
        if rows:
            out["companies"] = [r["name"] for r in rows]
            out["multi"] = len(rows) > 1
            out["ok"] = True
            for r in rows:                       # first row that reports it
                if r["yr_beg"]:
                    out["period_from"] = str(r["yr_beg"])[:10]
                    out["period_to"] = str(r["yr_end"] or "")[:10]
                    break
        else:
            out["error"] = "Connected, but could not read the company list."

        # 2) What data actually sits inside that period (cheap: two TOP-1s).
        #    Narrower than the period => entries incomplete / not posted yet.
        for key, order in (("data_from", "ASC"), ("data_to", "DESC")):
            try:
                cur.execute(f"SELECT TOP 1 $Date FROM DB_Mini ORDER BY $Date {order}")
                r = cur.fetchone()
                if r and r[0]:
                    out[key] = str(r[0])[:10]
            except Exception:
                pass
        # Fall back to the data range if the period fields aren't available.
        if not out["period_from"]:
            out["period_from"], out["period_to"] = out["data_from"], out["data_to"]

        # 3) Which loaded company is ACTIVE? Tally's ODBC does NOT expose this:
        #    every candidate flag ($IsActive/$IsSelected/$IsCurrent/...) returns
        #    NULL, and the Company table always lists ALL loaded companies.
        #    Guessing from the books range is unreliable — when two companies'
        #    books overlap the chosen period it names the wrong one — and a
        #    wrong name is worse than no name. So only claim it when a single
        #    company is loaded, where there is nothing to get wrong.
        if len(rows) == 1:
            out["active_guess"] = rows[0]["name"]
    finally:
        try:
            cnxn.close()
        except Exception:
            pass
    return out


# ── Constants ─────────────────────────────────────────────────────────────────
EXCLUDE_BASE_GROUPS = {
    'Duties & Taxes', 'Direct Expenses', 'Indirect Expenses',
    'Direct Income', 'Indirect Income', 'Sales Accounts', 'Purchase Accounts',
    'Bank Accounts', 'Cash-in-Hand', 'Bank OD Accounts'
}

EXPENSE_BASE_GROUPS = {'Direct Expenses', 'Indirect Expenses'}

PARTY_BASE_GROUPS = {'Sundry Debtors', 'Sundry Creditors','Loans (Liability)', 'Loans & Advances (Asset)', 'Unsecured Loans'}


# ── Pass 1: Derive party for blank $Party_LedName (all vouchers) ──────────────
def derive_party_ledger(df_transactions, master_map):
    """
    For vouchers where $Party_LedName is blank:
    - Single candidate → DERIVED
    - Multi expense + multi party → AMBIGUOUS
    - 1 expense + multi party → split always
    """
    blank_mask = (
        df_transactions['$Party_LedName'].isna() |
        (df_transactions['$Party_LedName'].astype(str).str.strip() == '') |
        (df_transactions['$Party_LedName'].astype(str).str.strip() == 'nan')
    )

    df_transactions['$Party_Flag'] = 'ORIGINAL'

    if not blank_mask.any():
        return df_transactions

    blank_vchs = df_transactions.loc[blank_mask, '$VoucherId'].unique()

    for vch in blank_vchs:
        vch_rows = df_transactions[df_transactions['$VoucherId'] == vch]

        candidates = vch_rows[
            ~vch_rows['$Led_BaseGroup'].isin(EXCLUDE_BASE_GROUPS)
        ]['$Particulars'].dropna().unique().tolist()
        candidates = [c for c in candidates if str(c).strip() not in ['', 'nan']]

        vch_mask = (df_transactions['$VoucherId'] == vch) & blank_mask

        if len(candidates) == 1:
            party = candidates[0]
            df_transactions.loc[vch_mask, '$Party_LedName'] = party
            df_transactions.loc[vch_mask, '$Party_Flag']    = 'DERIVED'
            gstin = master_map.get(party, {}).get('$_PartyGSTIN1', '')
            pan   = master_map.get(party, {}).get('$PAN', '')
            df_transactions.loc[vch_mask, '$Led_GSTIN'] = gstin
            df_transactions.loc[vch_mask, '$Led_PAN']   = pan

        elif len(candidates) > 1:
            # Check if 1 expense + multi party — defer to Pass 2
            expense_rows = vch_rows[vch_rows['$Led_BaseGroup'].isin(EXPENSE_BASE_GROUPS)]
            party_rows   = vch_rows[vch_rows['$Led_BaseGroup'].isin(PARTY_BASE_GROUPS)]

            if len(expense_rows) > 1 or len(party_rows) < 2:
                # Multi expense or not a clean split case → AMBIGUOUS
                df_transactions.loc[vch_mask, '$Party_LedName'] = ' | '.join(candidates)
                df_transactions.loc[vch_mask, '$Party_Flag']    = 'AMBIGUOUS'
            # else: leave blank — Pass 2 will handle split

    # ── Split: 1 expense + multi party (always on) ───────────────────────────
    exp_vchs = df_transactions[
        (
            df_transactions['$Led_BaseGroup'].isin(EXPENSE_BASE_GROUPS) |
            (
                (df_transactions['$Led_BaseGroup'] == 'Duties & Taxes') &
                (df_transactions['$Particulars'].str.lower().str.contains('tds|tax deducted', na=False))
            )
        ) &
        ~df_transactions['$Particulars'].str.lower().str.contains('round', na=False)
    ]['$VoucherId'].unique()

    grp = df_transactions.groupby('$VoucherId')
    rows_to_add, rows_to_remove = [], []

    for vch in exp_vchs:
        vch_rows     = grp.get_group(vch)
        expense_rows = vch_rows[
            vch_rows['$Led_BaseGroup'].isin(EXPENSE_BASE_GROUPS) |
            (
                (vch_rows['$Led_BaseGroup'] == 'Duties & Taxes') &
                (vch_rows['$Particulars'].str.lower().str.contains('tds|tax deducted', na=False))
            )
        ]
        party_rows   = vch_rows[vch_rows['$Led_BaseGroup'].isin(PARTY_BASE_GROUPS)]

        if len(expense_rows) == 1 and len(party_rows) >= 2:
            exp_row       = expense_rows.iloc[0]
            total_exp     = abs(float(exp_row['$Amount']))
            total_party   = party_rows['$Amount'].apply(lambda x: abs(float(x))).sum()
            running_total = 0.0

            for i, (_, p_row) in enumerate(party_rows.iterrows()):
                pname  = p_row['$Particulars']
                pamt   = abs(float(p_row['$Amount']))
                if i == len(party_rows) - 1:
                    split_amt = round(total_exp - running_total, 2)
                else:
                    split_amt = round((pamt / total_party) * total_exp, 2)
                    running_total += split_amt
                flag   = 'SPLIT_ROUNDING' if abs(split_amt - pamt) > 0.01 else 'SPLIT'
                nr     = exp_row.copy()
                nr['$Amount']        = split_amt if float(exp_row['$Amount']) > 0 else -split_amt
                nr['$Party_LedName'] = pname
                nr['$Party_Flag']    = flag
                nr['$Led_GSTIN']     = master_map.get(pname, {}).get('$_PartyGSTIN1', '')
                nr['$Led_PAN']       = master_map.get(pname, {}).get('$PAN', '')
                rows_to_add.append(nr)
            rows_to_remove.extend(expense_rows.index.tolist())

    if rows_to_remove:
        df_transactions = df_transactions.drop(index=rows_to_remove)
    if rows_to_add:
        df_transactions = pd.concat([df_transactions, pd.DataFrame(rows_to_add)], ignore_index=True)

    return df_transactions



# ── Main ──────────────────────────────────────────────────────────────────────
def _pull_ledger_master(cnxn):
    """Pull the ledger master (balances only, no transactions) from an open Tally
    company and enrich it with BS/PL nature + gross-profit flag.
    Shared by the previous-year (LS) and NCE master extractors."""
    ledger_df = pd.read_sql("""
        SELECT
            $Name, $_PrimaryGroup, $Parent,
            $OpeningBalance, $_ClosingBalance,
            $_PrevYearBalance, $_PartyGSTIN, $IncomeTaxNumber
        FROM Ledger
    """, cnxn)
    ledger_df = clean_df(ledger_df)
    ledger_df.columns = [
        '$Name', '$_PrimaryGroup', '$Parent', '$OpeningBalance',
        '$ClosingBalance', '$_PrevYearBalance', '$_PartyGSTIN1', '$PAN'
    ]

    # Enrich with BS/PL nature + gross-profit flag
    groups_df = pd.read_sql("""
        SELECT $_PrimaryGroup, $IsRevenue, $AffectsGrossProfit
        FROM Groups
    """, cnxn)
    groups_df = clean_df(groups_df)
    groups_df.columns = ['$_PrimaryGroup', '$IsRevenue', '$AffectsGrossProfit']
    groups_df['$IsRevenue']          = pd.to_numeric(groups_df['$IsRevenue'], errors='coerce').fillna(0)
    groups_df['$AffectsGrossProfit'] = pd.to_numeric(groups_df['$AffectsGrossProfit'], errors='coerce').fillna(0)
    groups_df = groups_df.drop_duplicates(subset=['$_PrimaryGroup'])

    ledger_df = ledger_df.merge(groups_df, on='$_PrimaryGroup', how='left')
    ledger_df['$Nature_Led'] = ledger_df['$IsRevenue'].apply(lambda x: 'PL' if x == 1 else 'BS')
    ledger_df['$GP']         = ledger_df['$AffectsGrossProfit'].apply(lambda x: 1 if x == 1 else 0)
    ledger_df.drop(columns=['$IsRevenue', '$AffectsGrossProfit'], inplace=True)
    return ledger_df


def extract_prev_year_master(company_name: str, fy: str, branch_name: str, concern_type: str = "Single Company"):
    """Extract previous year ledger master only — no transactions."""
    if not company_name:
        raise ValueError("Company name is required")
    if not branch_name:
        raise ValueError("Branch name is required")

    branch_name = branch_name.strip().replace(" ", "_")
    out_dir     = str(paths.extracted_dir(company_name, fy))
    os.makedirs(out_dir, exist_ok=True)

    try:
        cnxn = pyodbc.connect("DSN=TallyODBC64_9400;UID=;PWD=;", timeout=10)
        print("✅ Connected for Previous Year extraction.")
    except Exception:
        raise RuntimeError("Connection failed — Please change Tally ODBC port to 9400")

    ledger_df = _pull_ledger_master(cnxn)
    cnxn.close()

    out_file = os.path.join(out_dir, f"PrevYear_{branch_name}_MasterData.csv")
    ledger_df.to_csv(out_file, index=False)
    print(f"✅ Previous Year Master saved: {out_file}")
    return out_file


def extract_nce_master(company_name: str, fy: str, branch_name: str = None):
    """NCE: extract ledger master only (balances, no transactions) from the open
    Tally company and save it tagged by financial year, fully separate from LS.

    Single company -> financials/masters/master.csv (ready to use).
    Group concern  -> financials/masters/_branch_<branch>.csv (one per branch);
    call consolidate_nce_master() afterwards to sum them into master.csv.
    Returns the written path."""
    if not company_name:
        raise ValueError("Company name is required")
    if not fy:
        raise ValueError("Financial year is required")

    fy = str(fy).strip()
    out_dir = str(paths.masters_dir(company_name, fy))
    os.makedirs(out_dir, exist_ok=True)

    try:
        cnxn = pyodbc.connect("DSN=TallyODBC64_9400;UID=;PWD=;", timeout=10)
        print(f"✅ Connected for NCE master extraction (FY {fy}).")
    except Exception:
        raise RuntimeError("Connection failed — Please change Tally ODBC port to 9400")

    ledger_df = _pull_ledger_master(cnxn)
    cnxn.close()

    if branch_name and branch_name.strip():
        bn = branch_name.strip().replace(" ", "_")
        ledger_df.insert(0, "Branch", branch_name.strip())
        out_file = os.path.join(out_dir, f"_branch_{bn}.csv")
    else:
        out_file = os.path.join(out_dir, "master.csv")
    ledger_df.to_csv(out_file, index=False)
    print(f"✅ NCE master (FY {fy}) saved: {out_file}")
    return out_file


# ── NCE master consolidation / reuse (pure pandas — no Tally) ─────────────────
_NCE_MASTER_NUM   = ['$OpeningBalance', '$ClosingBalance', '$_PrevYearBalance']
_NCE_MASTER_FIRST = ['$Parent', '$_PartyGSTIN1', '$PAN', '$Nature_Led', '$GP']
_NCE_MASTER_COLS  = ['$Name', '$_PrimaryGroup', '$Parent', '$OpeningBalance',
                     '$ClosingBalance', '$_PrevYearBalance', '$_PartyGSTIN1',
                     '$PAN', '$Nature_Led', '$GP']


def _consolidate_master_df(df):
    """Sum ledger balances across branches, grouped by (ledger name + primary
    group). Non-numeric fields take the first value; the Branch column is
    dropped. Works for a single branch (a no-op group-by) and many."""
    df = df.copy()
    df.columns = [c.strip() for c in df.columns]
    if '$Name' not in df.columns or '$_PrimaryGroup' not in df.columns:
        raise ValueError("Master file is missing $Name / $_PrimaryGroup columns.")
    for c in _NCE_MASTER_NUM:
        df[c] = pd.to_numeric(df[c], errors='coerce').fillna(0) if c in df.columns else 0
    for c in _NCE_MASTER_FIRST:
        if c not in df.columns:
            df[c] = ''
    df['$Name'] = df['$Name'].fillna('').astype(str).str.strip()
    df['$_PrimaryGroup'] = df['$_PrimaryGroup'].fillna('').astype(str).str.strip()
    agg = {c: 'sum' for c in _NCE_MASTER_NUM}
    agg.update({c: 'first' for c in _NCE_MASTER_FIRST})
    out = df.groupby(['$Name', '$_PrimaryGroup'], as_index=False).agg(agg)
    return out[_NCE_MASTER_COLS]


def list_nce_branch_masters(company_name: str, fy: str):
    """Branch names already extracted for the NCE master (group mode)."""
    d = paths.masters_dir(company_name, fy)
    return sorted(p.stem[len("_branch_"):] for p in d.glob("_branch_*.csv"))


def consolidate_nce_master(company_name: str, fy: str):
    """Sum all extracted branch masters into financials/masters/master.csv.
    Returns (n_branches, n_ledgers)."""
    d = paths.masters_dir(company_name, fy)
    files = sorted(d.glob("_branch_*.csv"))
    if not files:
        raise FileNotFoundError("No branch masters extracted yet for this year.")
    df = pd.concat([pd.read_csv(f) for f in files], ignore_index=True)
    out = _consolidate_master_df(df)
    out.to_csv(d / "master.csv", index=False)
    print(f"✅ NCE master consolidated from {len(files)} branch(es): {len(out)} ledgers.")
    return len(files), len(out)


def build_nce_master_from_ls(company_name: str, fy: str):
    """Reuse the Ledger-Scrutiny consolidated master to build the NCE master —
    no Tally connection. Sums by (ledger name + primary group), so a group's
    branch-wise LS master collapses to one consolidated NCE master. Writes
    financials/masters/master.csv (LS data is never modified). Returns n_ledgers."""
    src = paths.consolidated_dir(company_name, fy) / "Conso_MasterData.csv"
    if not src.exists():
        raise FileNotFoundError(
            "No Ledger Scrutiny master for this year — run the LS extraction "
            "first, or extract fresh from Tally.")
    out = _consolidate_master_df(pd.read_csv(src))
    dest_dir = paths.masters_dir(company_name, fy)
    os.makedirs(str(dest_dir), exist_ok=True)
    out.to_csv(dest_dir / "master.csv", index=False)
    print(f"✅ NCE master built from Ledger Scrutiny: {len(out)} ledgers.")
    return len(out)


def extract_msme_verify(company_name: str, fy: str, branch_name: str = None):
    """43B(h) advanced verification — pull next-year creditor-ledger movements
    from whatever company/period is CURRENTLY OPEN in Tally (the user sets the
    next-year period, e.g. 01-Apr to mid-Apr, then runs this). Saves only
    Sundry Creditors ledger lines.

    Single company  -> msme/msme_verify.csv (one file).
    Group concern    -> open EACH branch's next-year company in turn and call
    this with its branch_name; each is saved to msme/msme_verify_<branch>.csv and
    tagged with a Branch column, so re-extracting one branch overwrites only that
    branch and the others accumulate (same pattern as the main extraction).

    Returns (output_path, row_count)."""
    if not company_name:
        raise ValueError("Company name is required")
    out_dir = str(paths.msme_dir(company_name, fy))
    os.makedirs(out_dir, exist_ok=True)
    branch = (branch_name or "").strip()
    if branch:
        safe = branch.replace(" ", "_")
        out_file = os.path.join(out_dir, f"msme_verify_{safe}.csv")
    else:
        out_file = os.path.join(out_dir, "msme_verify.csv")

    try:
        cnxn = pyodbc.connect("DSN=TallyODBC64_9400;UID=;PWD=;", timeout=10)
    except Exception:
        raise RuntimeError("Connection failed — Please change Tally ODBC port to 9400")

    df = pd.read_sql("""
        SELECT
            $VoucherNumber, $VoucherId, $Date,
            $VoucherTypeName, $VchTypeParent,
            $Particulars, $Amount,
            $Led_Parent, $Led_Group, $Led_BaseGroup,
            $Party_LedName
        FROM DB_Mini
    """, cnxn)
    cnxn.close()
    df = clean_df(df)
    if '$Led_BaseGroup' in df.columns:
        df = df[df['$Led_BaseGroup'].astype(str).str.strip().str.lower() == 'sundry creditors']
    if branch:
        df.insert(0, "Branch", branch)
    df.to_csv(out_file, index=False)
    return out_file, len(df)


def main(company_name: str, fy: str, branch_name: str, concern_type: str = "Single Company"):
    """
    STEP 1 – DATA EXTRACTION FROM TALLY
    concern_type: "Single Company" | "Group Concern"
    """
    if not company_name:
        raise ValueError("Company name is required")
    if not branch_name:
        raise ValueError("Branch name is required")

    branch_name = branch_name.strip().replace(" ", "_")

    if concern_type == "Single Company":
        txn_out_dir = str(paths.consolidated_dir(company_name, fy))
    else:
        txn_out_dir = str(paths.extracted_dir(company_name, fy))

    master_out_dir = str(paths.extracted_dir(company_name, fy))
    os.makedirs(txn_out_dir, exist_ok=True)
    os.makedirs(master_out_dir, exist_ok=True)

    if concern_type == "Single Company":
        transactions_file = os.path.join(txn_out_dir, "Transactions_1.csv")
    else:
        transactions_file = os.path.join(txn_out_dir, f"{branch_name.strip().replace(' ', '_')}_Transactions.csv")

    master_data_file = os.path.join(master_out_dir, f"{branch_name}_MasterData.csv")

    if os.path.exists(transactions_file) or os.path.exists(master_data_file):
        print(f"⚠️ Overwriting existing data for branch '{branch_name}'.")

    extract_start_time = time.time()
    try:
        cnxn = pyodbc.connect("DSN=TallyODBC64_9400;UID=;PWD=;", timeout=10)
        print("✅ Connected to Tally ODBC successfully!")
    except Exception as e:
        raise RuntimeError("Connection failed — Please change Tally ODBC port to 9400")

    print("Fetching transactions from Tally...")
    start_time = time.time()

    # $Supplier_VchNo = the supplier's own invoice number (for GST
    # reconciliation), from the custom TDL; populated on Purchase / Debit Note
    # vouchers. Tally returns a field it doesn't know as empty rather than
    # erroring, so a machine without the TDL just gets blanks here.
    df_transactions = pd.read_sql("""
        SELECT
            $VoucherNumber, $Supplier_VchNo, $VoucherId, $Date,
            $VoucherTypeName, $VchTypeParent,
            $Particulars, $Amount,
            $Led_Parent, $Led_Group, $Led_BaseGroup,
            $Party_LedName, $Led_GSTIN, $Led_PAN
        FROM DB_Mini
    """, cnxn)
    df_transactions = normalize_txn_columns(clean_df(df_transactions))

    print(f"--- {time.time() - start_time:.2f} seconds for Extracting ---")

    print("Fetching Ledger Master...")
    start_time = time.time()
    ledger_full_df = pd.read_sql("""
        SELECT
            $Name, $_PrimaryGroup, $Parent,
            $OpeningBalance, $_ClosingBalance,
            $_PrevYearBalance, $_PartyGSTIN, $IncomeTaxNumber
        FROM Ledger
    """, cnxn)
    ledger_full_df = clean_df(ledger_full_df)
    ledger_full_df.columns = [
        '$Name', '$_PrimaryGroup', '$Parent', '$OpeningBalance',
        '$ClosingBalance', '$_PrevYearBalance', '$_PartyGSTIN1', '$PAN'
    ]
    ledger_full_df.insert(7, '$Nature_Led', '')
    print(f"--- {time.time() - start_time:.2f}s for Ledger Master ---")

    print("Fetching Groups Master...")
    groups_df = pd.read_sql("""
        SELECT $_PrimaryGroup, $IsRevenue, $AffectsGrossProfit
        FROM Groups
    """, cnxn)
    groups_df = clean_df(groups_df)
    groups_df.columns = ['$_PrimaryGroup', '$IsRevenue', '$AffectsGrossProfit']
    groups_df['$IsRevenue'] = pd.to_numeric(groups_df['$IsRevenue'], errors='coerce').fillna(0)
    groups_df['$AffectsGrossProfit'] = pd.to_numeric(groups_df['$AffectsGrossProfit'], errors='coerce').fillna(0)
    groups_df = groups_df.drop_duplicates(subset=['$_PrimaryGroup'])
    cnxn.close()

    # Auto fill PAN from GSTIN in master data
    ledger_full_df['$PAN'] = ledger_full_df.apply(
        lambda row: str(row['$_PartyGSTIN1'])[2:12]
        if str(row['$PAN']).strip() in ['', 'nan', 'None', 'Missing']
        and len(str(row['$_PartyGSTIN1']).strip()) == 15
        else row['$PAN'], axis=1
    )
    
    # Enrich ledger master with BS/PL and GP
    ledger_full_df = ledger_full_df.merge(
        groups_df[['$_PrimaryGroup', '$IsRevenue', '$AffectsGrossProfit']],
        left_on='$_PrimaryGroup',
        right_on='$_PrimaryGroup',
        how='left'
    )
    ledger_full_df['$Nature_Led'] = ledger_full_df['$IsRevenue'].apply(
        lambda x: 'PL' if x == 1 else 'BS')
    ledger_full_df['$GP'] = ledger_full_df['$AffectsGrossProfit'].apply(
        lambda x: 1 if x == 1 else 0)
    ledger_full_df.drop(columns=['$IsRevenue', '$AffectsGrossProfit'], inplace=True)

    # Build master lookup once — used in both passes
    master_map = ledger_full_df.set_index('$Name')[
        ['$_PartyGSTIN1', '$PAN']
    ].to_dict('index')

    # ── Pass 1: Blank party derive ────────────────────────────────────────────
    print("Deriving party ledgers and splitting multi-party expenses...")
    df_transactions = derive_party_ledger(df_transactions, master_map)

    # Auto fill PAN from GSTIN where missing
    def fill_pan_from_gstin(row):
        pan   = str(row['$Led_PAN']).strip()
        gstin = str(row['$Led_GSTIN']).strip()
        if pan in ['', 'nan', 'None', 'Missing'] and len(gstin) == 15:
            return gstin[2:12]
        return row['$Led_PAN']
    df_transactions['$Led_PAN'] = df_transactions.apply(fill_pan_from_gstin, axis=1)
    print("✅ PAN auto-filled from GSTIN where missing.")


    # ── Stats ─────────────────────────────────────────────────────────────────
    flag_counts = df_transactions['$Party_Flag'].value_counts().to_dict()
    print(f"✅ Flag summary: {flag_counts}")

    df_transactions.to_csv(transactions_file, index=False)
    ledger_full_df.to_csv(master_data_file, index=False)

    if concern_type == "Single Company":
        try:
            import json
            from datetime import datetime
            filt = df_transactions.copy()
            filter_options = {
                "tds_ledgers": sorted(filt[filt['$Led_BaseGroup'] == 'Duties & Taxes']['$Particulars'].dropna().unique().tolist()),
                "party_names": sorted(filt['$Party_LedName'].dropna().unique().tolist()),
                "expenses"   : sorted(filt[filt['$Led_BaseGroup'].isin(['Direct Expenses','Indirect Expenses'])]['$Particulars'].dropna().unique().tolist()),
                "gst_ledgers": sorted(filt[filt['$Led_BaseGroup'] == 'Duties & Taxes']['$Particulars'].dropna().unique().tolist())
            }
            with open(os.path.join(txn_out_dir, "Filter_Options.json"), 'w') as f:
                json.dump(filter_options, f)
            with open(os.path.join(txn_out_dir, "Export_Log.txt"), 'w') as f:
                f.write(f"Export Date: {datetime.now()}\nFile Name, Number of Rows\nTransactions_1.csv, {len(df_transactions)}\n")
            ledger_full_df.to_csv(os.path.join(txn_out_dir, "Conso_MasterData.csv"), index=False)
            INCLUDE_GROUPS = {
                'Sundry Debtors', 'Sundry Creditors',
                'Loans (Liability)', 'Loans & Advances (Asset)',
                'Capital Account', 'Investments',
                'Secured Loans', 'Unsecured Loans',
                'Bank Accounts', 'Bank OD Accounts'
            }
            rp_ledgers = sorted(
                ledger_full_df[ledger_full_df['$_PrimaryGroup'].isin(INCLUDE_GROUPS)]['$Name']
                .dropna().unique().tolist()
            )
            with open(os.path.join(txn_out_dir, "RP_Ledgers.json"), 'w') as f:
                json.dump(rp_ledgers, f)
            print("✅ Filter options, log and master saved to consolidated.")
        except Exception as e:
            print(f"⚠️ Post-extract save failed: {e}")

    total_time = time.time() - extract_start_time
    print("✅ Extraction completed!")
    print(f"  - {transactions_file}")
    print(f"  - {master_data_file}")
    return round(total_time, 1)