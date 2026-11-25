"""
contra_engine.py — group-wide inter-se / contra balance reconciliation.

A "group" is a flat set of related concerns (companies, directors, firms, HUFs)
that trade with or lend to each other. Each concern's book holds a ledger for
the others (Sundry Debtor / Creditor / Loan / Advance). Reciprocal balances
should be EQUAL and OPPOSITE. This reads only the consolidated master
(ledger name + closing balance + primary group) — no transactions.

Balance sign convention (matches ledger scrutiny): CREDIT balances are POSITIVE,
DEBIT balances are NEGATIVE. A genuine contra pair is opposite in sign, equal in
magnitude.

Group config (JSON in paths.BASE/_contra_groups/<name>.json):
    { name, fy, entities:[str], pairs:[{A, A_Ledger, B, B_Ledger}] }
"""
import os
import re
import json
import difflib
import pandas as pd

import paths

_GROUPS_DIRNAME = "_contra_groups"
_MASTER_CSV = "Conso_MasterData.csv"
DEFAULT_TOLERANCE = 1.0        # ₹ — rounding wiggle for "matched"
MATCH_THRESHOLD = 0.82         # fuzzy score at/above which a name is a candidate

# Primary groups whose ledgers can hold an inter-concern balance.
PARTY_GROUPS = {
    "sundry debtors", "sundry creditors",
    "loans & advances (asset)", "loans (liability)",
    "secured loans", "unsecured loans",
}

# Profit & Loss groups — excluded. Contra deals with CLOSING BALANCES, so only
# Balance-Sheet ledgers are relevant (sales/purchase/income/expense are P&L).
PL_GROUPS = {
    "sales accounts", "purchase accounts",
    "direct incomes", "indirect incomes", "direct income", "indirect income",
    "direct expenses", "indirect expenses", "direct expense", "indirect expense",
}


def _is_bs(group):
    """True if the primary group is a Balance-Sheet group (not P&L)."""
    return str(group).strip().lower() not in PL_GROUPS

# Stripped when comparing a ledger name to an entity name.
_NOISE_TOKENS = {
    "loan", "loans", "ac", "acc", "account", "accounts", "current", "capital",
    "huf", "opening", "closing", "ledger", "pvt", "private", "ltd", "limited",
    "limted", "limitd", "ltda", "pvtltd", "llp", "co", "company", "companies",
    "the", "and", "mr", "mrs", "ms", "shri", "smt", "prop", "proprietor",
    "director", "advance", "advances", "group",
}


def _tok_eq(a, b):
    """Two name tokens count as the same if equal, or one is a prefix of the
    other (len ≥ 5) — bridges singular/plural and minor endings:
    'formulation' ≈ 'formulations', 'developer' ≈ 'developers'."""
    return a == b or (len(a) >= 5 and len(b) >= 5 and (a.startswith(b) or b.startswith(a)))


def _token_subset(e_tok, l_tok):
    """Every entity token has a (prefix-tolerant) match in the ledger tokens."""
    return all(any(_tok_eq(et, lt) for lt in l_tok) for et in e_tok)


def _s(x):
    """NaN-safe string (bundled pandas uses Arrow strings; blanks become NaN)."""
    return "" if x is None or (isinstance(x, float) and pd.isna(x)) else str(x)


# ── Entity / master access ────────────────────────────────────────────────────
def _master_path(company, fy):
    return paths.consolidated_dir(company, fy) / _MASTER_CSV


def list_master_entities(fy):
    base = paths.BASE
    if not base.exists():
        return []
    return [d for d in sorted(os.listdir(base))
            if (base / d).is_dir() and _master_path(d, fy).exists()]


def load_ledgers(company, fy):
    """{ledger_name: {'balance': float, 'group': str}} — ALL ledgers."""
    p = _master_path(company, fy)
    if not p.exists():
        return {}
    try:
        df = pd.read_csv(p)
    except Exception:
        return {}
    if "$Name" not in df.columns:
        return {}
    bal = pd.to_numeric(df.get("$ClosingBalance"), errors="coerce").fillna(0.0).tolist()
    names = df["$Name"].tolist()
    grp = (df["$_PrimaryGroup"].tolist() if "$_PrimaryGroup" in df.columns
           else [""] * len(df))
    out = {}
    for name, b, g in zip(names, bal, grp):
        nm = _s(name).strip()
        if nm:
            out[nm] = {"balance": float(b), "group": _s(g).strip()}
    return out


