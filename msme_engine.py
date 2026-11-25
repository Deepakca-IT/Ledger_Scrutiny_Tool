"""
Section 43B(h) — MSME delayed-payment disallowance working paper.

Logic
-----
* Universe = sundry creditors with a CREDIT (payable) balance at year end.
* For each such creditor we rebuild a bill-wise ageing from its own ledger
  movements (transactions where $Particulars == creditor and base group is
  Sundry Creditors):
      - positive $Amount  -> a BILL (purchase / credit)
      - negative $Amount  -> a REDUCTION (payment, debit note, journal debit)
* FIFO: ALL reductions are applied against the OLDEST items first — opening
  balance first, then bills in date order. Whatever remains unpaid (= the
  year-end credit balance) is the pending-bill list, each with its bill date.
* 43B(h) disallowance applies ONLY when the supplier is:
      MSME registered  AND  (Micro or Small)  AND  (Manufacturer or Service).
  Medium enterprises and Traders are excluded.
* Time limit: 45 days when a written agreement exists, else 15 days.
  A pending bill is DISALLOWED if  bill date + limit  <=  31-Mar of the FY.
  If the limit expires after year end, it is "Within time" (watch next year).

Year flow
---------
The pending-bill list (with dates) is SAVED per FY. Next year, when the
previous FY is set, those saved bills become the dated OPENING bills — so the
carried-forward amounts become date-testable. This only happens when the
creditor's current opening balance reconciles with last year's saved closing
(else we fall back to a single undated opening line and the user decides).
"""

import os
import json
import pandas as pd
from pathlib import Path
import paths


CREDITOR_GROUP = "sundry creditors"
DEFAULT_AGREEMENT = "Yes"          # 45-day default in prefilled master
CLASS_OPTS  = ["", "Micro", "Small", "Medium"]
TYPE_OPTS   = ["", "Manufacturer", "Service", "Trader"]
YESNO       = ["", "Yes", "No"]

# Status for bills whose 15/45-day limit expires AFTER year end — not disallowed
# this year (prevailing view); the user verifies actual payment in next-year books.
VERIFY_LABEL = "Verify due paid-with next year ledger"
UNDATED_LABEL = "Undated opening (verify)"


def verdict_conclusion(v):
    """Map a next-year verify status -> working-paper conclusion."""
    v = str(v or "")
    if v == "Paid within due date":
        return "Not disallowed (paid in time)"
    if v == "Paid after due date":
        return "Disallow (paid late) — review"
    if v == "Not paid by due date":
        return "Disallow (not paid) — review"
    if v == "Manual (no bill date)":
        return "Verify manually"
    return "Pending verification"


# ── paths (year-scoped via paths.py) ─────────────────────────────────────────
def _conso_master(company, fy):
    return paths.consolidated_dir(company, fy) / "Conso_MasterData.csv"


def _txn_files(company, fy):
    d = paths.consolidated_dir(company, fy)
    if not d.exists():
        return []
    return sorted(d.glob("Transactions_*.csv"))


def _msme_dir(company, fy):
    p = paths.msme_dir(company, fy)
    p.mkdir(parents=True, exist_ok=True)
    return p


def master_path(company, fy):
    return _msme_dir(company, fy) / "msme_master.json"


def pending_path(company, fy):
    return _msme_dir(company, fy) / "msme_pending.json"


def config_path(company, fy):
    return _msme_dir(company, fy) / "config.json"


def verify_path(company, fy):
    return _msme_dir(company, fy) / "msme_verify.csv"


# ── small helpers ──────────────────────────────────────────────────────────
def fy_end_date(fy):
    """'2025-26' -> Timestamp(2026-03-31)."""
    try:
        start = int(str(fy).split("-")[0])
        return pd.Timestamp(year=start + 1, month=3, day=31)
    except Exception:
        return None


def default_record():
    return {
        "registered": "",
        "classification": "",
        "type": "",
        "agreement": DEFAULT_AGREEMENT,
        "udyam": "",
    }


def days_limit(rec):
    return 45 if str(rec.get("agreement", "")).strip().lower() == "yes" else 15


def is_applicable(rec):
    return (
        str(rec.get("registered", "")).strip().lower() == "yes"
        and str(rec.get("classification", "")).strip().capitalize() in ("Micro", "Small")
        and str(rec.get("type", "")).strip().capitalize() in ("Manufacturer", "Service")
    )


