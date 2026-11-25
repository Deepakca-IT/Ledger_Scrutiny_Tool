"""
Clause 44 (Form 3CD) — break-up of total expenditure by GST registration status.

Columns produced (per the 3CD format):
  (2) Total expenditure incurred during the year
  (3) Registered: relating to goods/services EXEMPT from GST
  (4) Registered: relating to COMPOSITION-scheme entities
  (5) Registered: relating to OTHER registered entities
  (6) Total payment to registered entities          = (3)+(4)+(5)
  (7) Expenditure relating to entities NOT registered under GST
Check: (2) = (6) + (7).

Data
----
* years/<fy>/consolidated/Transactions_*.csv  — every voucher line (all groups).
* years/<fy>/consolidated/Conso_MasterData.csv — ledger GSTIN ($PartyGSTIN1).

Scope of expenditure (Col 2): debit movements in Purchase Accounts + Direct
Expenses + Indirect Expenses + (optionally) Fixed Assets (capital additions),
excluding Depreciation (non-cash) and any user-listed ledgers. The GST/duty
lines themselves are never part of the expenditure.

Classification per expenditure line
------------------------------------
* Supplier GSTIN = the line's $Led_GSTIN if valid, else the party's GSTIN from
  the master ($Party_LedName -> $PartyGSTIN1).  Valid GSTIN (15 chars) = registered.
* Not registered                       -> Col 7
* Registered + supplier flagged Composition (override) -> Col 4
* Registered + supplier flagged Exempt (override)      -> Col 3
* Registered + voucher HAS a GST line  -> Col 5 (other registered)
* Registered + voucher has NO GST line -> Col 3 (exempt, best-effort)

Composition cannot be detected from Tally, so it relies on the per-supplier
override table (seeded forward each year like the MSME master).
"""

import os
import json
import pandas as pd
import paths

# Tally base groups (lower-cased) that make up "expenditure".
_REVENUE_GROUPS = {"purchase accounts", "direct expenses", "indirect expenses"}
_CAPITAL_GROUP = "fixed assets"
# GST ledger keywords — only checked on 'Duties & Taxes' lines (so TDS is ignored).
_GST_KEYWORDS = ("cgst", "sgst", "igst", "utgst", "cess", "gst")
_DEPR_KEYWORDS = ("deprecia",)

# Ledger-name keywords whose lines are NOT a GST "supply" and are excluded from
# total expenditure (Col 2). Editable per-company in the UI; this is the seed.
_DEFAULT_EXCLUDE_KEYWORDS = [
    # Employee costs (employer-employee — Schedule III, not a supply)
    "salary", "salaries", "wage", "wages", "bonus", "gratuity", "provident",
    "esi", "staff welfare", "staff cost", "employee benefit", "remuneration",
    "stipend", "leave encash", "ex gratia", "ex-gratia",
    # Statutory levies & taxes (government levies, not a vendor supply)
    "rates and taxes", "rates & taxes", "professional tax", "property tax",
    "municipal tax", "roc", "late fee", "penalty", "penalties", "stamp duty",
    "government fee", "govt fee",
]

# "Review" = registered supplier, no GST line on the voucher → NOT auto-classified
# into 3/4/5; user decides per supplier. Excluded from registered totals until set.
REVIEW_CATEGORY = "Review"
CATEGORY_OPTS = ["Review", "Other registered", "Exempt", "Composition"]
DEFAULT_CATEGORY = "Other registered"


# ── paths ────────────────────────────────────────────────────────────────────
def suppliers_path(company, fy):
    return paths.config_path(company, fy, "clause44_suppliers.json")

def config_path(company, fy):
    return paths.config_path(company, fy, "clause44_config.json")

def _conso_dir(company, fy):
    return paths.consolidated_dir(company, fy)


# ── config (scope options) ───────────────────────────────────────────────────
def load_config(company, fy):
    p = config_path(company, fy)
    data = {"include_capital": True, "exclude_ledgers": [],
            "exclude_keywords": list(_DEFAULT_EXCLUDE_KEYWORDS)}
    if p.exists():
        try:
            saved = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(saved, dict):
                data.update(saved)   # a saved file without 'exclude_keywords' keeps the seed
        except Exception:
            pass
    data["include_capital"] = bool(data.get("include_capital", True))
    if not isinstance(data.get("exclude_ledgers"), list):
        data["exclude_ledgers"] = []
    if not isinstance(data.get("exclude_keywords"), list):
        data["exclude_keywords"] = list(_DEFAULT_EXCLUDE_KEYWORDS)
    return data