def load_party_ledgers(company, fy):
    """Only ledgers in PARTY_GROUPS — the reconcilable candidates."""
    return {nm: v for nm, v in load_ledgers(company, fy).items()
            if v["group"].strip().lower() in PARTY_GROUPS}


def party_ledger_names(entities, fy):
    """Sorted union of party-ledger names across entities (dropdown options)."""
    names = set()
    for e in entities:
        names.update(load_party_ledgers(e, fy).keys())
    return sorted(names)


def _inr(x):
    """Indian-grouped integer string, e.g. 120000 -> '1,20,000'."""
    x = abs(int(round(float(x or 0))))
    s = str(x)
    if len(s) <= 3:
        return s
    head, tail = s[:-3], s[-3:]
    head = re.sub(r"(\d)(?=(\d\d)+$)", r"\1,", head)
    return head + "," + tail


def fmt_bal(x):
    """'1,20,000 Cr' / '45,000 Dr' — credit +, debit − (statement convention)."""
    x = float(x or 0)
    dc = "Cr" if x > 0 else ("Dr" if x < 0 else "")
    return (f"{_inr(x)} {dc}").strip() or "0"


def entity_party_groups(entity, fy):
    """Distinct primary groups present among an entity's party ledgers."""
    gs = {v["group"] for v in load_party_ledgers(entity, fy).values() if v["group"]}
    return sorted(gs)


def ledgers_in_groups(entity, fy, groups=None):
    """(name, balance, group) for an entity, restricted to `groups`
    (case-insensitive) or to all PARTY_GROUPS when groups is None."""
    want = {g.strip().lower() for g in groups} if groups else PARTY_GROUPS
    out = [(nm, v["balance"], v["group"]) for nm, v in load_ledgers(entity, fy).items()
           if v["group"].strip().lower() in want]
    out.sort(key=lambda t: t[0].lower())
    return out


def source_candidates(source, others, fy):
    """The source concern's ledgers — across ALL primary groups (Investments,
    etc. included) — whose NAME resembles another concern in the group, each
    with a suggested counterpart concern + ledger. The counterpart ledger is
    chosen by name fuzzy-match to the SOURCE, then NEAREST OPPOSITE amount among
    those. Returns [{ledger, balance, group, sugg_concern, sugg_ledger}] sorted
    by suggested concern then ledger name."""
    ofeat = {o: _features(o) for o in others}
    oled = {o: load_ledgers(o, fy) for o in others}        # ALL ledgers
    src_tok, src_comp = _features(source)
    rows = []
    for nm, v in load_ledgers(source, fy).items():          # ALL source ledgers
        if not _is_bs(v["group"]):                           # skip P&L ledgers
            continue
        l_tok, l_comp = _features(nm)
        best_o = None                                        # concern this ledger names
        for o in others:
            ot, oc = ofeat[o]
            sc = _score(ot, oc, l_tok, l_comp, floor=CANDIDATE_THRESHOLD)
            if sc >= CANDIDATE_THRESHOLD and (best_o is None or sc > best_o[1]):
                best_o = (o, sc)
        if not best_o:
            continue
        o = best_o[0]
        # o's ledgers whose name resembles the SOURCE; pick nearest opposite amt.
        cand = []
        for onm, ov in oled[o].items():
            if not _is_bs(ov["group"]):
                continue
            ot2, oc2 = _features(onm)
            if _score(src_tok, src_comp, ot2, oc2, floor=CANDIDATE_THRESHOLD) >= CANDIDATE_THRESHOLD:
                cand.append((onm, ov["balance"]))
        cand.sort(key=lambda t: abs(v["balance"] + t[1]))    # nearest opposite first
        rows.append({"ledger": nm, "balance": v["balance"], "group": v["group"],
                     "sugg_concern": o, "sugg_ledger": cand[0][0] if cand else ""})
    rows.sort(key=lambda r: (r["sugg_concern"].lower(), r["ledger"].lower()))
    return rows


def all_source_ledgers(entity, fy):
    """(name, balance, group) for EVERY ledger of a concern (add-a-ledger pool),
    sorted by name."""
    items = [(nm, v["balance"], v["group"]) for nm, v in load_ledgers(entity, fy).items()
             if _is_bs(v["group"])]
    items.sort(key=lambda t: t[0].lower())
    return items