def exclusion_reason(rec):
    """Why 43B(h) does NOT apply (None if it applies)."""
    reg = str(rec.get("registered", "")).strip().lower()
    cls = str(rec.get("classification", "")).strip().capitalize()
    typ = str(rec.get("type", "")).strip().capitalize()
    if reg in ("", "nan"):
        return "MSME status not provided"
    if reg == "no":
        return "Not MSME registered"
    if cls == "Medium":
        return "Medium enterprise"
    if typ == "Trader":
        return "Trader"
    if cls not in ("Micro", "Small"):
        return "Classification not provided"
    if typ not in ("Manufacturer", "Service"):
        return "Supplier type not provided"
    return None


# ── config (last-used FY selection) ────────────────────────────────────────
def load_config(company, fy):
    p = config_path(company, fy)
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"current_fy": "", "previous_fy": ""}


def save_config(company, fy, current_fy, previous_fy):
    paths.atomic_write_json(config_path(company, fy),
                            {"current_fy": current_fy or "", "previous_fy": previous_fy or ""})


# ── master (supplier MSME details) ─────────────────────────────────────────
def load_master(company, fy):
    p = master_path(company, fy)
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def save_master(company, fy, mapping):
    paths.atomic_write_json(master_path(company, fy), mapping)


def seed_master_from_prev(company, fy, prev_fy):
    """If current FY master is empty and a previous FY master exists, copy it
    forward as the default (user reviews — vendor category can change yearly).
    Returns (mapping, seeded_bool)."""
    cur = load_master(company, fy)
    if cur:
        return cur, False
    if prev_fy:
        prev = load_master(company, prev_fy)
        if prev:
            return {k: dict(v) for k, v in prev.items()}, True
    return {}, False


# ── pending bills (closing -> next year opening) ───────────────────────────
def load_pending(company, fy):
    p = pending_path(company, fy)
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def save_pending(company, fy, mapping):
    paths.atomic_write_json(pending_path(company, fy), mapping)


# ── universe: creditors with credit balance ────────────────────────────────
def creditors_with_credit_balance(company, fy):
    """DataFrame: Party, Opening, Closing, GSTIN, Branch  (credit balance > 0).

    For a group concern the same supplier can appear in several branches; rows
    are aggregated by party — one PAN = one supplier for 43B(h) — with Opening
    and Closing SUMMED and Branch listing every branch the supplier appears in.
    Aggregating also prevents the same party being processed twice (which would
    double-count its bills, since transactions are pooled by party name)."""
    cols = ["Party", "Opening", "Closing", "GSTIN", "Branch"]
    p = _conso_master(company, fy)
    if not p.exists():
        return pd.DataFrame(columns=cols)
    m = pd.read_csv(p)
    m.columns = [c.strip() for c in m.columns]
    m["$_PrimaryGroup"] = m["$_PrimaryGroup"].astype(str).str.strip().str.lower()
    m["$OpeningBalance"] = pd.to_numeric(m["$OpeningBalance"], errors="coerce").fillna(0)
    m["$ClosingBalance"] = pd.to_numeric(m["$ClosingBalance"], errors="coerce").fillna(0)
    cr = m[m["$_PrimaryGroup"] == CREDITOR_GROUP].copy()
    if cr.empty:
        return pd.DataFrame(columns=cols)
    cr["GSTIN"] = cr["$PartyGSTIN1"] if "$PartyGSTIN1" in cr.columns else ""
    cr["Branch"] = (cr["Branch"].astype(str).str.strip()
                    if "Branch" in cr.columns else "")
    agg = cr.groupby("$Name", as_index=False).agg(
        Opening=("$OpeningBalance", "sum"),
        Closing=("$ClosingBalance", "sum"),
        GSTIN=("GSTIN", "first"),
        Branch=("Branch", lambda s: ", ".join(
            sorted({x for x in s if x and x.lower() != "nan"}))),
    ).rename(columns={"$Name": "Party"})
    out = agg[agg["Closing"] > 0].copy()
    return out.sort_values("Closing", ascending=False).reset_index(drop=True)