def save_config(company, fy, include_capital, exclude_ledgers, exclude_keywords=None):
    payload = {"include_capital": bool(include_capital),
               "exclude_ledgers": list(exclude_ledgers or [])}
    payload["exclude_keywords"] = (list(_DEFAULT_EXCLUDE_KEYWORDS)
                                   if exclude_keywords is None else list(exclude_keywords))
    paths.atomic_write_json(config_path(company, fy), payload)


# ── supplier override (party -> category) ────────────────────────────────────
def load_suppliers(company, fy):
    p = suppliers_path(company, fy)
    if p.exists():
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
            return d if isinstance(d, dict) else {}
        except Exception:
            return {}
    return {}

def save_suppliers(company, fy, mapping):
    paths.atomic_write_json(suppliers_path(company, fy), mapping or {})

def seed_suppliers_from_prev(company, fy, prev_fy):
    """Carry the previous year's supplier categories forward (user reviews)."""
    cur = load_suppliers(company, fy)
    if cur:
        return cur, False
    if prev_fy:
        prev = load_suppliers(company, prev_fy)
        if prev:
            return dict(prev), True
    return {}, False


# ── data ─────────────────────────────────────────────────────────────────────
def is_valid_gstin(s):
    s = str(s or "").strip()
    return len(s) == 15 and s.isalnum()

def _load_txn(company, fy):
    d = _conso_dir(company, fy)
    if not d.exists():
        return pd.DataFrame()
    frames = []
    for f in sorted(d.glob("Transactions_*.csv")):
        try:
            frames.append(pd.read_csv(f))
        except Exception:
            continue
    if not frames:
        return pd.DataFrame()
    t = pd.concat(frames, ignore_index=True)
    t.columns = [c.strip() for c in t.columns]
    return t

def _master_gstin_map(company, fy):
    p = _conso_dir(company, fy) / "Conso_MasterData.csv"
    if not p.exists():
        return {}
    try:
        m = pd.read_csv(p)
        m.columns = [c.strip() for c in m.columns]
        if "$Name" not in m.columns or "$PartyGSTIN1" not in m.columns:
            return {}
        return {str(n).strip(): str(g).strip()
                for n, g in zip(m["$Name"], m["$PartyGSTIN1"])}
    except Exception:
        return {}


def registered_suppliers(company, fy):
    """DataFrame of registered suppliers appearing in expenditure (Party, GSTIN)
    — used to seed the override editor."""
    res = compute(company, fy)
    return res["registered_suppliers"]


