"""
NCE Financial Statements — data layer (entity master + year-tagged TB grouping).

NCE is fully separate from Ledger Scrutiny (LS). LS may be run monthly/quarterly,
so its consolidated data is a part-period snapshot — unsuitable for year-end
financials. NCE therefore has its OWN master-only extraction, tagged by FY.

Persists per company under ~/Documents/LSTool/data/<company>/financials/:
  - entity.json     : entity & auditor master + {current_fy, previous_fy} pointers
  - masters/master_<fy>.csv : NCE master-only snapshots, one per FY (full history)
  - grouping.json   : {ledger_name: {face, note, subnote}}  (current-year grouping)
  - grouping_py.json: previous-year grouping (for comparatives)
"""
import os
import json
from datetime import date
import pandas as pd
import fs_grouping as fg
import fs_policies as fp
import paths

BASE_DATA_DIR = str(paths.BASE)   # shared/local data root (see paths.get_data_root)


def _fs_dir(company, fy=None):
    """Per-year financials folder (years/<fy>/financials/)."""
    fy = fy or get_current_fy(company)
    d = str(paths.financials_dir(company, fy))
    os.makedirs(d, exist_ok=True)
    return d


def _legacy_entity_path(company):
    return os.path.join(BASE_DATA_DIR, company, "financials", "entity.json")


def entity_path(company):
    # entity.json indexes the years + holds the active FY pointers -> company root.
    p = paths.entity_path(company)
    os.makedirs(str(p.parent), exist_ok=True)
    return str(p)


def grouping_path(company, fy=None):
    """Grouping file inside the per-year financials folder."""
    return os.path.join(_fs_dir(company, fy), "grouping.json")


# ── Entity master ─────────────────────────────────────────────────────────────
def _default_entity():
    return {
        "current_fy": None, "previous_fy": None,
        "is_group": False,
        "entity": {"name": "", "address": "", "type": "Partnership Firm",
                   "pan": "", "llpin": "", "nature_of_business": ""},
        "period": {"cy": {"date": 31, "month": "March", "year": 2026},
                   "py": {"date": 31, "month": "March", "year": 2025}},
        "signatories": [],
        "sign": {"place": "", "date": "", "month": "", "year": "", "theme_color": True},
        "auditor": {"firm_name": "", "frn": "", "membership_no": "", "ca_name": "",
                    "designation": "Chartered Accountant", "place": "", "date": "",
                    "month": "", "year": "", "udin": "", "show_udin": True,
                    "show_place_date": "Both", "print_ca_details": True},
        "options": {"depreciation": "FAR IT", "cash_flow": False, "annexures": True,
                    "itr_35": True, "comparative": True, "round_tally_import": True,
                    "profit_destination": "Reserves"},
        "presentation": {"round_off": "In Rs", "two_decimals": False,
                         "theme": "Theme 1", "border": "Layout 1", "font": "Calibri"},
        "print": {"header_align": "Left", "print_address": "Address",
                  "face_hide_zero": True, "print_policies": True,
                  "notes_start": 3, "show_notes_col": True},
    }


def _normalise_entity(raw):
    """Return the full nested entity schema, migrating the old flat keys if present."""
    d = _default_entity()
    if not isinstance(raw, dict) or not raw:
        return d
    d["current_fy"] = raw.get("current_fy", d["current_fy"])
    d["previous_fy"] = raw.get("previous_fy", d["previous_fy"])
    d["is_group"] = bool(raw.get("is_group", d.get("is_group", False)))
    if any(k in raw for k in ("entity", "auditor", "presentation", "print", "options")):
        # already new shape -> deep-merge over defaults
        for k in ("entity", "sign", "auditor", "options", "presentation", "print"):
            if isinstance(raw.get(k), dict):
                d[k].update(raw[k])
        if isinstance(raw.get("period"), dict):
            for sub in ("cy", "py"):
                if isinstance(raw["period"].get(sub), dict):
                    d["period"][sub].update(raw["period"][sub])
        if isinstance(raw.get("signatories"), list):
            d["signatories"] = raw["signatories"]
    else:
        # old flat schema -> migrate
        d["entity"]["name"] = raw.get("name", "")
        d["entity"]["address"] = raw.get("address", "")
        d["entity"]["pan"] = raw.get("pan", "")
        d["entity"]["type"] = ("Proprietorship"
                               if raw.get("entity_type") == "Proprietor" else "Partnership Firm")
        d["auditor"]["firm_name"] = raw.get("aud_firm", "")
        d["auditor"]["frn"] = raw.get("aud_frn", "")
        d["auditor"]["ca_name"] = raw.get("aud_partner", "")
        d["auditor"]["membership_no"] = raw.get("aud_mno", "")
        d["auditor"]["place"] = raw.get("place", "")
        d["sign"]["place"] = raw.get("place", "")
    return d


def load_entity(company):
    p = entity_path(company)
    if not os.path.exists(p):
        # Fallback to the legacy location until migration moves it (idempotent).
        lp = _legacy_entity_path(company)
        if os.path.exists(lp):
            p = lp
    raw = {}
    if os.path.exists(p):
        try:
            with open(p, encoding='utf-8') as f:
                raw = json.load(f)
        except Exception:
            raw = {}
    return _normalise_entity(raw)


def save_entity(company, data):
    paths.atomic_write_json(entity_path(company), data)


# ── Entity helpers ────────────────────────────────────────────────────────────
_MONTHS = ["January", "February", "March", "April", "May", "June",
           "July", "August", "September", "October", "November", "December"]

_UNITS = {"In Rs": (1.0, "in Rs"),
          "Rs '00": (100.0, "in Rs '00"),
          "Rs '000": (1000.0, "in Rs '000"),
          "Rs Lakhs": (100000.0, "in Rs Lakhs"),
          "Rs Crores": (10000000.0, "in Rs Crores")}


def grouping_entity_type(company):
    """Map the rich entity type to the grouping rule type ('Proprietor'/'Partnership')."""
    t = load_entity(company)["entity"]["type"]
    return "Proprietor" if t == "Proprietorship" else "Partnership"