# ── FIFO core ──────────────────────────────────────────────────────────────
def _fifo_unpaid(opening_bills, year_bills, reductions_total):
    """Apply reductions to the oldest items first (opening, then bills by date).
    Returns the remaining unpaid items, each {date, amount, source}."""
    queue = list(opening_bills) + list(year_bills)
    rem = round(reductions_total, 2)
    out = []
    for b in queue:
        amt = round(b["amount"], 2)
        if amt <= 0:
            continue
        if rem >= amt:
            rem = round(rem - amt, 2)
            continue
        out.append({"date": b.get("date"), "amount": round(amt - rem, 2),
                    "source": b.get("source", "Bill")})
        rem = 0.0
    return out


def _load_all_txn(company, fy):
    frames = []
    for f in _txn_files(company, fy):
        try:
            frames.append(pd.read_csv(f))
        except Exception:
            continue
    if not frames:
        return pd.DataFrame()
    t = pd.concat(frames, ignore_index=True)
    t.columns = [c.strip() for c in t.columns]
    return t


def compute(company, fy, prev_fy=None):
    """Returns dict:
       working   -> DataFrame (applicable creditors, bill-wise disallowance)
       excluded  -> DataFrame (Party, Closing, Reason)
       undated   -> DataFrame (undated opening lines for applicable creditors)
       pending   -> dict to save (this FY closing pending bills, all creditors)
       summary   -> dict of totals
       recon     -> list of party names whose opening did NOT reconcile with PY
    """
    cr = creditors_with_credit_balance(company, fy)
    master = load_master(company, fy)
    prev_pending = load_pending(company, prev_fy) if prev_fy else {}
    ye = fy_end_date(fy)

    txn = _load_all_txn(company, fy)
    grouped = {}
    if not txn.empty and "$Particulars" in txn.columns:
        names = set(cr["Party"].tolist())
        base = txn["$Led_BaseGroup"].astype(str).str.strip().str.lower() \
            if "$Led_BaseGroup" in txn.columns else None
        sub = txn[txn["$Particulars"].isin(names)].copy()
        if base is not None:
            sub = sub[base.loc[sub.index] == CREDITOR_GROUP]
        sub["$Amount"] = pd.to_numeric(sub["$Amount"], errors="coerce").fillna(0)
        sub["$Date"] = pd.to_datetime(sub["$Date"], errors="coerce")
        for nm, g in sub.groupby("$Particulars"):
            grouped[nm] = g

    work_rows, excl_rows = [], []
    pending_out, recon_fail = {}, []
    tot_disallow = tot_within = tot_undated = 0.0

    for _, row in cr.iterrows():
        party = row["Party"]
        branch = str(row.get("Branch", "") or "")
        opening = float(row["Opening"])
        rec = master.get(party, default_record())

        # --- opening bills (dated carry-forward, else undated lump) ---
        reductions = 0.0
        opening_bills = []
        pp = prev_pending.get(party)
        if pp:
            pp_total = round(sum(float(b.get("amount", 0)) for b in pp), 2)
            if abs(pp_total - round(opening, 2)) <= 1:
                opening_bills = [{"date": b.get("date"), "amount": float(b.get("amount", 0)),
                                  "source": "Opening (b/f)"} for b in pp]
            else:
                recon_fail.append(party)
        if not opening_bills:
            if opening > 0:
                opening_bills = [{"date": None, "amount": opening, "source": "Opening (undated)"}]
            elif opening < 0:
                reductions += abs(opening)   # debit opening = advance -> a reduction

        # --- current-year movements ---
        g = grouped.get(party)
        year_bills = []
        if g is not None and not g.empty:
            for _, ln in g.sort_values("$Date").iterrows():
                amt = float(ln["$Amount"])
                if amt > 0:
                    d = ln["$Date"]
                    year_bills.append({
                        "date": d.strftime("%Y-%m-%d") if pd.notna(d) else None,
                        "amount": amt, "source": "Bill"})
                elif amt < 0:
                    reductions += abs(amt)

        # date-sort year bills (None last)
        year_bills.sort(key=lambda b: (b["date"] is None, b["date"] or ""))

        unpaid = _fifo_unpaid(opening_bills, year_bills, reductions)
        pending_out[party] = [{"date": u["date"], "amount": u["amount"]} for u in unpaid]

        reason = exclusion_reason(rec)
        if reason is not None:
            excl_rows.append({"Branch": branch, "Party": party,
                              "Closing": round(float(row["Closing"]), 2),
                              "Reason": reason})
            continue

        # applicable -> build bill lines (bill id = party#index in pending,
        # so the next-year verdict can be merged back exactly).
        limit = days_limit(rec)
        for i, u in enumerate(unpaid):
            bid = f"{party}#{i}"
            amt = u["amount"]
            if not u["date"]:
                work_rows.append({
                    "_bid": bid, "Branch": branch, "Party": party,
                    "Class": rec.get("classification", ""),
                    "Type": rec.get("type", ""),
                    "Bill Date": "", "Days": limit, "Due Date": "",
                    "Age (days)": "", "Unpaid Amount": amt,
                    "Status": UNDATED_LABEL})
                tot_undated += amt
                continue
            bd = pd.to_datetime(u["date"], errors="coerce")
            due = bd + pd.Timedelta(days=limit) if pd.notna(bd) else pd.NaT
            age = (ye - bd).days if (ye is not None and pd.notna(bd)) else None
            disallowed = (ye is not None and pd.notna(due) and due <= ye)
            if disallowed:
                tot_disallow += amt
            else:
                tot_within += amt
            work_rows.append({
                "_bid": bid,
                "Branch": branch,
                "Party": party,
                "Class": rec.get("classification", ""),
                "Type": rec.get("type", ""),
                "Bill Date": bd.strftime("%d-%m-%Y") if pd.notna(bd) else "",
                "Days": limit,
                "Due Date": due.strftime("%d-%m-%Y") if pd.notna(due) else "",
                "Age (days)": age if age is not None else "",
                "Unpaid Amount": amt,
                "Status": "Disallowed" if disallowed else VERIFY_LABEL,
            })

    work_df = pd.DataFrame(work_rows, columns=[
        "_bid", "Branch", "Party", "Class", "Type", "Bill Date", "Days", "Due Date",
        "Age (days)", "Unpaid Amount", "Status"])
    if not work_df.empty:
        work_df = work_df.sort_values(
            ["Status", "Branch", "Party", "Bill Date"],
            ascending=[True, True, True, True]).reset_index(drop=True)
    excl_df = pd.DataFrame(excl_rows, columns=["Branch", "Party", "Closing", "Reason"])
    if not excl_df.empty:
        excl_df = excl_df.sort_values("Closing", ascending=False).reset_index(drop=True)

    return {
        "working": work_df,
        "excluded": excl_df,
        "pending": pending_out,
        "summary": {
            "disallowed": round(tot_disallow, 2),
            "within_time": round(tot_within, 2),
            "undated": round(tot_undated, 2),
            "applicable_parties": work_df["Party"].nunique() if not work_df.empty else 0,
            "excluded_parties": len(excl_df),
        },
        "recon": recon_fail,
    }