# ── core ─────────────────────────────────────────────────────────────────────
def compute(company, fy, suppliers=None, include_capital=True, exclude_ledgers=None,
            exclude_keywords=None):
    """Returns dict: summary, by_head (DataFrame), no_gstin (DataFrame),
    exempt_detail, review_detail, registered_suppliers (DataFrame), recon (bool)."""
    blank = {
        "summary": {k: 0.0 for k in ("total", "exempt", "composition", "other",
                                     "review", "registered", "not_registered",
                                     "books_total", "excluded")},
        "by_head": pd.DataFrame(),
        "no_gstin": pd.DataFrame(),
        "exempt_detail": pd.DataFrame(),
        "review_detail": pd.DataFrame(columns=["Party", "GSTIN", "Amount"]),
        "registered_suppliers": pd.DataFrame(columns=["Party", "GSTIN", "Category"]),
        "recon_table": pd.DataFrame(columns=["Particulars", "Amount"]),
        "excluded_detail": pd.DataFrame(columns=["Ledger", "Base Group", "Reason", "Amount"]),
        "recon": True,
    }
    txn = _load_txn(company, fy)
    if txn.empty or "$Led_BaseGroup" not in txn.columns:
        return blank

    suppliers = suppliers or {}
    exclude = {str(x).strip().lower() for x in (exclude_ledgers or [])}
    kw = [str(k).strip().lower() for k in (exclude_keywords or []) if str(k).strip()]
    base = txn["$Led_BaseGroup"].astype(str).str.strip().str.lower()

    scope = set(_REVENUE_GROUPS)
    if include_capital:
        scope.add(_CAPITAL_GROUP)

    exp_scope = txn[base.isin(scope)].copy()
    if exp_scope.empty:
        return blank
    # debit positive (expense/purchase/asset debits are stored negative)
    exp_scope["_amt"] = -pd.to_numeric(exp_scope["$Amount"], errors="coerce").fillna(0.0)
    _bg = exp_scope["$Led_BaseGroup"].astype(str).str.strip().str.lower()
    led_l = exp_scope["$Particulars"].astype(str).str.strip().str.lower()

    # Why each line is excluded (priority: depreciation > specific ledger > keyword).
    depr_mask = led_l.apply(lambda n: any(k in n for k in _DEPR_KEYWORDS))
    ledger_mask = led_l.isin(exclude)
    kw_mask = (led_l.apply(lambda n: any(k in n for k in kw)) if kw
               else pd.Series(False, index=exp_scope.index))
    reasons = pd.Series("", index=exp_scope.index)
    reasons[kw_mask] = "Employee / statutory (keyword)"
    reasons[ledger_mask] = "Specific ledger excluded"
    reasons[depr_mask] = "Depreciation"

    # ── Reconciliation figures (books → Clause 44 Col 2) ───────────────────────
    gross_rev = round(float(exp_scope.loc[_bg.isin(_REVENUE_GROUPS), "_amt"].sum()), 2)
    gross_cap = round(float(exp_scope.loc[_bg == _CAPITAL_GROUP, "_amt"].sum()), 2)
    excl_depr = round(float(exp_scope.loc[reasons == "Depreciation", "_amt"].sum()), 2)
    excl_ledger = round(float(exp_scope.loc[reasons == "Specific ledger excluded", "_amt"].sum()), 2)
    excl_kw = round(float(exp_scope.loc[reasons == "Employee / statutory (keyword)", "_amt"].sum()), 2)

    exd = exp_scope[reasons != ""].copy()
    if not exd.empty:
        exd["Reason"] = reasons[reasons != ""]
        excluded_detail = (exd.groupby(["$Particulars", "$Led_BaseGroup", "Reason"],
                                       as_index=False)["_amt"].sum()
                           .rename(columns={"$Particulars": "Ledger",
                                            "$Led_BaseGroup": "Base Group", "_amt": "Amount"})
                           .sort_values("Amount", ascending=False))
    else:
        excluded_detail = pd.DataFrame(columns=["Ledger", "Base Group", "Reason", "Amount"])

    exp = exp_scope[reasons == ""].copy()
    if exp.empty:
        return blank
    exp["_party"] = exp["$Party_LedName"].astype(str).str.strip() if "$Party_LedName" in exp.columns else ""

    gmap = _master_gstin_map(company, fy)
    led_gstin = exp["$Led_GSTIN"].astype(str).str.strip() if "$Led_GSTIN" in exp.columns else pd.Series([""] * len(exp), index=exp.index)

    def _resolve_gstin(i):
        g = led_gstin.iloc[i] if i < len(led_gstin) else ""
        if is_valid_gstin(g):
            return g
        return str(gmap.get(exp["_party"].iloc[i], "")).strip()
    exp = exp.reset_index(drop=True)
    led_gstin = led_gstin.reset_index(drop=True)
    exp["_gstin"] = [_resolve_gstin(i) for i in range(len(exp))]
    exp["_reg"] = exp["_gstin"].apply(is_valid_gstin)

    # vouchers that carry a GST line
    vid = "$VoucherId" if "$VoucherId" in txn.columns else "$VoucherNumber"
    if vid in txn.columns:
        gst_mask = (base == "duties & taxes") & txn["$Particulars"].astype(str).str.lower().apply(
            lambda n: any(k in n for k in _GST_KEYWORDS))
        gst_vouchers = set(txn.loc[gst_mask, vid].astype(str).unique())
        exp["_gst_vch"] = exp[vid].astype(str).isin(gst_vouchers) if vid in exp.columns else False
    else:
        exp["_gst_vch"] = False

    def _bucket(row):
        if not row["_reg"]:
            return "not_registered"
        cat = suppliers.get(row["_party"])
        if cat == "Composition":
            return "composition"
        if cat == "Exempt":
            return "exempt"
        if cat == "Other registered":
            return "other"
        # No explicit decision yet: a voucher that charged GST is clearly "other
        # registered (5)"; one with NO GST line is left for manual review (not put
        # into 3/4/5 until the user classifies the supplier).
        return "other" if row["_gst_vch"] else "review"
    exp["_bucket"] = exp.apply(_bucket, axis=1)

    def _s(b):
        return round(float(exp.loc[exp["_bucket"] == b, "_amt"].sum()), 2)
    exempt = _s("exempt"); comp = _s("composition"); other = _s("other")
    review = _s("review"); notreg = _s("not_registered")
    registered = round(exempt + comp + other, 2)             # Col 6 (classified only)
    total = round(registered + review + notreg, 2)           # Col 2 (full expenditure)
    books_total = round(gross_rev + gross_cap, 2)
    excluded_total = round(excl_depr + excl_kw + excl_ledger, 2)
    summary = {"total": total, "exempt": exempt, "composition": comp,
               "other": other, "review": review,
               "registered": registered, "not_registered": notreg,
               "books_total": books_total, "excluded": excluded_total}

    # ── Reconciliation: total expenses per books → Clause 44 Col 2 ──────────────
    recon_rows = [("Purchase + Direct + Indirect Expenses (per books)", gross_rev)]
    if include_capital:
        recon_rows.append(("Add: Fixed Asset additions (capital)", gross_cap))
    recon_rows += [
        ("Less: Depreciation", -excl_depr),
        ("Less: Employee / statutory exclusions (keyword)", -excl_kw),
        ("Less: Specific ledgers excluded", -excl_ledger),
        ("Total expenditure considered — Clause 44 (2)", total),
    ]
    recon_table = pd.DataFrame(recon_rows, columns=["Particulars", "Amount"])

    # ── by expenditure head (working-paper detail) ─────────────────────────────
    piv = exp.pivot_table(index="$Particulars", columns="_bucket", values="_amt",
                          aggfunc="sum", fill_value=0.0)
    for b in ("exempt", "composition", "other", "review", "not_registered"):
        if b not in piv.columns:
            piv[b] = 0.0
    piv["registered"] = piv["exempt"] + piv["composition"] + piv["other"]
    piv["total"] = piv["registered"] + piv["review"] + piv["not_registered"]
    piv = piv[piv["total"].round(2) != 0].sort_values("total", ascending=False)
    by_head = piv.reset_index().rename(columns={
        "$Particulars": "Expenditure Head", "total": "Total (2)", "exempt": "Exempt (3)",
        "composition": "Composition (4)", "other": "Other registered (5)",
        "registered": "Total registered (6)", "review": "Under review",
        "not_registered": "Not registered (7)"})
    # each ledger's base group (Purchase Accounts / Direct / Indirect / Fixed Assets)
    _bgmap = exp.groupby("$Particulars")["$Led_BaseGroup"].first()
    by_head.insert(0, "Base Group", by_head["Expenditure Head"].map(_bgmap))
    by_head.insert(0, "S.No", range(1, len(by_head) + 1))
    by_head = by_head[["S.No", "Base Group", "Expenditure Head", "Total (2)", "Exempt (3)",
                       "Composition (4)", "Other registered (5)",
                       "Total registered (6)", "Under review", "Not registered (7)"]]

    # ── review panels ──────────────────────────────────────────────────────────
    nr = exp[~exp["_reg"]]
    no_gstin = (nr.groupby("_party", as_index=False)["_amt"].sum()
                .rename(columns={"_party": "Party", "_amt": "Amount"})
                .sort_values("Amount", ascending=False)) if not nr.empty else \
        pd.DataFrame(columns=["Party", "Amount"])

    ex = exp[exp["_bucket"] == "exempt"]
    exempt_detail = (ex.groupby(["_party", "_gstin"], as_index=False)["_amt"].sum()
                     .rename(columns={"_party": "Party", "_gstin": "GSTIN", "_amt": "Amount"})
                     .sort_values("Amount", ascending=False)) if not ex.empty else \
        pd.DataFrame(columns=["Party", "GSTIN", "Amount"])

    rv = exp[exp["_bucket"] == "review"]
    review_detail = (rv.groupby(["_party", "_gstin"], as_index=False)["_amt"].sum()
                     .rename(columns={"_party": "Party", "_gstin": "GSTIN", "_amt": "Amount"})
                     .sort_values("Amount", ascending=False)) if not rv.empty else \
        pd.DataFrame(columns=["Party", "GSTIN", "Amount"])

    reg = exp[exp["_reg"]]
    # Per-supplier default for the override editor: a supplier whose vouchers
    # charged GST defaults to "Other registered"; one that never did defaults to
    # "Review" (so it shows up for a manual decision). An explicit saved override wins.
    party_has_gst = reg.groupby("_party")["_gst_vch"].any().to_dict() if not reg.empty else {}
    reg_sup = (reg.groupby(["_party", "_gstin"], as_index=False)["_amt"].sum()
               .rename(columns={"_party": "Party", "_gstin": "GSTIN", "_amt": "Amount"})
               .sort_values("Amount", ascending=False)) if not reg.empty else \
        pd.DataFrame(columns=["Party", "GSTIN", "Amount"])
    if not reg_sup.empty:
        reg_sup["Category"] = reg_sup["Party"].map(
            lambda p: suppliers.get(p) or (DEFAULT_CATEGORY if party_has_gst.get(p)
                                           else REVIEW_CATEGORY))

    return {"summary": summary, "by_head": by_head, "no_gstin": no_gstin,
            "exempt_detail": exempt_detail, "review_detail": review_detail,
            "registered_suppliers": reg_sup,
            "recon_table": recon_table, "excluded_detail": excluded_detail,
            # 3CD identity (2)=(6)+(7) holds only once nothing is left under review.
            "recon": abs(review) < 1.0}