def concern_ledger_options(target, source, fy, show_all=False):
    """Counterpart-ledger options in `target`. By default only ledgers whose
    name resembles the SOURCE concern (across all groups), sorted by name;
    show_all=True returns every ledger (fallback when the match isn't found).
    Returns (name, balance, group)."""
    src_tok, src_comp = _features(source)
    out = []
    for nm, v in load_ledgers(target, fy).items():
        if not _is_bs(v["group"]):                       # balance-sheet only
            continue
        if not show_all:
            l_tok, l_comp = _features(nm)
            if _score(src_tok, src_comp, l_tok, l_comp, floor=CANDIDATE_THRESHOLD) < CANDIDATE_THRESHOLD:
                continue
        out.append((nm, v["balance"], v["group"]))
    out.sort(key=lambda t: t[0].lower())
    return out


def entity_ledger_options(entity, fy, target=None):
    """Party ledgers of one entity for the picker, as [(label, name, balance)].
    If `target` is given, sort by nearest OPPOSITE amount (|target+bal| asc) so a
    genuine contra floats to the top even when the name differs; else by |bal|."""
    items = list(load_party_ledgers(entity, fy).items())
    if target is None:
        items.sort(key=lambda kv: abs(kv[1]["balance"]), reverse=True)
        return [(f"{nm}  ·  {fmt_bal(v['balance'])}", nm, v["balance"]) for nm, v in items]
    items.sort(key=lambda kv: abs(float(target) + kv[1]["balance"]))
    out = []
    for nm, v in items:
        d = float(target) + v["balance"]
        tag = "  ✓ match" if abs(d) <= DEFAULT_TOLERANCE else f"  Δ {fmt_bal(d)}"
        out.append((f"{nm}  ·  {fmt_bal(v['balance'])}{tag}", nm, v["balance"]))
    return out


# ── Name matching ─────────────────────────────────────────────────────────────
def _tokens(text):
    raw = re.sub(r"[^a-z0-9]+", " ", str(text).lower()).split()
    return [t for t in raw if t not in _NOISE_TOKENS and len(t) > 1 and not t.isdigit()]


def _compress(text):
    """Significant name parts joined with no spaces — bridges initials and
    concatenation: 'A A Sample Name' and 'a.a.samplename' -> 'samplename'."""
    return "".join(_tokens(text))


def _features(name):
    """(token_set, compressed) — computed once per name, reused across scoring."""
    return set(_tokens(name)), _compress(name)


def _score(e_tok, e_comp, l_tok, l_comp, floor=0.0):
    """Fuzzy 0..1 from precomputed features. `floor` skips the costly difflib
    ratio when even its cheap upper bound can't reach it."""
    if not e_tok or not l_tok:
        return 0.0
    if _token_subset(e_tok, l_tok):               # every entity token present
        return 1.0
    if not e_comp or not l_comp:
        return 0.0
    if e_comp == l_comp:
        return 1.0
    if e_comp in l_comp or l_comp in e_comp:
        return 0.9
    sm = difflib.SequenceMatcher(None, e_comp, l_comp)
    if sm.real_quick_ratio() < floor or sm.quick_ratio() < floor:
        return 0.0
    return sm.ratio()


def match_score(entity_name, ledger_name):
    """0..1 — how strongly `ledger_name` refers to `entity_name`."""
    e_tok, e_comp = _features(entity_name)
    l_tok, l_comp = _features(ledger_name)
    return _score(e_tok, e_comp, l_tok, l_comp)


# ── Status ────────────────────────────────────────────────────────────────────
def pair_status(bal_a, bal_b, both_present, tol=DEFAULT_TOLERANCE):
    """(status, difference) where difference = |A| - |B| (0 for a clean contra).
    MATCHED / DIFFERENCE / SAME_SIGN / ONE_SIDE_ONLY.
    A zero (or near-zero) balance has NO sign, so 'same sign' is only reported
    when BOTH sides are non-zero and point the same way; a real amount facing a
    zero is a DIFFERENCE, not same-sign."""
    if not both_present:
        return "ONE_SIDE_ONLY", 0.0
    diff = abs(bal_a) - abs(bal_b)
    sa = 0 if abs(bal_a) <= tol else (1 if bal_a > 0 else -1)
    sb = 0 if abs(bal_b) <= tol else (1 if bal_b > 0 else -1)
    if sa == 0 and sb == 0:
        return "MATCHED", 0.0                 # both effectively nil
    if sa == 0 or sb == 0:
        return "DIFFERENCE", diff             # one real amount vs a nil balance
    if sa == sb:
        return "SAME_SIGN", diff              # both non-zero, same direction
    return ("MATCHED" if abs(diff) <= tol else "DIFFERENCE"), diff


