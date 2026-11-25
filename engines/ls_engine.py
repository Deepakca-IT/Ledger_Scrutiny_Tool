import pandas as pd
import numpy as np
import re
from pathlib import Path


SCRUTINY_REMARKS = {
    "Journal_Debtors_No_Income": {
        "title"  : "Vouchers in Debtors ledgers having Journal entries other than Income ledgers",
        "remarks": "Ideally Journal Entries to be avoided in Party Ledgers. Even incase if such direct entries are posted, it should be impacting the Income ledgers.",
        "action" : "Check for Accuracy and Reason for such entries being in existence."
    },
    "Fixed_Assets_Purchased": {
        "title"  : "Fixed Assets Purchased During The Year",
        "remarks": "The following is the list of the Assets that have been purchased during the year.",
        "action" : "Obtain the Invoice copies, check FA Registers, Check for GST Credit availments."
    },
    "Debtors_Same_Balance": {
        "title"  : "Sundry Debtors — Opening balance & Closing balance Same for Party Ledgers",
        "remarks": "Opening Balance should have been received during the year.",
        "action" : "Analyse opening balance is equal to closing balance and confirm."
    },
    "Same_Opening_Closing": {
        "title"  : "Ledgers having same Opening and Closing balance other than Debtors & Fixed Assets",
        "remarks": "Opening Balance should have been received during the year.",
        "action" : "Analyse opening balance is equal to closing balance and confirm."
    },
    "Cash_Payments_Above_10000": {
        "title"  : "Cash payments more than 10,000",
        "remarks": "There should not be any cash payments in excess of Rs 10,000 and above.",
        "action" : "These transactions are to be considered for disallowance under section 40A(3) of Income Tax for tax computation."
    },
    "Cash_Receipts_Above_20000": {
        "title"  : "Cash receipts more than 20,000",
        "remarks": "",
        "action" : ""
    },
    "Prepaid_Same_Balance": {
        "title"  : "Prepaid Expenses — Opening balance is same as closing balance",
        "remarks": "Opening Balance should have been accounted as expenses during the year.",
        "action" : "Expense to the extent proportionate to the current year and expenses related to future period to be continued in prepaid."
    },
    "Cash_Receipt_Via_Payment": {
        "title"  : "Cash Ledger is of Receipt nature passed through Payment Entry",
        "remarks": "Ideally Cash Inflow should be in receipt ledger, however Tally allows cash to be routed through payment also.",
        "action" : "Check the correctness of the entries and get them corrected wherever needed."
    },
    "Running_Negative_Cash": {
        "title"  : "Negative Balance in Closing Cash Ledgers",
        "remarks": "Cash Balance can never be negative, you cannot spend what you do not have.",
        "action" : "Check for missing receipts or Duplicate Payments."
    },
    "Cash_Payment_Via_Receipt": {
        "title"  : "Cash Ledger is of Payment Nature Passed Through Receipt Entry",
        "remarks": "Ideally Cash Outflow should be in Payment ledger, however Tally allows cash to be routed through journal also.",
        "action" : "Check the correctness of the entries and get them corrected wherever needed."
    },
    "Fixed_Assets_Below_5000": {
        "title"  : "Fixed Asset — Additions value less than 5000",
        "remarks": "The following is the list of the Assets that are capitalised where Values < 5000.",
        "action" : "These should be charged off to Profit and Loss Account."
    },
    "Asset_Credit_Balance": {
        "title"  : "Asset ledgers with credit balance other than Sundry Debtors & Fixed Assets",
        "remarks": "General Nature of Asset Balances is Debit.",
        "action" : "Analyse the reason for these being credit and confirm."
    },
    "Staff_Advances_Pending": {
        "title"  : "Long Pending Staff Advances",
        "remarks": "Staff advances more than 90 days overdue.",
        "action" : "Analyse the reason for non-recovery, document it and confirm."
    },
    "Journal_Creditors_No_Purchase": {
        "title"  : "Vouchers in Creditors ledgers having Journal entries other than Purchase / Expenses",
        "remarks": "Creditors ledger should have only purchase vouchers or Debit notes.",
        "action" : "Understand the concept of accounting. If journal is the practice of accounting purchase and expense, recommend for change and obtain substantive documents for high amounts."
    },
    "Suppliers_No_GST": {
        "title"  : "Suppliers without GST Number",
        "remarks": "Generally recommended to have business with GST registered suppliers for better compliance.",
        "action" : "If suppliers are registered, inform the accountant to collect and update the GSTN."
    },
    "Creditors_Same_Balance": {
        "title"  : "Opening balance & Closing balance Same for Party Ledgers — Sundry Creditors",
        "remarks": "Opening Balance should have been paid during the year.",
        "action" : "Analyse opening balance is equal to closing balance and confirm."
    },
    "Loans_Repayments": {
        "title"  : "Loans — Repayments",
        "remarks": "",
        "action" : ""
    },
    "Liability_Debit_Balance": {
        "title"  : "Liability Ledgers with Debit Balance other than Sundry Creditors",
        "remarks": "General Nature of Liability Balances is Credit.",
        "action" : "Analyse the reason for these being Debit and confirm."
    },
    "Loans_Receipts": {
        "title"  : "Loans — Receipts",
        "remarks": "Loans received.",
        "action" : ""
    },
    "Creditors_With_Income": {
        "title"  : "Voucher having Creditors ledgers and Income Ledgers",
        "remarks": "Ideally creditors are related to expenses.",
        "action" : "Check if there are entries which have creditors and income ledger. Get the accounting rectified unless the company has business of both purchase and sale."
    },
    "269ST_Cash_Violations": {
        "title"  : "269ST Cash Receipt Violations",
        "remarks": "Cash receipts above Rs 2,00,000 from a single party in a single day.",
        "action" : "These are violations under section 269ST. Verify and take corrective action."
    },
    "HighValue_Sales_Cash_Ref": {
        "title"  : "High Value Sales with Cash Cross Reference",
        "remarks": "High value sales invoices cross referenced with cash receipts from same parties.",
        "action" : "Analyse if cash is being received against high value sales — potential 269ST risk."
    },
    "Negative_Cash_Balance": {
        "title"  : "Negative Balance in Cash Ledgers",
        "remarks": "Cash Balance can never be negative.",
        "action" : "Check for missing receipts or duplicate payments."
    },
    "Debtors_Credit_Balance": {
        "title"  : "Sundry Debtors with Credit Balance",
        "remarks": "Debtors generally have debit balance. Credit balance may indicate advance received from customer. "
                   "Months_Pending = how long the balance has stayed continuously in credit (movement within credit does not reset it); "
                   "'12+' = credit since opening, i.e. the advance is older than the year.",
        "action" : "Check whether this is advance from customer. If yes, reclassify under Advance from Customers. Confirm outstanding bills if any."
    },
    "Creditors_Debit_Balance": {
        "title"  : "Sundry Creditors with Debit Balance",
        "remarks": "Creditors generally have credit balance. Debit balance may indicate advance payment made or bills pending from supplier. "
                   "Months_Pending = how long the balance has stayed continuously in debit (movement within debit does not reset it); "
                   "'12+' = debit since opening, i.e. the advance is older than the year.",
        "action" : "Check whether advance payment is made or bills are pending. Obtain confirmation and reconcile."
    },
    "Opening_Balance_Mismatch": {
        "title"  : "Opening Balance Mismatch — Previous Year Closing vs Current Year Opening",
        "remarks": "Previous year closing balance should match current year opening balance for all BS ledgers.",
        "action" : "Identify the ledgers with mismatch, check if any entries were passed after year end closing, rectify and confirm."
    },
    "Recurring_Monthly_Expenses": {
        "title"  : "Recurring Monthly Expenses — Missing / Low Months",
        "remarks": "Expenses such as rent, salary, electricity (EB), interest etc. are normally incurred every month. A month with no entry (blank) or an unusually low amount may indicate an unrecorded expense or a missed provision.",
        "action" : "Verify whether the expense for the blank / low months has been omitted or under-provided. Pass the necessary entry or document the reason."
    },
}