def entity_type_label(company):
    """The rich entity type as stored ('Proprietorship' / 'Partnership Firm' / 'LLP').
    Used where the firm-vs-LLP distinction matters (P&L routing, Reserves face)."""
    return load_entity(company)["entity"]["type"]


def period_header(p):
    """{'date':31,'month':'March','year':2026} -> '31 March 2026'."""
    if not isinstance(p, dict):
        return ""
    parts = [str(p.get("date", "")).strip(), str(p.get("month", "")).strip(),
             str(p.get("year", "")).strip()]
    return " ".join(x for x in parts if x)


def units(round_off):
    """Round-off label -> (divisor, label). Defaults to (1, 'in Rs')."""
    return _UNITS.get(round_off, (1.0, "in Rs"))


# ── Trade Receivables ageing (FIFO approximation from transactions) ───────────
# The consolidated transactions carry no bill-wise data, so we age each debtor
# ledger by FIFO: opening balance + invoices (debits) settled by receipts
# (credits) oldest-first; whatever invoices remain open are aged from the
# year-end date into < 6 months / > 6 months buckets.
_AGE_FACE = "Trade receivables"


def _conso_txn(company, fy):
    d = paths.consolidated_dir(company, fy)
    frames = []
    try:
        for f in sorted(d.glob("Transactions_*.csv")):
            try:
                frames.append(pd.read_csv(f))
            except Exception:
                pass
    except Exception:
        return pd.DataFrame()
    if not frames:
        return pd.DataFrame()
    t = pd.concat(frames, ignore_index=True)
    t.columns = [c.strip() for c in t.columns]
    return t


def _ageing_ason(fy):
    """Year-end (as-on) date for ageing. FY '2025-26' -> 31-Mar-2026."""
    try:
        return date(2000 + int(str(fy).split("-")[1]), 3, 31)
    except Exception:
        return date.today()


def receivables_ageing(company, fy, work):
    """FIFO-age the Trade-receivable ledgers in `work` (the working mapping for
    `fy`). Returns {'lt6', 'gt6', 'tb'} — amounts in actual rupees (unscaled)."""
    from datetime import timedelta
    recs = {l: float(v.get("closing") or 0.0) for l, v in (work or {}).items()
            if v.get("face") == _AGE_FACE}
    tb = round(-sum(recs.values()), 2)          # presented positive
    if not recs:
        return {"lt6": 0.0, "gt6": 0.0, "tb": tb}
    ason = _ageing_ason(fy)
    txn = _conso_txn(company, fy)
    if txn.empty or "$Particulars" not in txn.columns:
        # no transactions to age against — park the whole debit closing in > 6m
        gt6 = round(sum(-c for c in recs.values() if c < 0), 2)
        return {"lt6": 0.0, "gt6": gt6, "tb": tb}
    txn = txn.copy()
    txn["_d"] = pd.to_datetime(txn["$Date"], errors="coerce", dayfirst=True)
    txn["_a"] = pd.to_numeric(txn["$Amount"], errors="coerce").fillna(0.0)
    txn["_p"] = txn["$Particulars"].astype(str).str.strip()

    lt6 = gt6 = 0.0
    for led, closing in recs.items():
        sub = txn[txn["_p"] == str(led).strip()].dropna(subset=["_d"])
        # Invoices (debits) before receipts (credits) on the SAME date, so an
        # invoice raised and received on the same day settles in order.
        sub = sub.assign(_o=(sub["_a"] > 0).astype(int)).sort_values(["_d", "_o"])
        net_current = float(sub["_a"].sum())
        opening = closing - net_current          # signed, debit = negative
        queue = []                               # FIFO [date, magnitude] open invoices
        advance = 0.0                            # unmatched receipts carried forward
        if opening < -0.005:                     # opening receivable (debit)
            queue.append([ason - timedelta(days=400), -opening])   # ages as > 6m
        elif opening > 0.005:                    # opening credit (customer advance)
            advance = opening
        for d, a in zip(sub["_d"], sub["_a"]):
            if a < -1e-6:                        # debit = invoice
                mag = -a
                if advance > 1e-6:               # apply any carried advance first
                    used = min(advance, mag); advance -= used; mag -= used
                if mag > 1e-6:
                    queue.append([d.date(), mag])
            elif a > 1e-6:                       # credit = receipt -> settle FIFO
                r = a
                while r > 1e-6 and queue:
                    if queue[0][1] <= r + 1e-6:
                        r -= queue[0][1]; queue.pop(0)
                    else:
                        queue[0][1] -= r; r = 0.0
                if r > 1e-6:                     # receipt with no open invoice yet
                    advance += r                 # carry forward (do NOT discard)
        # By construction the open queue now totals this ledger's receivable
        # closing, so the buckets always reconcile to the trial-balance total.
        for qd, mag in queue:
            if (ason - qd).days < 182:
                lt6 += mag
            else:
                gt6 += mag
    return {"lt6": round(lt6, 2), "gt6": round(gt6, 2), "tb": tb}


# ── Trade Receivables ageing — saved disclosure (per company/year) ────────────
def _tr_ageing_path(company, fy):
    return paths.config_path(company, fy, "tr_ageing.json")


def _tr_zero():
    return {"lt6_cy": 0.0, "lt6_py": 0.0, "gt6_cy": 0.0, "gt6_py": 0.0}


def tr_ageing_default():
    return {"disclose": False,
            "grid": {k: _tr_zero() for k in ("secured", "unsecured", "doubtful", "provision")},
            "unbilled": {"cy": 0.0, "py": 0.0},
            "undue": {"cy": 0.0, "py": 0.0},
            "footnotes": []}