# ── Auto-detect + candidate options (one precomputed pass) ────────────────────
CANDIDATE_THRESHOLD = 0.75     # bar for the manual-mapping dropdown list


def analyze(entities, fy):
    """Single pass over every entity's party ledgers. Returns:
        rows           — auto-detected reciprocal pairs {A, A_Ledger, B, B_Ledger}
        candidate_names— sorted ledger names that look inter-concern (dropdown
                         options), i.e. match SOME other entity at >= CANDIDATE.
    Only party-group ledgers are scanned; names are tokenised once."""
    ename = {e: _features(e) for e in entities}
    # best[e][other] = (ledger_name, balance, score) — a's ledger referring to other
    best = {e: {} for e in entities}
    candidate_names = set()

    for e in entities:
        et_self = ename[e]
        for nm, v in load_party_ledgers(e, fy).items():
            l_tok, l_comp = _features(nm)
            top = 0.0
            for o in entities:
                if o == e:
                    continue
                o_tok, o_comp = ename[o]
                sc = _score(o_tok, o_comp, l_tok, l_comp, floor=CANDIDATE_THRESHOLD)
                if sc < CANDIDATE_THRESHOLD:
                    continue
                top = max(top, sc)
                cur = best[e].get(o)
                if cur is None or sc > cur[2] or (
                        sc == cur[2] and abs(v["balance"]) > abs(cur[1])):
                    best[e][o] = (nm, v["balance"], sc)
            if top >= CANDIDATE_THRESHOLD:
                candidate_names.add(nm)

    rows = []
    for i in range(len(entities)):
        for j in range(i + 1, len(entities)):
            a, b = entities[i], entities[j]
            a_side = best[a].get(b)
            b_side = best[b].get(a)
            a_ok = a_side and a_side[2] >= MATCH_THRESHOLD
            b_ok = b_side and b_side[2] >= MATCH_THRESHOLD
            if not a_ok and not b_ok:
                continue
            rows.append({
                "A": a, "A_Ledger": a_side[0] if a_ok else "",
                "B": b, "B_Ledger": b_side[0] if b_ok else "",
            })
    return rows, sorted(candidate_names)


# ── Reconcile a mapping (used on every run) ───────────────────────────────────
def reconcile(pairs, fy, tol=DEFAULT_TOLERANCE):
    """Re-read current balances for the mapped pairs. `pairs`: list of dicts with
    A, A_Ledger, B, B_Ledger. Returns (DataFrame, summary)."""
    cache = {}

    def led(e):
        if e not in cache:
            cache[e] = load_ledgers(e, fy)      # full set, so any mapping resolves
        return cache[e]

    out = []
    for p in pairs:
        a, b = _s(p.get("A")).strip(), _s(p.get("B")).strip()
        an, bn = _s(p.get("A_Ledger")).strip(), _s(p.get("B_Ledger")).strip()
        if not a or not b:
            continue
        a_has = bool(an) and an in led(a)
        b_has = bool(bn) and bn in led(b)
        a_bal = led(a).get(an, {}).get("balance", 0.0) if a_has else 0.0
        b_bal = led(b).get(bn, {}).get("balance", 0.0) if b_has else 0.0
        status, diff = pair_status(a_bal, b_bal, a_has and b_has, tol)
        out.append({
            "Entity A": a, "Ledger A": an, "Balance A": round(a_bal, 2),
            "Entity B": b, "Ledger B": bn, "Balance B": round(b_bal, 2),
            "Difference": round(diff, 2), "Status": status,
        })
    df = pd.DataFrame(out, columns=["Entity A", "Ledger A", "Balance A",
                                    "Entity B", "Ledger B", "Balance B",
                                    "Difference", "Status"])
    summary = {
        "total": len(out),
        "matched": sum(1 for r in out if r["Status"] == "MATCHED"),
        "difference": sum(1 for r in out if r["Status"] == "DIFFERENCE"),
        "same_sign": sum(1 for r in out if r["Status"] == "SAME_SIGN"),
        "one_side": sum(1 for r in out if r["Status"] == "ONE_SIDE_ONLY"),
    }
    return df, summary