# ── Excel export ─────────────────────────────────────────────────────────────
_INR = r'[>=10000000]##\,##\,##\,##0.00;[>=100000]##\,##\,##0.00;##,##0.00'

def build_excel(company, fy, res):
    import io
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
    from openpyxl.utils import get_column_letter

    s = res["summary"]
    clause = pd.DataFrame([{
        "S.No": 1,
        "Total expenditure (2)": s["total"],
        "Exempt (3)": s["exempt"],
        "Composition (4)": s["composition"],
        "Other registered (5)": s["other"],
        "Total to registered (6)": s["registered"],
        "Under review (unclassified)": s.get("review", 0.0),
        "Not registered (7)": s["not_registered"],
    }])

    out = io.BytesIO()
    with pd.ExcelWriter(out, engine="openpyxl") as xw:
        clause.to_excel(xw, index=False, sheet_name="Clause 44", startrow=1)
        res.get("recon_table", pd.DataFrame()).to_excel(
            xw, index=False, sheet_name="Reconciliation")
        res["by_head"].to_excel(xw, index=False, sheet_name="By Expenditure Head")
        res.get("excluded_detail", pd.DataFrame()).to_excel(
            xw, index=False, sheet_name="Excluded items")
        res["no_gstin"].to_excel(xw, index=False, sheet_name="No GSTIN (review)")
        res.get("review_detail", pd.DataFrame()).to_excel(
            xw, index=False, sheet_name="Under review")
        res["exempt_detail"].to_excel(xw, index=False, sheet_name="Exempt (review)")

        wb = xw.book
        hdr_fill = PatternFill("solid", fgColor="1F4E79")
        hdr_font = Font(bold=True, color="FFFFFF", name="Segoe UI", size=10)
        thin = Side(style="thin", color="D9D9D9")
        border = Border(left=thin, right=thin, top=thin, bottom=thin)

        ws = wb["Clause 44"]
        ws["A1"] = f"Clause 44 — Break-up of total expenditure (FY {fy}) — {company}"
        ws["A1"].font = Font(bold=True, size=12, color="1F4E79", name="Segoe UI")
        for ws_name in ("Clause 44", "Reconciliation", "By Expenditure Head",
                        "Excluded items", "No GSTIN (review)",
                        "Under review", "Exempt (review)"):
            w = wb[ws_name]
            hdr_row = 2 if ws_name == "Clause 44" else 1
            for cell in w[hdr_row]:
                if cell.value is not None:
                    cell.fill = hdr_fill; cell.font = hdr_font
                    cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
            for row in w.iter_rows(min_row=hdr_row + 1):
                for cell in row:
                    cell.border = border
                    if isinstance(cell.value, (int, float)) and w.cell(row=hdr_row, column=cell.column).value not in ("S.No",):
                        cell.number_format = _INR
            for col in w.columns:
                ln = max((len(str(c.value)) if c.value is not None else 0) for c in col)
                w.column_dimensions[get_column_letter(col[0].column)].width = min(max(ln + 3, 11), 42)
            w.freeze_panes = w.cell(row=hdr_row + 1, column=1)
    out.seek(0)
    return out