def load_tr_ageing(company, fy):
    p = _tr_ageing_path(company, fy)
    d = tr_ageing_default()
    try:
        if p.exists():
            saved = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(saved, dict):
                d.update(saved)
                for k in ("secured", "unsecured", "doubtful", "provision"):
                    row = d.setdefault("grid", {}).get(k) or {}
                    d["grid"][k] = {**_tr_zero(), **row}
                d["unbilled"] = {**{"cy": 0.0, "py": 0.0}, **(d.get("unbilled") or {})}
                d["undue"] = {**{"cy": 0.0, "py": 0.0}, **(d.get("undue") or {})}
                if not isinstance(d.get("footnotes"), list):
                    d["footnotes"] = []
    except Exception:
        pass
    return d


def save_tr_ageing(company, fy, data):
    paths.atomic_write_json(_tr_ageing_path(company, fy), data)


# ── Owner's Capital Account — saved disclosure (Proprietor/Individual) ────────
# Purely user-entered (credit & debit lines) EXCEPT Profit/Loss for the period,
# which is auto-injected from the P&L at render time.
def _owners_cap_path(company, fy):
    return paths.config_path(company, fy, "owners_capital.json")


def owners_capital_default():
    return {"disclose": False,
            "credit": [{"label": "Opening Balance", "cy": 0.0, "py": 0.0},
                       {"label": "Capital Brought in during the year", "cy": 0.0, "py": 0.0}],
            "debit": [{"label": "Withdrawals", "cy": 0.0, "py": 0.0},
                      {"label": "Income Tax", "cy": 0.0, "py": 0.0},
                      {"label": "Life Insurance", "cy": 0.0, "py": 0.0},
                      {"label": "Mediclaim", "cy": 0.0, "py": 0.0}],
            "footnotes": []}


def load_owners_capital(company, fy):
    p = _owners_cap_path(company, fy)
    d = owners_capital_default()
    try:
        if p.exists():
            saved = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(saved, dict):
                d["disclose"] = bool(saved.get("disclose", False))
                for side in ("credit", "debit"):
                    rows = saved.get(side)
                    if isinstance(rows, list):
                        d[side] = [{"label": str(r.get("label", "")),
                                    "cy": float(r.get("cy") or 0.0),
                                    "py": float(r.get("py") or 0.0)}
                                   for r in rows if isinstance(r, dict)]
                if isinstance(saved.get("footnotes"), list):
                    d["footnotes"] = saved["footnotes"]
    except Exception:
        pass
    return d


def save_owners_capital(company, fy, data):
    paths.atomic_write_json(_owners_cap_path(company, fy), data)


# ── Inventories disclosure — Cost of material consumed + Change in inventories ─
# User-entered (Opening / Purchases / Closing per material category; Opening /
# Closing per finished-goods/WIP stock type). Optional; when blank the regular
# single Opening/Closing stock presentation is used. Only the stock movement
# (Opening − Closing) affects the balance — purchases stay in the trial balance.
def _inventory_path(company, fy):
    return paths.config_path(company, fy, "inventory.json")


def _mat_row(label=""):
    return {"label": label,
            "opening_cy": 0.0, "purchases_cy": 0.0, "closing_cy": 0.0,
            "opening_py": 0.0, "purchases_py": 0.0, "closing_py": 0.0}


def _stock_row(label=""):
    return {"label": label, "open_cy": 0.0, "close_cy": 0.0,
            "open_py": 0.0, "close_py": 0.0}


def inventory_default():
    return {
        "disclose": False,
        "materials": [_mat_row("Raw materials"), _mat_row("Packing materials"),
                      _mat_row("Stores and Spares"), _mat_row("Other Material")],
        "mfg_expenses": [{"label": "", "group": "", "cy": 0.0, "py": 0.0}],
        "mfg_footnotes": [],
        "change": [_stock_row("Finished Goods"), _stock_row("Work-in-progress"),
                   _stock_row("Stock-in-trade"), _stock_row("Goods-in-transit"),
                   _stock_row("Loose Tool"), _stock_row("Other Stock")],
        "change_footnotes": [],
    }


def _norm_lbl(s):
    return str(s or "").strip().lower()


def _carry_py_inventory(d, src):
    """Fill blank PY cells of inventory dict `d` from the previous-year CY figures
    in `src`. Matches rows by label (renamed rows simply stay blank). Never
    overwrites a PY value the user already typed."""
    def _fill(row, pyk, srcval):
        if abs(float(row.get(pyk) or 0.0)) <= 0.005:
            row[pyk] = float(srcval or 0.0)
    by_lbl = {_norm_lbl(r.get("label")): r for r in src.get("materials", [])}
    for r in d.get("materials", []):
        s = by_lbl.get(_norm_lbl(r.get("label")))
        if s:
            _fill(r, "opening_py", s.get("opening_cy"))
            _fill(r, "purchases_py", s.get("purchases_cy"))
            _fill(r, "closing_py", s.get("closing_cy"))
    by_chg = {_norm_lbl(r.get("label")): r for r in src.get("change", [])}
    for r in d.get("change", []):
        s = by_chg.get(_norm_lbl(r.get("label")))
        if s:
            _fill(r, "open_py", s.get("open_cy"))
            _fill(r, "close_py", s.get("close_cy"))
    by_mfg = {(_norm_lbl(r.get("label")), _norm_lbl(r.get("group"))): r
              for r in src.get("mfg_expenses", [])}
    for r in d.get("mfg_expenses", []):
        s = by_mfg.get((_norm_lbl(r.get("label")), _norm_lbl(r.get("group"))))
        if s:
            _fill(r, "py", s.get("cy"))