class LSEngine:
    def __init__(self, conso_masterdata_path, conso_ledgerview_path=None, prev_year_path=None,
                 prev_branch_pairs=None):
        self.conso_masterdata_path = Path(conso_masterdata_path)
        self.conso_ledgerview_path = Path(conso_ledgerview_path) if conso_ledgerview_path else None
        self.prev_year_path        = Path(prev_year_path) if prev_year_path else None
        # Group concern: {branch: (prev_year_master_csv, current_year_master_csv)} —
        # when given, the OB check runs BRANCH-WISE (catches offsetting errors that
        # a consolidated-level check would hide).
        self.prev_branch_pairs     = prev_branch_pairs or {}
        self.master_df     = None
        self.ledgerview_df = None
        self.prev_year_df  = None

    def load_inputs(self):
        if not self.conso_masterdata_path.exists():
            raise FileNotFoundError(f"Missing file: {self.conso_masterdata_path}")
        self.master_df = pd.read_csv(self.conso_masterdata_path)
        if self.conso_ledgerview_path and self.conso_ledgerview_path.exists():
            self.ledgerview_df = pd.read_csv(self.conso_ledgerview_path)
        else:
            self.ledgerview_df = None
        if self.prev_year_path and self.prev_year_path.exists():
            self.prev_year_df = pd.read_csv(self.prev_year_path)
        else:
            self.prev_year_df = None

    def run_scrutiny(self):
        if self.master_df is None:
            raise RuntimeError("Input data not loaded. Call load_inputs() first.")

        df  = self.master_df.copy()
        df['$_PrimaryGroup'] = df['$_PrimaryGroup'].astype(str).str.strip().str.lower()
        txn = self.ledgerview_df
        results = {}

        # ── Master Data Reports ───────────────────────────────────────────────

        results["Same_Opening_Closing"] = df[
            (df['$OpeningBalance'] == df['$ClosingBalance']) &
            (df['$ClosingBalance'] != 0) &
            (~df['$_PrimaryGroup'].isin(['sundry debtors', 'sundry creditors', 'fixed assets']))
        ].reset_index(drop=True)

        results["Debtors_Same_Balance"] = df[
            (df['$_PrimaryGroup'] == 'sundry debtors') &
            (df['$OpeningBalance'] == df['$ClosingBalance']) &
            (df['$ClosingBalance'] != 0)
        ].reset_index(drop=True)

        prepaid_mask = (
            df['$Name'].str.contains('prepaid', case=False, na=False) |
            df['$Parent'].str.contains('prepaid', case=False, na=False) |
            df['$_PrimaryGroup'].str.contains('prepaid', case=False, na=False)
        )
        results["Prepaid_Same_Balance"] = df[
            prepaid_mask &
            (df['$OpeningBalance'] == df['$ClosingBalance']) &
            (df['$ClosingBalance'] != 0)
        ].reset_index(drop=True)

        results["Negative_Cash_Balance"] = df[
            (df['$_PrimaryGroup'] == 'cash-in-hand') &
            (pd.to_numeric(df['$ClosingBalance'], errors='coerce') > 0)
        ].reset_index(drop=True)

        ASSET_GROUPS = {
            'current assets', 'loans & advances (asset)', 'deposits (asset)',
            'investments', 'misc. expenses (asset)'
        }
        results["Asset_Credit_Balance"] = df[
            (df['$_PrimaryGroup'].isin(ASSET_GROUPS)) &
            (pd.to_numeric(df['$ClosingBalance'], errors='coerce') > 0)
        ].reset_index(drop=True)

        staff_mask = (
            df['$Name'].str.contains('staff|advance', case=False, na=False) |
            df['$Parent'].str.contains('staff|advance', case=False, na=False) |
            df['$_PrimaryGroup'].str.contains('staff|advance', case=False, na=False)
        )
        results["Staff_Advances_Pending"] = df[
            staff_mask &
            (df['$OpeningBalance'] == df['$ClosingBalance']) &
            (df['$ClosingBalance'] != 0)
        ].reset_index(drop=True)

        results["Creditors_Same_Balance"] = df[
            (df['$_PrimaryGroup'] == 'sundry creditors') &
            (pd.to_numeric(df['$OpeningBalance'], errors='coerce') ==
             pd.to_numeric(df['$ClosingBalance'], errors='coerce')) &
            (pd.to_numeric(df['$ClosingBalance'], errors='coerce') != 0)
        ].reset_index(drop=True)

        results["Debtors_Credit_Balance"] = df[
            (df['$_PrimaryGroup'] == 'sundry debtors') &
            (pd.to_numeric(df['$ClosingBalance'], errors='coerce') > 0)
        ].reset_index(drop=True)

        results["Creditors_Debit_Balance"] = df[
            (df['$_PrimaryGroup'] == 'sundry creditors') &
            (pd.to_numeric(df['$ClosingBalance'], errors='coerce') < 0)
        ].reset_index(drop=True)

        results["Suppliers_No_GST"] = df[
            (df['$_PrimaryGroup'] == 'sundry creditors') &
            (
                df['$PartyGSTIN1'].isna() |
                (df['$PartyGSTIN1'].astype(str).str.strip().isin(['', 'nan', 'None']))
            ) &
            (
                (pd.to_numeric(df['$OpeningBalance'], errors='coerce').fillna(0) != 0) |
                (pd.to_numeric(df['$ClosingBalance'], errors='coerce').fillna(0) != 0)
            )
        ].reset_index(drop=True)

        LIABILITY_GROUPS = {
            'loans (liability)', 'current liabilities',
            'provisions', 'bank od accounts',
            'secured loans', 'unsecured loans'
        }
        results["Liability_Debit_Balance"] = df[
            (df['$_PrimaryGroup'].isin(LIABILITY_GROUPS)) &
            (pd.to_numeric(df['$ClosingBalance'], errors='coerce') < 0)
        ].reset_index(drop=True)

        # ── Transaction Based Reports ─────────────────────────────────────────
        if txn is not None and not txn.empty:
            txn_df = txn.copy()
            # Tally's ODBC column CASE varies between runs (e.g. $vouchertypename)
            # — normalise so every name-based lookup below is reliable.
            from engines.extract_engine import normalize_txn_columns
            txn_df = normalize_txn_columns(txn_df)
            txn_df['$Led_BaseGroup'] = txn_df['$Led_BaseGroup'].astype(str).str.strip().str.lower()
            txn_df['$VchTypeParent'] = txn_df['$VchTypeParent'].astype(str).str.strip().str.lower()

            # $VoucherId is unique only WITHIN a Tally company, so the same id
            # repeats across branches (group concern). Scope it by branch here so
            # every downstream $VoucherId group/filter can't splice unrelated
            # branch vouchers together. No effect on single-company data.
            if 'Branch' in txn_df.columns:
                _vid = (txn_df['$VoucherId'].astype(str).str.strip()
                        .str.replace(r'\.0$', '', regex=True))
                txn_df['$VoucherId'] = (txn_df['Branch'].astype(str).str.strip()
                                        + '::' + _vid)

            income_groups    = {'direct income', 'indirect income', 'indirect incomes', 'direct incomes'}
            purchase_expense = {'purchase accounts', 'direct expenses', 'indirect expenses'}

            # Branch helper for constructed-row reports (consolidated txn carries Branch)
            _has_branch = 'Branch' in txn_df.columns

            def _vch_branch(vch_df):
                if not _has_branch:
                    return ''
                return ' | '.join(vch_df['Branch'].dropna().astype(str).unique().tolist())

            # Group the transaction table by voucher ONCE. Every per-voucher
            # report then looks its rows up in O(1) via _vch() instead of
            # rescanning the whole table per voucher (which is quadratic and
            # was the main slowdown on large ledger views).
            _vch_grp = txn_df.groupby('$VoucherId')
            _vch_empty = txn_df.iloc[0:0]

            def _vch(vch):
                try:
                    return _vch_grp.get_group(vch)
                except KeyError:
                    return _vch_empty

            # Fast helpers for the per-voucher summary loops: work on numpy
            # arrays inside each group instead of chains of small pandas
            # filters (which cost ~1ms each and dominated large runs).
            def _first_nn(series):
                a = series.dropna()
                return a.iloc[0] if not a.empty else ''

            def _uniq_join(values):
                out, seen = [], set()
                for x in values:
                    if pd.isna(x):
                        continue
                    s = str(x)
                    if s not in seen:
                        seen.add(s)
                        out.append(s)
                return ' | '.join(out)

            def _np_first(a):
                if a is None:
                    return ''
                for x in a:
                    if not pd.isna(x):
                        return x
                return ''

            def _fast_vch_iter(vch_ids):
                """Iterate vouchers as dicts of numpy column slices — zero
                pandas operations inside the caller's loop. One sort + one
                to_numpy per column TOTAL, then pure-numpy slices per voucher."""
                sub = txn_df[txn_df['$VoucherId'].isin(set(vch_ids))]
                if sub.empty:
                    return
                sub = sub.sort_values('$VoucherId', kind='stable')
                cols = {
                    'amt'  : pd.to_numeric(sub['$Amount'], errors='coerce')
                               .to_numpy(dtype=float),
                    'name' : sub['$Particulars'].to_numpy(),
                    'grp'  : sub['$Led_BaseGroup'].to_numpy(),
                    'date' : sub['$Date'].to_numpy() if '$Date' in sub.columns else None,
                    'vno'  : sub['$VoucherNumber'].to_numpy() if '$VoucherNumber' in sub.columns else None,
                    'vtype': sub['$VchTypeParent'].to_numpy() if '$VchTypeParent' in sub.columns else None,
                    'br'   : sub['Branch'].to_numpy() if _has_branch else None,
                }
                vid = sub['$VoucherId'].to_numpy()
                bounds = np.flatnonzero(np.r_[True, vid[1:] != vid[:-1]])
                bounds = np.append(bounds, len(vid))
                for i in range(len(bounds) - 1):
                    s = slice(bounds[i], bounds[i + 1])
                    yield vid[bounds[i]], {
                        k: (v[s] if v is not None else None)
                        for k, v in cols.items()}

            # Creditors with debit balance — since WHEN has the debit been
            # pending? Rebuild each creditor's running balance (opening + its
            # ledger lines date-wise; negative = debit) and find the date from
            # which the balance stayed continuously debit up to the data end.
            # Movement WITHIN debit (e.g. a further advance) does not reset the
            # clock. Debit from opening that never cleared during the year =
            # advance older than the year -> "12+" (covers the same-opening-
            # closing case automatically).
            _asof_all = pd.to_datetime(txn_df['$Date'], errors='coerce').max()

            def _add_ageing(res_key, sign, since_col):
                """Add '<since_col>' + 'Months_Pending' to a party report.

                sign = -1 -> the abnormal state is a DEBIT balance (creditors,
                             i.e. advance PAID to a supplier)
                sign = +1 -> the abnormal state is a CREDIT balance (debtors,
                             i.e. advance RECEIVED from a customer)

                Walks each party's running balance (opening + its dated lines)
                and finds the date from which it stayed continuously in the
                abnormal state up to the end of the data. Movement WITHIN that
                state (a further advance) does NOT reset the clock. Still
                abnormal from opening = older than this year -> '12+', which
                covers the same-opening-closing case automatically.
                """
                out = results.get(res_key)
                if out is None or out.empty:
                    return
                names = set(out['$Name'])
                _bt = txn_df[txn_df['$Particulars'].isin(names)][
                    ['$Particulars', '$Amount', '$Date']].copy()
                _bt['$Amount'] = pd.to_numeric(_bt['$Amount'], errors='coerce').fillna(0)
                _bt['_Dt'] = pd.to_datetime(_bt['$Date'], errors='coerce')
                _bt = _bt.dropna(subset=['_Dt']).sort_values('_Dt')
                # Group once — a per-name filter inside the loop would rescan
                # the whole table for every party.
                _by_name = {n: g for n, g in _bt.groupby('$Particulars', sort=False)}

                def _since_date(name, opening):
                    led = _by_name.get(name)
                    ob = pd.to_numeric(pd.Series([opening]),
                                       errors='coerce').fillna(0).iloc[0]
                    if led is None or led.empty:
                        return None                 # no movement: since opening
                    amts = led['$Amount'].to_numpy()
                    dts  = led['_Dt'].to_numpy()
                    bal  = ob + np.cumsum(amts)
                    notpending = np.flatnonzero(sign * bal <= 0)
                    if notpending.size == 0:
                        # never came out of the abnormal state this year
                        return None if sign * ob > 0 else dts[0]
                    pos = notpending[-1]            # last time it was NORMAL
                    if pos == len(amts) - 1:
                        return dts[-1]              # data quirk: use last txn
                    return dts[pos + 1]

                _since, _months, _rank = [], [], []
                for _, _r in out.iterrows():
                    d = _since_date(_r['$Name'], _r['$OpeningBalance'])
                    if d is None:
                        _since.append('Opening (last year or earlier)')
                        _months.append('12+')
                        _rank.append(999)
                    else:
                        d = pd.Timestamp(d)
                        m = max(0, int((_asof_all - d).days // 30)) if pd.notna(_asof_all) else 0
                        _since.append(d.strftime('%d-%b-%Y'))
                        _months.append(m)
                        _rank.append(m)
                out = out.assign(**{since_col: _since},
                                 Months_Pending=_months, _rk=_rank)
                results[res_key] = (out.sort_values('_rk', ascending=False)
                                       .drop(columns='_rk').reset_index(drop=True))

            # Creditors in DEBIT  = advance paid to supplier, pending since when?
            _add_ageing("Creditors_Debit_Balance", -1, "Debit_Since")
            # Debtors in CREDIT   = advance received from customer, pending since when?
            _add_ageing("Debtors_Credit_Balance",  +1, "Credit_Since")

            # Journal in Debtors not hitting Income
            debtor_parties = set(df[df['$_PrimaryGroup'] == 'sundry debtors']['$Name'].tolist())
            journal_vchs = txn_df[
                (txn_df['$VchTypeParent'] == 'journal') &
                (txn_df['$Party_LedName'].isin(debtor_parties))
            ]['$VoucherId'].unique()

            no_income_vchs = [
                vch for vch in journal_vchs
                if not _vch(vch)['$Led_BaseGroup'].isin(income_groups).any()
                and not _vch(vch)['$Particulars'].str.contains(
                    'tds|tcs|round', case=False, na=False).any()
            ]
            jd_rows = []
            for vch, g in _fast_vch_iter(no_income_vchs):
                amt, names = g['amt'], g['name']
                debited  = [s for s in pd.unique(names[amt < 0]) if pd.notna(s)]
                credited = [s for s in pd.unique(names[amt > 0]) if pd.notna(s)]
                party_set = set(debited) | set(credited)
                others   = [s for s in pd.unique(names)
                            if pd.notna(s) and s not in party_set]
                jd_rows.append({
                    'Branch'          : _uniq_join(g['br']) if g['br'] is not None else '',
                    'VoucherNumber'   : _np_first(g['vno']),
                    'Date'            : _np_first(g['date']),
                    'Debited'         : _uniq_join(debited),
                    'Debit_Amount'    : round(float(np.abs(amt[amt < 0]).sum()), 2),
                    'Credited'        : _uniq_join(credited),
                    'Credit_Amount'   : round(float(np.abs(amt[amt > 0]).sum()), 2),
                    'Other_Ledgers'   : _uniq_join(others)
                })
            jd_df = pd.DataFrame(jd_rows) if jd_rows else pd.DataFrame(columns=[
                'Branch', 'VoucherNumber', 'Date', 'Debited', 'Debit_Amount',
                'Credited', 'Credit_Amount', 'Other_Ledgers'])
            results["Journal_Debtors_No_Income"] = jd_df.reset_index(drop=True)

            # Fixed Assets Purchased
            results["Fixed_Assets_Purchased"] = txn_df[
                (txn_df['$Led_BaseGroup'] == 'fixed assets') &
                (pd.to_numeric(txn_df['$Amount'], errors='coerce') < 0)
            ].reset_index(drop=True)

            # Fixed Assets Below 5000
            results["Fixed_Assets_Below_5000"] = txn_df[
                (txn_df['$Led_BaseGroup'] == 'fixed assets') &
                (pd.to_numeric(txn_df['$Amount'], errors='coerce') < 0) &
                (pd.to_numeric(txn_df['$Amount'], errors='coerce').abs() < 5000)
            ].reset_index(drop=True)

            # Cash Payments > 10000 (exclude Contra)
            cash_cr = txn_df[
                (txn_df['$Led_BaseGroup'] == 'cash-in-hand') &
                (pd.to_numeric(txn_df['$Amount'], errors='coerce') > 0) &
                (~txn_df['$VchTypeParent'].isin(['contra']))
            ].copy()
            cash_cr['$Amount'] = pd.to_numeric(cash_cr['$Amount'], errors='coerce')
            cash_cr['$Date']   = cash_cr['$Date'].astype(str).str.strip()

            # Exclude inter-branch transfers — a voucher whose counter-ledger sits
            # under Branch/Divisions is a fund movement between branches, not a
            # 40A(3) cash expense.
            _bd = (txn_df['$Led_BaseGroup'].str.contains('branch', na=False) &
                   txn_df['$Led_BaseGroup'].str.contains('division', na=False))
            _interbranch_vchs = set(txn_df.loc[_bd, '$VoucherId'].unique())
            if _interbranch_vchs:
                cash_cr = cash_cr[~cash_cr['$VoucherId'].isin(_interbranch_vchs)]

            # Single voucher >= 10000
            single_pay_vchs = cash_cr[
                cash_cr['$Amount'] >= 10000]['$VoucherId'].unique()

            # Aggregated same party same day >= 10000 — vectorized: total and
            # max per (date, party) in ONE pass. A group qualifies when the
            # day-total crosses 10000 but no single row in it does (same rule
            # as before, without rescanning cash_cr once per group).
            daily_pay = cash_cr.groupby(
                ['$Date', '$Party_LedName'])['$Amount'].agg(
                    _total='sum', _max='max').reset_index()
            agg_keys = daily_pay[
                (daily_pay['_total'] >= 10000) & (daily_pay['_max'] < 10000)]
            agg_pay_vchs = cash_cr.merge(
                agg_keys[['$Date', '$Party_LedName']],
                on=['$Date', '$Party_LedName'])['$VoucherId'].unique().tolist()
            agg_pay_vchs = list(set(agg_pay_vchs) - set(single_pay_vchs))

            vch_flag_map = {}
            for v in single_pay_vchs:
                vch_flag_map[v] = 'Single Voucher >= 10000'
            for v in agg_pay_vchs:
                vch_flag_map[v] = 'Aggregated Same Party Same Day'

            cp_rows = []
            for vch, g in _fast_vch_iter(vch_flag_map):
                amt, names = g['amt'], g['name']
                iscash = g['grp'] == 'cash-in-hand'
                cp_rows.append({
                    'Branch'       : _uniq_join(g['br']) if g['br'] is not None else '',
                    'VoucherNumber': _np_first(g['vno']),
                    'Date'         : _np_first(g['date']),
                    'VoucherType'  : _np_first(g['vtype']),
                    'Amount'       : round(float(np.abs(np.nan_to_num(amt[iscash])).sum()), 2),
                    'Cash_Ledger'  : _uniq_join(names[iscash]),
                    'Other_Ledgers': _uniq_join(names[~iscash]),
                    'Flag'         : vch_flag_map[vch]
                })
            cp_rows.sort(key=lambda r: r['Flag'] != 'Single Voucher >= 10000')
            cp_df = pd.DataFrame(cp_rows) if cp_rows else pd.DataFrame(columns=[
                'Branch', 'VoucherNumber', 'Date', 'VoucherType', 'Amount',
                'Cash_Ledger', 'Other_Ledgers', 'Flag'])
            results["Cash_Payments_Above_10000"] = cp_df.reset_index(drop=True)

            # Cash Receipts > 20000 (exclude Contra, Sales)
            cash_dr_vchs = txn_df[
                (txn_df['$Led_BaseGroup'] == 'cash-in-hand') &
                (pd.to_numeric(txn_df['$Amount'], errors='coerce') < 0) &
                (~txn_df['$VchTypeParent'].isin(['contra', 'sales']))
            ].copy()
            cash_dr_vchs['$Amount'] = pd.to_numeric(
                cash_dr_vchs['$Amount'], errors='coerce').abs()

            recv_vchs = cash_dr_vchs[
                cash_dr_vchs['$Amount'] >= 20000]['$VoucherId'].unique()

            cr_rows = []
            for vch, g in _fast_vch_iter(recv_vchs):
                amt, names = g['amt'], g['name']
                iscash = g['grp'] == 'cash-in-hand'
                date        = _np_first(g['date'])
                vch_no      = _np_first(g['vno'])
                cash_ledger = _uniq_join(names[iscash])
                amount      = round(float(np.abs(np.nan_to_num(amt[iscash])).sum()), 2)
                others      = _uniq_join(names[~iscash])

                vch_type = _np_first(g['vtype'])
                cr_rows.append({
                    'VoucherNumber': vch_no,
                    'Date'         : date,
                    'VoucherType'  : vch_type,
                    'Amount'       : amount,
                    'Cash_Ledger'  : cash_ledger,
                    'Other_Ledgers': others,
                    'Flag'         : 'Cash Receipt >= 20000'
                })
            cr_df = pd.DataFrame(cr_rows) if cr_rows else pd.DataFrame(columns=[
                'VoucherNumber', 'Date', 'VoucherType', 'Amount',
                'Cash_Ledger', 'Other_Ledgers', 'Flag'])
            results["Cash_Receipts_Above_20000"] = cr_df.reset_index(drop=True)

            # Cash Receipt via Payment entry
            results["Cash_Receipt_Via_Payment"] = txn_df[
                (txn_df['$VchTypeParent'] == 'payment') &
                (txn_df['$Led_BaseGroup'] == 'cash-in-hand') &
                (pd.to_numeric(txn_df['$Amount'], errors='coerce') < 0)
            ].reset_index(drop=True)

            # Cash Payment via Receipt entry
            results["Cash_Payment_Via_Receipt"] = txn_df[
                (txn_df['$VchTypeParent'] == 'receipt') &
                (txn_df['$Led_BaseGroup'] == 'cash-in-hand') &
                (pd.to_numeric(txn_df['$Amount'], errors='coerce') > 0)
            ].reset_index(drop=True)

            # Running Negative Cash Balance — branch-wise (same-name cash ledgers
            # across branches have separate openings and running balances)
            cash_txn = txn_df[txn_df['$Led_BaseGroup'] == 'cash-in-hand'].copy()
            cash_txn['$Amount'] = pd.to_numeric(cash_txn['$Amount'], errors='coerce').fillna(0)
            cash_txn['$Date']   = pd.to_datetime(cash_txn['$Date'], errors='coerce')
            cash_txn['_Br']     = cash_txn['Branch'].astype(str) if _has_branch else ''

            cash_open = df[df['$_PrimaryGroup'] == 'cash-in-hand'].copy()
            cash_open['$OpeningBalance'] = pd.to_numeric(
                cash_open['$OpeningBalance'], errors='coerce').fillna(0)
            cash_open['_Br'] = cash_open['Branch'].astype(str) if 'Branch' in cash_open.columns else ''
            open_map = cash_open.set_index(['_Br', '$Name'])['$OpeningBalance'].to_dict()

            daily = cash_txn.groupby(
                ['_Br', '$Particulars', '$Date'], as_index=False)['$Amount'].sum()
            daily = daily.sort_values(['_Br', '$Particulars', '$Date'])

            running_rows = []
            for (branch, ledger), grp in daily.groupby(['_Br', '$Particulars']):
                opening = open_map.get((branch, ledger), 0) * -1
                balance = opening
                for _, row in grp.iterrows():
                    movement       = row['$Amount'] * -1
                    closing        = balance + movement
                    running_rows.append({
                        'Branch'        : branch,
                        'Ledger'        : ledger,
                        'Opening'       : round(balance, 2),
                        'Date'          : row['$Date'],
                        'Day_Movement'  : round(movement, 2),
                        'Closing'       : round(closing, 2),
                        'Negative_Flag' : 'Negative' if closing < 0 else ''
                    })
                    balance = closing
            rn_df = pd.DataFrame(running_rows)
            if not rn_df.empty:
                results["Running_Negative_Cash"] = rn_df[rn_df['Negative_Flag'] == 'Negative'].reset_index(drop=True)
            else:
                results["Running_Negative_Cash"] = pd.DataFrame(columns=[
                    'Branch', 'Ledger', 'Opening', 'Date', 'Day_Movement', 'Closing', 'Negative_Flag'])

            # Journal in Creditors not hitting Purchase/Expenses
            creditor_parties = set(df[df['$_PrimaryGroup'] == 'sundry creditors']['$Name'].tolist())
            cred_journal_vchs = txn_df[
                (txn_df['$VchTypeParent'] == 'journal') &
                (txn_df['$Party_LedName'].isin(creditor_parties))
            ]['$VoucherId'].unique()

            # One pass: the set of vouchers that DO touch purchase/expense rows,
            # then a set-lookup per candidate (was a full-table scan per voucher).
            _purch_vch_set = set(txn_df.loc[
                txn_df['$Led_BaseGroup'].isin(purchase_expense | {'Duties & Taxes'}),
                '$VoucherId'])
            no_purchase_vchs = [
                vch for vch in cred_journal_vchs if vch not in _purch_vch_set
            ]
            jc_rows = []
            for vch, g in _fast_vch_iter(no_purchase_vchs):
                amt, names = g['amt'], g['name']
                debited  = [s for s in pd.unique(names[amt < 0]) if pd.notna(s)]
                credited = [s for s in pd.unique(names[amt > 0]) if pd.notna(s)]
                party_set = set(debited) | set(credited)
                others   = [s for s in pd.unique(names)
                            if pd.notna(s) and s not in party_set]
                jc_rows.append({
                    'Branch'        : _uniq_join(g['br']) if g['br'] is not None else '',
                    'VoucherNumber' : _np_first(g['vno']),
                    'Date'          : _np_first(g['date']),
                    'Debited'       : _uniq_join(debited),
                    'Debit_Amount'  : round(float(np.abs(amt[amt < 0]).sum()), 2),
                    'Credited'      : _uniq_join(credited),
                    'Credit_Amount' : round(float(np.abs(amt[amt > 0]).sum()), 2),
                    'Other_Ledgers' : _uniq_join(others)
                })
            jc_df = pd.DataFrame(jc_rows) if jc_rows else pd.DataFrame(columns=[
                'Branch', 'VoucherNumber', 'Date', 'Debited', 'Debit_Amount',
                'Credited', 'Credit_Amount', 'Other_Ledgers'])
            results["Journal_Creditors_No_Purchase"] = jc_df.reset_index(drop=True)

            # Creditors with Income Ledgers
            cred_vchs = txn_df[
                txn_df['$Party_LedName'].isin(creditor_parties)
            ]['$VoucherId'].unique()
            # One pass: vouchers that touch income rows, then set-lookups
            # (cred_vchs can be nearly EVERY voucher — this was the single
            # worst quadratic scan on large data).
            _inc_vch_set = set(txn_df.loc[
                txn_df['$Led_BaseGroup'].isin(income_groups), '$VoucherId'])
            income_vchs = [vch for vch in cred_vchs if vch in _inc_vch_set]
            results["Creditors_With_Income"] = txn_df[
                txn_df['$VoucherId'].isin(income_vchs)
            ].reset_index(drop=True)

            # Loan Receipts and Loan Payments
            LOAN_GROUPS = {'loans (liability)', 'secured loans', 'unsecured loans'}

            _loan_mask = (txn_df['$Led_BaseGroup'].isin(LOAN_GROUPS) |
                          txn_df['$Particulars'].str.contains(
                              'secured loan|unsecured loan', case=False, na=False))
            _loan_amt = pd.to_numeric(txn_df['$Amount'], errors='coerce')

            # Counter-side ledgers per voucher (everything that ISN'T the loan
            # ledger) — shown as the "Other_Ledgers" column so the user can see
            # what the loan was repaid to / received from.
            _nonloan = txn_df[~_loan_mask]
            _other_by_vch = _nonloan.groupby('$VoucherId')['$Particulars'].agg(
                lambda s: ' | '.join(sorted({str(v).strip() for v in s.dropna()
                                             if str(v).strip() not in ('', 'nan')})))

            _rep = txn_df[_loan_mask & (_loan_amt < 0)].reset_index(drop=True)
            _rep['Other_Ledgers'] = _rep['$VoucherId'].map(_other_by_vch).fillna('')
            results["Loans_Repayments"] = _rep

            _rcv = txn_df[_loan_mask & (_loan_amt > 0)].reset_index(drop=True)
            _rcv['Other_Ledgers'] = _rcv['$VoucherId'].map(_other_by_vch).fillna('')
            results["Loans_Receipts"] = _rcv
            
            
            # ── 269ST Cash Receipt Violations ────────────────────────────────
            
            cash_recv = txn_df[
                (txn_df['$Led_BaseGroup'] == 'cash-in-hand') &
                (pd.to_numeric(txn_df['$Amount'], errors='coerce') < 0)
            ].copy()
            cash_recv['$Amount'] = pd.to_numeric(
                cash_recv['$Amount'], errors='coerce').abs()
            cash_recv['$Date'] = cash_recv['$Date'].astype(str).str.strip()

            # Exclude blank/ambiguous parties
            cash_recv = cash_recv[
                ~cash_recv['$Party_LedName'].astype(str).str.strip().isin(
                    ['', 'nan', 'None'])
            ]

            # Condition 1: Single transaction >= 2L
            single_2l = cash_recv[
                cash_recv['$Amount'] >= 200000].copy()
            single_2l['Flag'] = 'Single Transaction >= 2L'

            # Condition 2: Same party same day aggregate >= 2L
            daily_recv = cash_recv.groupby(
                ['$Date', '$Party_LedName'], as_index=False)['$Amount'].sum()
            agg_2l = daily_recv[
                (daily_recv['$Amount'] >= 200000) &
                (~daily_recv.apply(
                    lambda r: ((cash_recv['$Date'] == r['$Date']) &
                               (cash_recv['$Party_LedName'] == r['$Party_LedName']) &
                               (cash_recv['$Amount'] >= 200000)).any(), axis=1))
            ].copy()
            agg_2l['Flag'] = 'Aggregated Same Party Same Day >= 2L'

            violations = pd.concat([single_2l, agg_2l], ignore_index=True)
            if violations.empty:
                violations = pd.DataFrame(columns=[
                    '$Date', '$Party_LedName', '$Amount', 'Flag'])
            results["269ST_Cash_Violations"] = violations

            # ── High Value Sales + Cash Cross Reference ───────────────────────
            # Step 1 — Parties with total cash received >= 2L (party-level
            # threshold across all branches, so splits can't dodge the check;
            # output rows are branch-wise for traceability)
            cash_recv['_Br'] = cash_recv['Branch'].astype(str) if _has_branch else ''
            party_cash_total = cash_recv.groupby('$Party_LedName')['$Amount'].sum()
            high_cash_parties = set(
                party_cash_total[party_cash_total >= 200000].index.tolist())

            if high_cash_parties:
                cash_party = cash_recv[
                    cash_recv['$Party_LedName'].isin(high_cash_parties)
                ].groupby(['_Br', '$Party_LedName'], as_index=False)['$Amount'].sum()
                cash_party.columns = ['Branch', 'Party', 'Total_Cash_Received']

                # Step 2 — Sales to those parties (branch-wise)
                sales_txn = txn_df[
                    (txn_df['$VchTypeParent'] == 'sales') &
                    (txn_df['$Party_LedName'].isin(high_cash_parties))
                ].copy()
                sales_txn['$Amount'] = pd.to_numeric(
                    sales_txn['$Amount'], errors='coerce')
                sales_txn['_Br'] = sales_txn['Branch'].astype(str) if _has_branch else ''

                sales_summary = sales_txn.groupby(
                    ['_Br', '$Party_LedName'], as_index=False).agg(
                    No_of_Invoices=('$VoucherId', 'nunique'),
                    Total_Sales_Amount=('$Amount', 'sum')
                ).rename(columns={'_Br': 'Branch', '$Party_LedName': 'Party'})

                # Step 3 — Merge cash + sales (same branch + party)
                result_hv = cash_party.merge(
                    sales_summary, on=['Branch', 'Party'], how='left')
                result_hv['No_of_Invoices']    = result_hv['No_of_Invoices'].fillna(0).astype(int)
                result_hv['Total_Sales_Amount'] = result_hv['Total_Sales_Amount'].fillna(0)
                result_hv['Risk_Flag'] = result_hv['Total_Sales_Amount'].apply(
                    lambda x: 'Review Required' if x > 0 else 'No Sales Found')
                result_hv = result_hv.sort_values(
                    ['Total_Cash_Received'], ascending=False).reset_index(drop=True)
            else:
                result_hv = pd.DataFrame(columns=[
                    'Branch', 'Party', 'Total_Cash_Received',
                    'No_of_Invoices', 'Total_Sales_Amount', 'Risk_Flag'
                ])

            results["HighValue_Sales_Cash_Ref"] = result_hv

            # ── Recurring Monthly Expenses — Missing / Low Months ────────────
            # Expenses whose ledger name matches a "monthly" keyword (rent, EB,
            # salary, interest, ...) are expected every active month. Build a
            # month-wise grid of the spend so blank months (and low months) stand
            # out. Keyword-driven (ledger/expense-wise), not party-wise.
            RECURRING_KEYWORDS = [
                'rent', 'electricity', 'eb', 'power', 'salary', 'salaries',
                'wages', 'staff welfare', 'interest', 'telephone', 'mobile',
                'internet', 'broadband', 'water', 'security', 'housekeeping',
                'rates & taxes', 'lease'
            ]
            EXPENSE_GROUPS_LC = {'direct expenses', 'indirect expenses'}
            _kw_res = [re.compile(r'\b' + re.escape(k) + r'\b', re.IGNORECASE)
                       for k in RECURRING_KEYWORDS]

            exp = txn_df[txn_df['$Led_BaseGroup'].isin(EXPENSE_GROUPS_LC)].copy()
            exp['$Particulars'] = exp['$Particulars'].astype(str).str.strip()
            exp['$Amount'] = pd.to_numeric(exp['$Amount'], errors='coerce').fillna(0)
            exp['$Date']   = pd.to_datetime(exp['$Date'], errors='coerce')
            exp = exp.dropna(subset=['$Date'])
            exp = exp[~exp['$Particulars'].str.lower().isin(['', 'nan'])]
            exp['_Br'] = exp['Branch'].astype(str) if _has_branch else ''

            # Active months = every month the entity has transactions (FY order)
            _all_dates = pd.to_datetime(txn_df['$Date'], errors='coerce').dropna()
            active_periods = sorted(_all_dates.dt.to_period('M').unique())
            month_labels   = [p.strftime('%b-%y') for p in active_periods]
            out_cols = ['Branch', 'Expense Ledger'] + month_labels + \
                       ['Months Present', 'Months Missing', 'Missing Months']

            exp_match = exp[exp['$Particulars'].apply(
                lambda n: any(p.search(n) for p in _kw_res))]

            rec_rows = []
            if not exp_match.empty and active_periods:
                exp_match = exp_match.copy()
                exp_match['_ym'] = exp_match['$Date'].dt.to_period('M')
                monthly = exp_match.groupby(['_Br', '$Particulars', '_ym'])['$Amount'].sum()
                # Expenses are debits (negative $Amount) -> show as positive spend
                monthly = (-monthly).reset_index(name='Amt')
                pivot = monthly.pivot_table(index=['_Br', '$Particulars'], columns='_ym',
                                            values='Amt', aggfunc='sum')
                pivot = pivot.reindex(columns=active_periods)

                for (branch, ledger), prow in pivot.iterrows():
                    present_mask = prow.notna()
                    n_present = int(present_mask.sum())
                    if n_present < 2:        # skip one-off matches, not truly monthly
                        continue
                    missing_lbls = [lbl for lbl, m in
                                    zip(month_labels, present_mask.tolist()) if not m]
                    row = {'Branch': branch, 'Expense Ledger': ledger}
                    for lbl, val in zip(month_labels, prow.tolist()):
                        row[lbl] = round(float(val), 2) if pd.notna(val) else None
                    row['Months Present'] = n_present
                    row['Months Missing'] = len(missing_lbls)
                    row['Missing Months'] = ', '.join(missing_lbls)
                    rec_rows.append(row)

            rec_df = pd.DataFrame(rec_rows, columns=out_cols) if rec_rows \
                else pd.DataFrame(columns=out_cols)
            if not rec_df.empty:
                rec_df = rec_df.sort_values(
                    ['Months Missing', 'Expense Ledger'],
                    ascending=[False, True]).reset_index(drop=True)
            results["Recurring_Monthly_Expenses"] = rec_df

        # ── Opening Balance Mismatch ──────────────────────────────────────────
        def _ob_mismatch(prev, curr):
            """Ledger-wise PY closing vs CY opening (BS items only)."""
            prev, curr = prev.copy(), curr.copy()
            if '$Nature_Led' in prev.columns:
                prev = prev[prev['$Nature_Led'] == 'BS']
            if '$Nature_Led' in curr.columns:
                curr = curr[curr['$Nature_Led'] == 'BS']
            prev['$ClosingBalance'] = pd.to_numeric(prev['$ClosingBalance'], errors='coerce').fillna(0)
            curr['$OpeningBalance'] = pd.to_numeric(curr['$OpeningBalance'], errors='coerce').fillna(0)
            if '$_PrimaryGroup' not in prev.columns:
                prev['$_PrimaryGroup'] = ''
            m = prev[['$Name', '$_PrimaryGroup', '$ClosingBalance']].merge(
                curr[['$Name', '$OpeningBalance']], on='$Name', how='outer')
            # fill numerics with 0 and the text column with '' separately —
            # a blanket fillna(0) injects int 0 into Primary Group (mixed type
            # -> Arrow serialization error in the UI).
            for _c in ('$ClosingBalance', '$OpeningBalance'):
                m[_c] = pd.to_numeric(m[_c], errors='coerce').fillna(0)
            m['$_PrimaryGroup'] = m['$_PrimaryGroup'].fillna('').astype(str)
            m['Difference'] = m['$OpeningBalance'] - m['$ClosingBalance']
            m = m[m['Difference'].abs() > 1]
            return m.rename(columns={
                '$Name': 'Ledger Name', '$_PrimaryGroup': 'Primary Group',
                '$ClosingBalance': 'PrevYear_Closing', '$OpeningBalance': 'CurrYear_Opening'})

        if self.prev_branch_pairs:
            # Group concern: check EACH branch against its own previous year —
            # offsetting errors across branches can't hide.
            frames = []
            for branch, (prev_p, curr_p) in self.prev_branch_pairs.items():
                try:
                    bm = _ob_mismatch(pd.read_csv(prev_p), pd.read_csv(curr_p))
                except Exception:
                    continue
                if not bm.empty:
                    bm.insert(0, 'Branch', branch)
                    frames.append(bm)
            cols = ['Branch', 'Ledger Name', 'Primary Group',
                    'PrevYear_Closing', 'CurrYear_Opening', 'Difference']
            merged_ob = (pd.concat(frames, ignore_index=True)[cols]
                         if frames else pd.DataFrame(columns=cols))
            merged_ob = merged_ob.sort_values(
                ['Branch', 'Difference'], key=lambda s: s.abs() if s.name == 'Difference' else s,
                ascending=[True, False]).reset_index(drop=True)
            results["Opening_Balance_Mismatch"] = merged_ob
        elif self.prev_year_df is not None:
            merged_ob = _ob_mismatch(self.prev_year_df, df)
            merged_ob = merged_ob.sort_values('Difference', key=abs,
                                              ascending=False).reset_index(drop=True)
            results["Opening_Balance_Mismatch"] = merged_ob
        
        DROP_COLS = [
            '$Parent', '$_PrevYearBalance', '$PartyGSTIN1', '$Nature_Led', '$PAN',
            '$VoucherTypeName', '$VoucherId', '$Led_Group', '$Party_Flag'
        ]
        for key in results:
            df_r = results[key]
            df_r = df_r.drop(columns=[c for c in DROP_COLS if c in df_r.columns])
            if '$VoucherNumber' in df_r.columns:
                df_r['$VoucherNumber'] = df_r['$VoucherNumber'].astype(str).str.replace('.0', '', regex=False)
            results[key] = df_r
        return results


def run_ls_engine(conso_masterdata_path, conso_ledgerview_path=None, prev_year_path=None,
                  prev_branch_pairs=None):
    engine = LSEngine(conso_masterdata_path, conso_ledgerview_path, prev_year_path,
                      prev_branch_pairs=prev_branch_pairs)
    engine.load_inputs()
    return engine.run_scrutiny()