def matrix(pairs, entities, fy, tol=DEFAULT_TOLERANCE):
    """Cross-tab of inter-se balances. For each ordered (row, col) concern pair
    returns {'bal': net balance in ROW's own books for COL, 'status': ...}.
    All ledgers between two concerns are NETTED, and the status compares the two
    concerns' net figures. Returns {row: {col: {'bal', 'status'}}}."""
    cache = {}

    def led(e):
        if e not in cache:
            cache[e] = load_ledgers(e, fy)
        return cache[e]

    net = {}                                   # frozenset{A,B} -> {ent: [sum, booked]}
    for p in pairs:
        a, b = _s(p.get("A")).strip(), _s(p.get("B")).strip()
        if not a or not b or a == b:
            continue
        aL, bL = _s(p.get("A_Ledger")).strip(), _s(p.get("B_Ledger")).strip()
        a_bal = led(a).get(aL, {}).get("balance", 0.0) if aL else 0.0
        b_bal = led(b).get(bL, {}).get("balance", 0.0) if bL else 0.0
        d = net.setdefault(frozenset({a, b}), {})
        da = d.setdefault(a, [0.0, False]); da[0] += a_bal; da[1] = da[1] or bool(aL)
        db = d.setdefault(b, [0.0, False]); db[0] += b_bal; db[1] = db[1] or bool(bL)

    mat = {r: {} for r in entities}
    for d in net.values():
        if len(d) != 2:
            continue
        (a, (sa, pa)), (b, (sb, pb)) = list(d.items())
        status, _ = pair_status(sa, sb, pa and pb, tol)
        if a in mat:
            mat[a][b] = {"bal": sa, "status": status}
        if b in mat:
            mat[b][a] = {"bal": sb, "status": status}
    return mat


# ── Group config persistence ──────────────────────────────────────────────────
def _groups_dir():
    d = paths.BASE / _GROUPS_DIRNAME
    d.mkdir(parents=True, exist_ok=True)
    return d


def _safe_group_file(name):
    slug = re.sub(r"[^A-Za-z0-9._ -]+", "_", str(name).strip()) or "group"
    return _groups_dir() / f"{slug}.json"


def group_key(name):
    """The list_groups() identifier (file stem) a given name saves under."""
    return _safe_group_file(name).stem


def list_groups():
    d = paths.BASE / _GROUPS_DIRNAME
    return sorted(p.stem for p in d.glob("*.json")) if d.exists() else []


def _migrate(obj):
    """Bring an old-schema group (companies/individuals + Company/Individual
    pairs) up to the flat entities + A/B schema."""
    if "entities" in obj:
        return obj
    ents = list(dict.fromkeys((obj.get("companies") or []) + (obj.get("individuals") or [])))
    pairs = [{"A": p.get("Company", ""), "A_Ledger": p.get("Company_Ledger", ""),
              "B": p.get("Individual", ""), "B_Ledger": p.get("Individual_Ledger", "")}
             for p in obj.get("pairs", [])]
    obj["entities"], obj["pairs"] = ents, pairs
    obj.setdefault("dismissed", {})
    obj.setdefault("extra", {})
    return obj


def load_group(name):
    p = _safe_group_file(name)
    if not p.exists():
        return None
    try:
        obj = _migrate(json.loads(p.read_text(encoding="utf-8")))
        obj.setdefault("dismissed", {})
        obj.setdefault("extra", {})
        return obj
    except Exception:
        return None


def save_group(name, entities, pairs, fy, dismissed=None, extra=None):
    obj = {
        "name": str(name).strip(),
        "fy": str(fy).strip(),
        "entities": list(entities),
        "pairs": [{"A": _s(p.get("A")).strip(), "A_Ledger": _s(p.get("A_Ledger")).strip(),
                   "B": _s(p.get("B")).strip(), "B_Ledger": _s(p.get("B_Ledger")).strip()}
                  for p in pairs
                  if _s(p.get("A")).strip() and _s(p.get("B")).strip()],
        # Per-concern removed ledgers (🗑) and manually added ledgers, so the
        # working state survives reload.
        "dismissed": {k: sorted(v) for k, v in (dismissed or {}).items() if v},
        "extra": {k: list(v) for k, v in (extra or {}).items() if v},
    }
    paths.atomic_write_json(_safe_group_file(name), obj)
    return obj


def delete_group(name):
    p = _safe_group_file(name)
    if p.exists():
        p.unlink()