def load_inventory(company, fy, carry=True):
    p = _inventory_path(company, fy)
    d = inventory_default()
    try:
        if p.exists():
            saved = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(saved, dict):
                d["disclose"] = bool(saved.get("disclose", False))
                if isinstance(saved.get("materials"), list):
                    d["materials"] = [{**_mat_row(), **{k: r.get(k, _mat_row().get(k))
                                       for k in _mat_row()},
                                       "label": str(r.get("label", "") or "")}
                                      for r in saved["materials"] if isinstance(r, dict)]
                if isinstance(saved.get("mfg_expenses"), list):
                    d["mfg_expenses"] = [{"label": str(r.get("label", "") or ""),
                                          "group": str(r.get("group", "") or ""),
                                          "cy": float(r.get("cy") or 0.0),
                                          "py": float(r.get("py") or 0.0)}
                                         for r in saved["mfg_expenses"] if isinstance(r, dict)]
                if isinstance(saved.get("change"), list):
                    d["change"] = [{**_stock_row(), **{k: r.get(k, _stock_row().get(k))
                                    for k in _stock_row()},
                                    "label": str(r.get("label", "") or "")}
                                   for r in saved["change"] if isinstance(r, dict)]
                for fk in ("mfg_footnotes", "change_footnotes"):
                    if isinstance(saved.get(fk), list):
                        d[fk] = saved[fk]
        # numeric coercion (defensive)
        for r in d["materials"]:
            for k in ("opening_cy", "purchases_cy", "closing_cy",
                      "opening_py", "purchases_py", "closing_py"):
                r[k] = float(r.get(k) or 0.0)
        for r in d["change"]:
            for k in ("open_cy", "close_cy", "open_py", "close_py"):
                r[k] = float(r.get(k) or 0.0)
        # Carry the comparative (PY) column forward from the previous year's saved
        # disclosure (its CY) — fills blanks only, blank when no prior year exists.
        if carry:
            prev = paths.latest_year_before(company, fy)
            if prev:
                _carry_py_inventory(d, load_inventory(company, prev, carry=False))
    except Exception:
        pass
    return d


def save_inventory(company, fy, data):
    paths.atomic_write_json(_inventory_path(company, fy), data)


def inventory_has_data(inv):
    """True when any inventory figure (material or stock movement) is non-zero."""
    inv = inv or {}
    for r in inv.get("materials", []):
        if any(abs(float(r.get(k) or 0.0)) > 0.005 for k in
               ("opening_cy", "purchases_cy", "closing_cy",
                "opening_py", "purchases_py", "closing_py")):
            return True
    for r in inv.get("change", []):
        if any(abs(float(r.get(k) or 0.0)) > 0.005 for k in
               ("open_cy", "close_cy", "open_py", "close_py")):
            return True
    for r in inv.get("mfg_expenses", []):
        if abs(float(r.get("cy") or 0.0)) > 0.005 or abs(float(r.get("py") or 0.0)) > 0.005:
            return True
    return False


def inventory_totals(inv, side="cy"):
    """Resolved stock totals for one side ('cy'/'py'). Returns dict with
    opening_mat, closing_mat, opening_fg, closing_fg and their grand sums."""
    o = "opening_" + side
    c = "closing_" + side
    om = sum(float(r.get(o) or 0.0) for r in inv.get("materials", []))
    cm = sum(float(r.get(c) or 0.0) for r in inv.get("materials", []))
    ofg = sum(float(r.get("open_" + side) or 0.0) for r in inv.get("change", []))
    cfg = sum(float(r.get("close_" + side) or 0.0) for r in inv.get("change", []))
    return {"opening_mat": om, "closing_mat": cm,
            "opening_fg": ofg, "closing_fg": cfg,
            "opening_total": om + ofg, "closing_total": cm + cfg}


# ── Fixed Assets disclosure — Capital WIP + Intangible assets under development ─
# Movement schedule (Opening + Addition − Capitalised = Closing). When disclosed,
# the Closing Balance DRIVES the Balance-Sheet figure for that face (overrides the
# ledgers); when blank the regular ledger/face presentation is used. Renders inside
# the PPE note (Note 7).
def _fixed_assets_path(company, fy):
    return paths.config_path(company, fy, "fixed_assets.json")


def _fa_block():
    return {"disclose": False,
            "opening_cy": 0.0, "addition_cy": 0.0, "capitalised_cy": 0.0,
            "opening_py": 0.0, "addition_py": 0.0, "capitalised_py": 0.0}


def fixed_assets_default():
    return {"cwip": _fa_block(), "intan_dev": _fa_block(), "footnotes": []}


def _carry_py_fixed_assets(d, src):
    """Fill blank PY cells of the FA blocks from the previous year's saved CY
    figures. Blanks only; never overwrites a typed PY value."""
    for key in ("cwip", "intan_dev"):
        blk, s = d.get(key, {}), (src.get(key) or {})
        for pyk, cyk in (("opening_py", "opening_cy"),
                         ("addition_py", "addition_cy"),
                         ("capitalised_py", "capitalised_cy")):
            if abs(float(blk.get(pyk) or 0.0)) <= 0.005:
                blk[pyk] = float(s.get(cyk) or 0.0)


def load_fixed_assets(company, fy, carry=True):
    p = _fixed_assets_path(company, fy)
    d = fixed_assets_default()
    try:
        if p.exists():
            saved = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(saved, dict):
                for key in ("cwip", "intan_dev"):
                    blk = saved.get(key)
                    if isinstance(blk, dict):
                        d[key]["disclose"] = bool(blk.get("disclose", False))
                        for k in ("opening_cy", "addition_cy", "capitalised_cy",
                                  "opening_py", "addition_py", "capitalised_py"):
                            d[key][k] = float(blk.get(k) or 0.0)
                if isinstance(saved.get("footnotes"), list):
                    d["footnotes"] = saved["footnotes"]
        # Carry the PY column forward from the previous year's saved CY (blanks only).
        if carry:
            prev = paths.latest_year_before(company, fy)
            if prev:
                _carry_py_fixed_assets(d, load_fixed_assets(company, prev, carry=False))
    except Exception:
        pass
    return d


def save_fixed_assets(company, fy, data):
    paths.atomic_write_json(_fixed_assets_path(company, fy), data)


def fa_closing(block, side="cy"):
    """Closing balance for one FA block & side = Opening + Addition − Capitalised."""
    return (float(block.get("opening_" + side) or 0.0)
            + float(block.get("addition_" + side) or 0.0)
            - float(block.get("capitalised_" + side) or 0.0))