# ── bulk template (export creditor list + MSME columns) ────────────────────
def build_template_df(company, fy):
    cr = creditors_with_credit_balance(company, fy)
    master = load_master(company, fy)
    rows = []
    for _, r in cr.iterrows():
        rec = master.get(r["Party"], default_record())
        rows.append({
            "Branch": r.get("Branch", ""),
            "Party": r["Party"],
            "Closing Balance": round(float(r["Closing"]), 2),
            "GSTIN": r.get("GSTIN", ""),
            "Registered (Yes/No)": rec.get("registered", ""),
            "Classification (Micro/Small/Medium)": rec.get("classification", ""),
            "Type (Manufacturer/Service/Trader)": rec.get("type", ""),
            "Agreement (Yes/No)": rec.get("agreement", DEFAULT_AGREEMENT),
            "Udyam No": rec.get("udyam", ""),
        })
    return pd.DataFrame(rows)


def merge_template_df(company, fy, df):
    """Merge an uploaded/edited template back into the master. Returns count."""
    master = load_master(company, fy)
    df = df.copy()
    df.columns = [str(c).strip() for c in df.columns]
    n = 0
    for _, r in df.iterrows():
        party = str(r.get("Party", "")).strip()
        if not party:
            continue
        master[party] = {
            "registered": str(r.get("Registered (Yes/No)", "") or "").strip(),
            "classification": str(r.get("Classification (Micro/Small/Medium)", "") or "").strip(),
            "type": str(r.get("Type (Manufacturer/Service/Trader)", "") or "").strip(),
            "agreement": str(r.get("Agreement (Yes/No)", DEFAULT_AGREEMENT) or DEFAULT_AGREEMENT).strip(),
            "udyam": str(r.get("Udyam No", "") or "").strip(),
        }
        n += 1
    save_master(company, fy, master)
    return n