def fa_block_has_data(blk):
    """True when a single FA block (cwip / intan_dev) carries any non-zero figure."""
    blk = blk or {}
    return any(abs(float(blk.get(k) or 0.0)) > 0.005 for k in
               ("opening_cy", "addition_cy", "capitalised_cy",
                "opening_py", "addition_py", "capitalised_py"))


def fa_block_discloses(blk):
    """Effective 'show detail' for a block — the saved flag OR any figure present,
    so filling a block always shows its breakup even if the toggle wasn't ticked."""
    blk = blk or {}
    return bool(blk.get("disclose")) or fa_block_has_data(blk)


def fixed_assets_has_data(fa):
    fa = fa or {}
    return any(fa_block_has_data(fa.get(key, {})) for key in ("cwip", "intan_dev"))


# ── Year-tagged master snapshots (NCE's own extraction) ───────────────────────
def masters_dir(company, fy=None):
    d = str(paths.masters_dir(company, fy or get_current_fy(company)))
    os.makedirs(d, exist_ok=True)
    return d


def master_path(company, fy):
    return os.path.join(masters_dir(company, fy), "master.csv")


def list_master_fys(company):
    """FY strings (e.g. '2025-26') that have an extracted master file, newest first."""
    out = []
    for fy in paths.list_years(company):
        if os.path.exists(os.path.join(str(paths.masters_dir(company, fy)), "master.csv")):
            out.append(fy)
    return out


def save_master_df(company, fy, df):
    df.to_csv(master_path(company, fy), index=False)


def ls_master_exists(company, fy):
    """True if a Ledger-Scrutiny consolidated master exists for this FY, so NCE
    can reuse it instead of re-extracting from Tally."""
    return bool(fy) and (paths.consolidated_dir(company, fy)
                         / "Conso_MasterData.csv").exists()


def available_fy_choices(span=7):
    """Generated FY dropdown list (e.g. '2025-26'), current FY first going back `span` years.
    The Indian FY ends 31 March; before April the 'current' FY started the previous year."""
    today = date.today()
    start_year = today.year if today.month >= 4 else today.year - 1
    return [f"{y}-{str(y + 1)[-2:]}" for y in range(start_year, start_year - span, -1)]


# ── Active-year pointers (stored in entity.json) ──────────────────────────────
def get_current_fy(company):
    return load_entity(company).get('current_fy') or ''


def get_previous_fy(company):
    return load_entity(company).get('previous_fy') or ''


def set_current_fy(company, fy):
    ent = load_entity(company)
    ent['current_fy'] = (str(fy).strip() or None) if fy else None
    save_entity(company, ent)


def set_previous_fy(company, fy):
    ent = load_entity(company)
    ent['previous_fy'] = (str(fy).strip() or None) if fy else None
    save_entity(company, ent)


def get_is_group(company):
    """True if this company was marked a Group Concern (multi-branch) at creation."""
    return bool(load_entity(company).get('is_group', False))


def set_is_group(company, is_group):
    ent = load_entity(company)
    ent['is_group'] = bool(is_group)
    save_entity(company, ent)


# ── Grouping (ledger -> face/note/subnote) ────────────────────────────────────
def _migrate_mapping(m):
    """Upgrade saved {ledger: {face, note, subnote}} from the old face/note
    vocabulary to the new one (fg.migrate_face_note)."""
    if not isinstance(m, dict):
        return {}
    for v in m.values():
        if isinstance(v, dict):
            f2, n2 = fg.migrate_face_note(v.get('face', ''), v.get('note', ''))
            v['face'], v['note'] = f2, n2
    return m


def load_grouping(company, fy=None):
    """Grouping for a FY (default: current). FY-tagged — one file per year, so
    switching the year pointers automatically picks the right grouping. No
    roll-over needed; history is kept like the masters shelf."""
    p = grouping_path(company, fy)
    if os.path.exists(p):
        try:
            with open(p, encoding='utf-8') as f:
                return _migrate_mapping(json.load(f))
        except Exception:
            pass
    return {}


def save_grouping(company, mapping, fy=None):
    paths.atomic_write_json(grouping_path(company, fy), mapping)


# ── Previous-year grouping (comparative) ─────────────────────────────────────
# Base = the previous FY's own tagged grouping file (read-only here). Any PY
# regrouping done while working in the CURRENT year is stored as a current-year
# *override* (grouping_py_override.json in THIS year's financials folder) and
# layered on top — so the prior year's finalized file is never altered.
def grouping_py_override_path(company, fy=None):
    """Current-year comparative-grouping override (does NOT touch the prior file)."""
    return os.path.join(_fs_dir(company, fy), "grouping_py_override.json")


def load_grouping_py_override(company, fy=None):
    p = grouping_py_override_path(company, fy)
    if os.path.exists(p):
        try:
            with open(p, encoding='utf-8') as f:
                d = json.load(f)
                return d if isinstance(d, dict) else {}
        except Exception:
            pass
    return {}


def save_grouping_py_override(company, mapping, fy=None):
    paths.atomic_write_json(grouping_py_override_path(company, fy), mapping)


def load_grouping_py(company):
    """PY comparative grouping = the previous FY's own file, with the current
    year's comparative-only override layered on top (override wins per ledger)."""
    pfy = get_previous_fy(company)
    base = load_grouping(company, pfy) if pfy else {}
    override = load_grouping_py_override(company)
    if not override:
        return base
    merged = dict(base)
    for led, g in override.items():
        if isinstance(g, dict) and g.get('face'):
            merged[led] = g
    return merged


def save_grouping_py(company, mapping):
    """Persist PY regrouping as a CURRENT-year override — the previous year's own
    grouping file is left untouched."""
    save_grouping_py_override(company, mapping)


# ── Stock & manual adjustments (per FY) ───────────────────────────────────────
# Stock is NOT extracted from Tally — the user enters Opening / Closing stock
# (positive figures). Closing stock -> Inventories (BS asset); Opening - Closing
# -> Changes in inventories (P&L). Manual adjustment rows plug reconciling items.
def aux_path(company, fy):
    # NB: 'aux' is a reserved Windows device name -> must not be the bare filename.
    return os.path.join(_fs_dir(company, fy), "aux_data.json")


def load_aux(company, fy=None):
    fy = fy or get_current_fy(company)
    p = aux_path(company, fy) if fy else None
    data = {"opening_stock": 0.0, "closing_stock": 0.0, "adjustments": []}
    if p and os.path.exists(p):
        try:
            with open(p, encoding='utf-8') as f:
                saved = json.load(f)
            if isinstance(saved, dict):
                data.update(saved)
        except Exception:
            pass
    data["opening_stock"] = float(data.get("opening_stock") or 0.0)
    data["closing_stock"] = float(data.get("closing_stock") or 0.0)
    if not isinstance(data.get("adjustments"), list):
        data["adjustments"] = []
    for adj in data["adjustments"]:
        if isinstance(adj, dict):
            f2, n2 = fg.migrate_face_note(adj.get('face', ''), adj.get('note', ''))
            adj['face'], adj['note'] = f2, n2
    return data


def save_aux(company, fy, data):
    fy = fy or get_current_fy(company)
    paths.atomic_write_json(aux_path(company, fy), data)


def default_opening_stock(company):
    """This year's opening stock defaults to the previous year's closing stock."""
    pfy = get_previous_fy(company)
    if not pfy:
        return 0.0
    return float(load_aux(company, pfy).get("closing_stock") or 0.0)


# ── FAR (Fixed Assets Register, per FY) ───────────────────────────────────────
# Income-tax depreciation is NOT extracted from Tally — the user maintains the
# asset register here (manual first year; rolls forward thereafter). Each row is a
# block-mapped asset; fs_reports.compute_far() derives rate / depreciation / WDV.
FAR_INPUT_FIELDS = ["id", "name", "category", "block", "rate", "opening_gross",
                    "add_before180", "add_after180", "sale", "opening_accum", "manual_adj"]


def far_path(company, fy):
    return os.path.join(_fs_dir(company, fy), "far.json")


def far_default_row():
    return {"id": "", "name": "", "category": "Tangible", "block": "Office equipment",
            "rate": None, "opening_gross": 0.0, "add_before180": 0.0, "add_after180": 0.0,
            "sale": 0.0, "opening_accum": 0.0, "manual_adj": 0.0}


def _far_norm_row(r):
    out = far_default_row()
    if isinstance(r, dict):
        for k in FAR_INPUT_FIELDS:
            if k in r and r[k] is not None:
                out[k] = r[k]
    for k in ("opening_gross", "add_before180", "add_after180", "sale",
              "opening_accum", "manual_adj"):
        try:
            out[k] = float(out[k] or 0.0)
        except (TypeError, ValueError):
            out[k] = 0.0
    if out.get("rate") not in (None, ""):
        try:
            out["rate"] = float(out["rate"])
        except (TypeError, ValueError):
            out["rate"] = None
    else:
        out["rate"] = None
    out["name"] = str(out.get("name") or "").strip()
    out["category"] = str(out.get("category") or "Tangible").strip() or "Tangible"
    out["block"] = str(out.get("block") or "").strip()
    return out


def load_far(company, fy=None):
    """List of asset input rows for the given FY (current FY if omitted)."""
    fy = fy or get_current_fy(company)
    p = far_path(company, fy) if fy else None
    rows = []
    if p and os.path.exists(p):
        try:
            with open(p, encoding='utf-8') as f:
                saved = json.load(f)
            if isinstance(saved, list):
                rows = [_far_norm_row(r) for r in saved]
        except Exception:
            pass
    return rows


def save_far(company, fy, rows):
    fy = fy or get_current_fy(company)
    if not fy:
        return
    clean = [_far_norm_row(r) for r in (rows or [])
             if isinstance(r, dict) and (str(r.get("name") or "").strip()
                                         or float(r.get("opening_gross") or 0) != 0)]
    paths.atomic_write_json(far_path(company, fy), clean)


# ── Reconciliation comments + custom checks (per FY, for the Check tab) ────────
def checks_path(company, fy):
    return os.path.join(_fs_dir(company, fy), "checks.json")


def load_checks(company, fy=None):
    fy = fy or get_current_fy(company)
    data = {"comments": {}, "custom": []}
    p = checks_path(company, fy) if fy else None
    if p and os.path.exists(p):
        try:
            with open(p, encoding='utf-8') as f:
                saved = json.load(f)
            if isinstance(saved, dict):
                if isinstance(saved.get("comments"), dict):
                    data["comments"] = saved["comments"]
                if isinstance(saved.get("custom"), list):
                    data["custom"] = saved["custom"]
        except Exception:
            pass
    return data


def save_checks(company, fy, data):
    fy = fy or get_current_fy(company)
    if not fy:
        return
    out = {"comments": (data or {}).get("comments", {}) or {},
           "custom": (data or {}).get("custom", []) or []}
    paths.atomic_write_json(checks_path(company, fy), out)


# ── Partners' capital schedules (per FY, Partnership entities) ─────────────────
PARTNER_FIELDS = ["name", "share", "opening", "addition", "withdrawal",
                  "interest", "remuneration", "profit"]          # current schedule
PARTNER_FIXED_FIELDS = ["name", "share", "opening", "addition", "withdrawal",
                        "others_add", "others_less"]             # fixed schedule


def partners_path(company, fy):
    return os.path.join(_fs_dir(company, fy), "partners.json")


def _pnum(x):
    try:
        v = float(x)
        return 0.0 if v != v else v   # NaN -> 0
    except (TypeError, ValueError):
        return 0.0