# ── Advanced: verify next-year payments for "verify" bills ──────────────────
def load_verify_txn(company, fy):
    """Load the next-year creditor-ledger extract(s) saved for verification.

    Single-company  -> msme_verify.csv.
    Group concern    -> one msme_verify_<branch>.csv per branch; ALL are read and
    concatenated so a supplier paid from any branch is counted (the group shares
    one PAN, so 43B(h) payments are pooled by party)."""
    d = _msme_dir(company, fy)
    frames = []
    single = d / "msme_verify.csv"
    if single.exists():
        frames.append(single)
    frames += sorted(d.glob("msme_verify_*.csv"))
    if not frames:
        return pd.DataFrame()
    out = []
    for p in frames:
        try:
            t = pd.read_csv(p)
            t.columns = [c.strip() for c in t.columns]
            if "Branch" not in t.columns:
                t.insert(0, "Branch", p.stem[len("msme_verify_"):]
                         if p.stem.startswith("msme_verify_") else "")
            out.append(t)
        except Exception:
            continue
    if not out:
        return pd.DataFrame()
    return pd.concat(out, ignore_index=True)


def list_verify_branches(company, fy):
    """Branch names already extracted for next-year verification (group mode)."""
    d = _msme_dir(company, fy)
    return sorted(p.stem[len("msme_verify_"):] for p in d.glob("msme_verify_*.csv"))


def detect_branches(company, fy):
    """Distinct branch names in the consolidated master. More than one => the
    company was extracted branch-wise (a group concern), which drives the Branch
    column + per-branch next-year extraction in the UI."""
    p = _conso_master(company, fy)
    if not p.exists():
        return []
    try:
        m = pd.read_csv(p)
        m.columns = [c.strip() for c in m.columns]
        if "Branch" not in m.columns:
            return []
        return sorted({str(x).strip() for x in m["Branch"].dropna()
                       if str(x).strip() and str(x).strip().lower() != "nan"})
    except Exception:
        return []


def verify_next_year(company, fy, compute_res, ny_txn):
    """Continue FIFO into next-year payments and tag each applicable bill whose
    limit expires AFTER year end (the "verify" bills) with whether it was paid
    by its due date. Flag-only — never changes the disallowance total.

    Returns (verdicts, paid_dates, extract_date_str):
      verdicts    maps bill-id (``party#index``) -> status string,
      paid_dates  maps bill-id -> the date (dd-mm-YYYY) on which cumulative
                  next-year payments first FULLY cleared that bill ("" if it
                  was not fully paid by the extract date / has no bill date).
    so the caller can merge both back onto the Verify tab exactly. Undated
    opening bills get "Manual (no bill date)".
    """
    if ny_txn is None or ny_txn.empty:
        return {}, {}, ""

    master = load_master(company, fy)
    ye = fy_end_date(fy)
    pending = compute_res.get("pending", {})

    nt = ny_txn.copy()
    nt.columns = [c.strip() for c in nt.columns]
    if "$Led_BaseGroup" in nt.columns:
        nt = nt[nt["$Led_BaseGroup"].astype(str).str.strip().str.lower() == CREDITOR_GROUP]
    nt["$Amount"] = pd.to_numeric(nt["$Amount"], errors="coerce").fillna(0)
    nt["$Date"] = pd.to_datetime(nt["$Date"], errors="coerce")
    extract_date = nt["$Date"].max()

    # next-year reductions (payments / debit notes) per supplier
    pays_by_party = {}
    pay_lines = nt[nt["$Amount"] < 0]
    for nm, g in pay_lines.groupby("$Particulars"):
        rows = [(d, abs(float(a))) for d, a in zip(g["$Date"], g["$Amount"]) if pd.notna(d)]
        rows.sort(key=lambda x: x[0])
        pays_by_party[nm] = rows

    def _clear_date(pays, target):
        """Date cumulative payments first reach `target` (FIFO clears oldest
        bills first). None if total payments never cover it by the extract."""
        run = 0.0
        for d, a in pays:          # pays already sorted ascending by date
            run += a
            if run + 1e-6 >= target:
                return d
        return None

    asof = extract_date.strftime("%d-%m-%Y") if pd.notna(extract_date) else "extract"
    verdicts, paid_dates = {}, {}
    for party, bills in pending.items():
        rec = master.get(party, default_record())
        if not is_applicable(rec):
            continue
        limit = days_limit(rec)
        pays = pays_by_party.get(party, [])
        P_ext = sum(a for _, a in pays)
        cum = 0.0
        for i, b in enumerate(bills):
            bid = f"{party}#{i}"
            amt = float(b.get("amount", 0))
            cum += amt
            bd = pd.to_datetime(b.get("date"), errors="coerce") if b.get("date") else pd.NaT
            if pd.isna(bd):
                verdicts[bid] = "Manual (no bill date)"
                continue
            due = bd + pd.Timedelta(days=limit)
            if ye is not None and due <= ye:
                continue   # already a disallowed bill, not a verify bill
            # Date this bill was FULLY cleared next year (blank if not fully paid).
            cleared = _clear_date(pays, cum)
            paid_dates[bid] = cleared.strftime("%d-%m-%Y") if pd.notna(cleared) else ""
            P_due = sum(a for d, a in pays if d <= due)
            if P_due + 1e-6 >= cum:
                verdicts[bid] = "Paid within due date"
            elif P_ext + 1e-6 >= cum:
                verdicts[bid] = "Paid after due date"
            else:
                # no payment in the books covers this bill -> not paid
                verdicts[bid] = "Not paid by due date"

    return verdicts, paid_dates, (asof if pd.notna(extract_date) else "")


# ── formatted working-paper Excel ──────────────────────────────────────────
_INR_FMT = ('[>=10000000]##\\,##\\,##\\,##0.00;'
            '[>=100000]##\\,##\\,##0.00;##,##0.00')
_AMOUNT_COLS = {"Unpaid Amount", "Closing"}
_WRAP_COLS = {"Branch", "Party", "Reason", "Conclusion", "Next-Year Check", "Status"}


def build_workpaper_excel(sheets):
    """sheets = {sheet_name: DataFrame}. Returns a BytesIO of a formatted
    workbook — styled header, thin borders, Indian number format on amounts,
    wrapped text on wide columns, auto-fit widths, frozen header."""
    import io as _io
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
    from openpyxl.utils import get_column_letter

    buf = _io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        for name, df in sheets.items():
            d = df if (df is not None and not getattr(df, "empty", True)) \
                else pd.DataFrame({"(none)": []})
            d.to_excel(writer, index=False, sheet_name=str(name)[:31])

        thin = Side(style="thin", color="BBBBBB")
        border = Border(left=thin, right=thin, top=thin, bottom=thin)
        hfill = PatternFill("solid", fgColor="1F4E79")
        hfont = Font(bold=True, color="FFFFFF", name="Segoe UI", size=10)

        for name in sheets:
            ws = writer.sheets[str(name)[:31]]
            ncols, nrows = ws.max_column, ws.max_row
            headers = [ws.cell(row=1, column=c).value for c in range(1, ncols + 1)]
            for c in range(1, ncols + 1):
                hc = ws.cell(row=1, column=c)
                hc.fill, hc.font, hc.border = hfill, hfont, border
                hc.alignment = Alignment(horizontal="center", vertical="center",
                                         wrap_text=True)
            for c in range(1, ncols + 1):
                hdr = headers[c - 1]
                wrap = hdr in _WRAP_COLS
                is_amt = hdr in _AMOUNT_COLS
                maxlen = len(str(hdr))
                for r in range(2, nrows + 1):
                    cell = ws.cell(row=r, column=c)
                    cell.border = border
                    cell.alignment = Alignment(vertical="top", wrap_text=wrap)
                    if is_amt and isinstance(cell.value, (int, float)):
                        cell.number_format = _INR_FMT
                    vlen = len(str(cell.value)) if cell.value is not None else 0
                    if not wrap:
                        maxlen = max(maxlen, vlen)
                    else:
                        maxlen = max(maxlen, min(vlen, 30))
                ws.column_dimensions[get_column_letter(c)].width = \
                    min(max(maxlen + 3, 10), 45)
            ws.freeze_panes = "A2"
    buf.seek(0)
    return buf