def load_partners(company, fy=None):
    fy = fy or get_current_fy(company)
    data = {"fixed_schedule": False, "format": "Vertical",
            "rows": [], "fixed_rows": [],
            "py": {"current": {}, "fixed": {}}}
    p = partners_path(company, fy) if fy else None
    if p and os.path.exists(p):
        try:
            with open(p, encoding='utf-8') as f:
                saved = json.load(f)
            if isinstance(saved, dict):
                data.update({k: saved[k] for k in data if k in saved})
        except Exception:
            pass
    for key in ("rows", "fixed_rows"):
        if not isinstance(data.get(key), list):
            data[key] = []
    if not isinstance(data.get("py"), dict):
        data["py"] = {"current": {}, "fixed": {}}
    data["py"].setdefault("current", {})
    data["py"].setdefault("fixed", {})
    return data


def save_partners(company, fy, data):
    fy = fy or get_current_fy(company)
    if not fy:
        return
    out = {"fixed_schedule": bool((data or {}).get("fixed_schedule")),
           "format": (data or {}).get("format", "Vertical"),
           "rows": [r for r in (data or {}).get("rows", [])
                    if isinstance(r, dict) and str(r.get("name") or "").strip()],
           "fixed_rows": [r for r in (data or {}).get("fixed_rows", [])
                          if isinstance(r, dict) and str(r.get("name") or "").strip()],
           "py": (data or {}).get("py", {"current": {}, "fixed": {}})}
    paths.atomic_write_json(partners_path(company, fy), out)


def partners_py_totals(company, pfy, fixed=False):
    """Auto-fetched Previous Year totals from the previous FY's saved partners
    file (used when the user hasn't typed manual PY totals)."""
    if not pfy:
        return {}
    pdata = load_partners(company, pfy)
    rows = pdata.get('fixed_rows' if fixed else 'rows') or []
    if not rows:
        return {}
    keys = (("opening", "addition", "withdrawal", "others_add", "others_less")
            if fixed else
            ("opening", "addition", "withdrawal", "interest", "remuneration", "profit"))
    out = {k: sum(_pnum(r.get(k)) for r in rows) for k in keys}
    out["closing"] = sum(partners_closing(r, fixed) for r in rows)
    return out


def partners_closing(row, fixed=False):
    """Closing balance of one partner row (current: open+add−wdr+interest+remun+profit;
    fixed: open+add−wdr+others_add−others_less)."""
    if fixed:
        return (_pnum(row.get("opening")) + _pnum(row.get("addition"))
                - _pnum(row.get("withdrawal")) + _pnum(row.get("others_add"))
                - _pnum(row.get("others_less")))
    return (_pnum(row.get("opening")) + _pnum(row.get("addition"))
            - _pnum(row.get("withdrawal")) + _pnum(row.get("interest"))
            + _pnum(row.get("remuneration")) + _pnum(row.get("profit")))


# ── Disclosures: accounting policies + entity information (per company) ────────
# Stored once per company (carried forward across years; editable). Resolves the
# prefilled defaults against saved overrides so new default heads always appear.
def policies_path(company, fy=None):
    return os.path.join(_fs_dir(company, fy), "policies.json")


def load_policies(company, fy=None):
    saved = {}
    p = policies_path(company, fy)
    if os.path.exists(p):
        try:
            with open(p, encoding='utf-8') as f:
                s = json.load(f)
            if isinstance(s, dict):
                saved = s
        except Exception:
            pass
    saved_pol = {x.get('key'): x for x in saved.get('policies', [])
                 if isinstance(x, dict) and x.get('key')}

    # Entity information (Note 1)
    ei = saved.get('entity_info') if isinstance(saved.get('entity_info'), dict) else {}
    entity_info = {
        'disclose': bool(ei.get('disclose', True)),
        'text': ei.get('text', fp.DEFAULT_ENTITY_INFO),
    }

    # Significant accounting policies (Note 2) — defaults overlaid with saved
    policies = []
    seen = set()
    for key, head, disclose, text in fp.DEFAULT_POLICIES:
        s = saved_pol.get(key, {})
        item = {
            'key': key,
            'head': s.get('head', head),
            'disclose': bool(s.get('disclose', disclose)),
            'text': s.get('text', text),
            'custom': False,
        }
        if key in fp.DEFAULT_TABLES:
            tbl = fp.DEFAULT_TABLES[key]
            item['table_cols'] = tbl['columns']
            item['table_headers'] = tbl['headers']
            rows = s.get('table')
            item['table'] = rows if isinstance(rows, list) else [dict(r) for r in tbl['rows']]
        policies.append(item)
        seen.add(key)
    # User-added custom heads kept at the end
    for x in saved.get('policies', []):
        if isinstance(x, dict) and x.get('key') and x['key'] not in seen:
            policies.append({
                'key': x['key'], 'head': x.get('head', x['key']),
                'disclose': bool(x.get('disclose', True)),
                'text': x.get('text', ''), 'custom': True,
            })
            seen.add(x['key'])
    return {'entity_info': entity_info, 'policies': policies}


def save_policies(company, data, fy=None):
    out = {'entity_info': (data or {}).get('entity_info', {}),
           'policies': (data or {}).get('policies', [])}
    paths.atomic_write_json(policies_path(company, fy), out)


# Tally groups whose Face depends on the balance sign (re-checked each year).
SIGN_SENSITIVE = {'sundry debtors', 'sundry creditors'}
_SIGN_FACES = {
    'sundry debtors':   {"Trade receivables", "Other current liabilities"},
    'sundry creditors': {"Trade payables due to others", "Trade payables due to MSME",
                         "Short term loans and advances"},
}


# ── Trial balance from the NCE year-tagged master snapshot ────────────────────
def tb_available(company):
    """True only when a current FY is set AND its master snapshot exists.
    NCE never falls back to the LS consolidated data (hard separation)."""
    if not company:
        return False
    fy = get_current_fy(company)
    return bool(fy) and os.path.exists(master_path(company, fy))


def load_tb(company, fy=None):
    fy = fy or get_current_fy(company)
    df = pd.read_csv(master_path(company, fy))

    def col(*names):
        for n in names:
            if n in df.columns:
                return df[n]
        return pd.Series([None] * len(df))

    def _scol(*names):
        # pandas 3.0: astype(str) no longer stringifies NaN -> fillna('') first.
        return col(*names).fillna('').astype(str).str.strip()

    out = pd.DataFrame({
        'Ledger': _scol('$Name'),
        'PrimaryGroup': _scol('$_PrimaryGroup', '$Led_BaseGroup'),
        'Parent': _scol('$Parent', '$_PrimaryGroup'),
        'Closing': pd.to_numeric(col('$ClosingBalance'), errors='coerce').fillna(0),
        'Opening': pd.to_numeric(col('$OpeningBalance'), errors='coerce').fillna(0),
    })
    out = out[~out['Ledger'].str.lower().isin(['', 'nan'])]
    # Ledgers with a NIL closing balance are not relevant to the statements
    out = out[out['Closing'].round(2) != 0].reset_index(drop=True)
    # Tally's "Profit & Loss A/c" appropriation ledger carries no primary group,
    # so it never appears under the primary-group filter. Give it a synthetic
    # group ("Profit & Loss A/c") so the CA can find and re-map it in the editor.
    _pl_mask = (out['PrimaryGroup'].str.strip() == '') & \
        out['Ledger'].str.lower().str.contains('profit & loss|profit and loss|p&l', regex=True)
    out.loc[_pl_mask, 'PrimaryGroup'] = 'Profit & Loss A/c'
    return out


def load_py_closing(company):
    """{ledger: closing} from the PREVIOUS-year master (for the comparative column).
    Empty dict if no previous FY / file."""
    fy = get_previous_fy(company)
    if not fy or not os.path.exists(master_path(company, fy)):
        return {}
    try:
        tb = load_tb(company, fy)
    except Exception:
        return {}
    return {r['Ledger']: float(r['Closing']) for _, r in tb.iterrows()}


def build_working_mapping(company, entity_type="Partnership"):
    """Build the editor's working mapping for the CURRENT year.

    Current Face/Note/Sub-Note follow a carry-forward chain per ledger:
      1. grouping.json          (manual current-year edits)            -> source 'saved'
      2. grouping_py.json       (same-named ledger carried from PY)    -> source 'carry'
      3. fg.default_grouping()  (predefined rules for new ledgers)     -> source 'default'
    Sign-sensitive groups (Sundry Debtors/Creditors) are re-checked against the
    current balance sign for cases 1 & 2 (-> source 'resign').
    Returns {ledger: {face, note, subnote, py_*, py_closing, primary_group, parent,
    closing, source}}."""
    tb = load_tb(company)
    saved = load_grouping(company)
    saved_py = load_grouping_py(company)
    py_closing = load_py_closing(company)
    # Use the rich entity label (Proprietorship / Partnership Firm / LLP) for the
    # default rules so P&L routing can tell a firm from an LLP.
    entity_type = entity_type_label(company) or entity_type
    work = {}
    for _, r in tb.iterrows():
        led = r['Ledger']
        pg = str(r['PrimaryGroup']).strip().lower()
        closing = float(r['Closing'])

        def _resign(g, src):
            # If a carried sign-based Face no longer matches the current balance sign, switch.
            if pg in SIGN_SENSITIVE and g.get('face') in _SIGN_FACES[pg]:
                exp = fg.default_grouping(r['PrimaryGroup'], led, entity_type, closing)
                if exp.get('face') != g.get('face'):
                    return exp, 'resign'
            return g, src

        if led in saved and isinstance(saved[led], dict) and saved[led].get('face'):
            g, src = _resign(dict(saved[led]), 'saved')
        elif led in saved_py and isinstance(saved_py[led], dict) and saved_py[led].get('face'):
            g, src = _resign(dict(saved_py[led]), 'carry')
        else:
            g = fg.default_grouping(r['PrimaryGroup'], led, entity_type, closing)
            src = 'default'

        pyg = saved_py.get(led, {})
        if not isinstance(pyg, dict):
            pyg = {}
        work[led] = {
            'face': g.get('face', 'Not Mapped'),
            'note': g.get('note', ''),
            'subnote': g.get('subnote', ''),
            'py_face': pyg.get('face', ''),
            'py_note': pyg.get('note', ''),
            'py_subnote': pyg.get('subnote', ''),
            'py_closing': py_closing.get(led, 0.0),
            'primary_group': r['PrimaryGroup'],
            'parent': r['Parent'],
            'closing': closing,
            'source': src,
        }
    return work


def build_py_working_mapping(company, entity_type="Partnership"):
    """Working mapping for the PREVIOUS year (comparative). Uses the previous-FY
    master + the saved previous-year grouping (grouping_py), falling back to the
    predefined rules for any ledger without a PY grouping. Empty if no previous FY."""
    pfy = get_previous_fy(company)
    if not pfy or not os.path.exists(master_path(company, pfy)):
        return {}
    tb = load_tb(company, pfy)
    gp = load_grouping_py(company)
    entity_type = entity_type_label(company) or entity_type
    work = {}
    for _, r in tb.iterrows():
        led = r['Ledger']
        closing = float(r['Closing'])
        g = gp.get(led) if isinstance(gp.get(led), dict) else None
        if not (g and g.get('face')):
            g = fg.default_grouping(r['PrimaryGroup'], led, entity_type, closing)
        work[led] = {
            'face': g.get('face', 'Not Mapped'),
            'note': g.get('note', ''),
            'subnote': g.get('subnote', ''),
            'primary_group': r['PrimaryGroup'],
            'parent': r['Parent'],
            'closing': closing,
        }
    return work


def working_to_df(work):
    rows = [{
        'Ledger': k,
        'PrimaryGroup': v.get('primary_group', ''),
        'Closing': v.get('closing', 0.0),
        'Face': v.get('face', 'Not Mapped'),
        'Note': v.get('note', ''),
        'SubNote': v.get('subnote', ''),
    } for k, v in work.items()]
    return pd.DataFrame(rows, columns=['Ledger', 'PrimaryGroup', 'Closing', 'Face', 'Note', 'SubNote'])
