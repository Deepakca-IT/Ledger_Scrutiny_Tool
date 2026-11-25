"""
NCE Financial Statements — aggregation + balance check.

Turns the working grouping (from fs_engine.build_working_mapping) plus the
user-entered stock and manual adjustments into statement-section totals and a
balance check. This is the shared foundation for the BS / P&L / Notes viewer.

Sign convention (same as the master data): Debit = negative, Credit = positive.
  - Assets / expenses  -> negative
  - Equity / liabilities / income -> positive

Stock (not extracted from Tally; entered by the user as positive figures):
  - Closing stock -> Inventories, a BS asset      -> row closing = -closing_stock
  - Changes in inventories (P&L) = Opening - Closing
        as a signed expense the line = (closing_stock - opening_stock)
        (positive => credit, i.e. stock rose and cost falls; negative => cost)

Why the books balance: Tally keeps stock in inventory, not in ledgers, so the
extracted trial balance is short on the debit side by exactly the opening stock.
Injecting the Inventories asset (-closing) and the Changes line (closing-opening)
contributes a net of (-opening) which cancels that shortfall. Hence the signed
sum of every row (TB + injected stock + adjustments) is the balance difference,
and it is zero when the entered opening stock equals the real carried-forward stock.
"""
import fs_grouping as fg
import fs_engine as fe

CLOSING_STOCK_FACE = "Inventories"
CLOSING_STOCK_NOTE = "Stock-in-trade"
CHANGES_FACE = "Change in Inventories of work in progress and finished goods"
CHANGES_NOTE = "Changes in inventories of FG / WIP / stock-in-trade"
COST_FACE = "Cost of material consumed"
DISCLOSURE_NOTE = "Captured from Disclosure Tab"


def _f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return 0.0


def fmt_amt(x, dash_zero=True, decimals=0):
    """Indian-grouped amount. None -> '', negative -> (parentheses)."""
    if x is None:
        return ""
    try:
        x = float(x)
    except (TypeError, ValueError):
        return ""
    thresh = 0.005 if decimals else 0.5
    if dash_zero and abs(x) < thresh:
        return "-"
    neg = x < 0
    a = abs(x)
    ip = str(int(a))
    dp = ""
    if decimals:
        dp = f"{a - int(a):.{decimals}f}"[1:]  # ".dd"
    if len(ip) > 3:
        last3, rest, groups = ip[-3:], ip[:-3], []
        while len(rest) > 2:
            groups.append(rest[-2:]); rest = rest[:-2]
        if rest:
            groups.append(rest)
        groups.reverse()
        ip = ",".join(groups) + "," + last3
    s = ip + dp
    return f"({s})" if neg else s


def _fold_l3(note, subnote):
    """'Specify at Level 3' notes display the (mandatory) sub-note AT NOTE LEVEL:
    the sub-note text becomes the note label and the sub-note level disappears."""
    if fg.is_specify_l3(note):
        return (_scol_str(subnote) or 'Others'), ''
    return note, subnote


def _scol_str(x):
    s = '' if x is None else str(x).strip()
    return '' if s.lower() == 'nan' else s


CWIP_FACE = "Capital work in progress"
INTAN_DEV_FACE = "Intangible assets under development"


def build_rows(work, aux, inv=None, inv_side='cy', fa=None, fa_side='cy'):
    """Flatten the working mapping + injected stock + manual adjustments into a
    list of {ledger, face, note, subnote, section, closing, kind} rows.

    `inv` is the optional Inventories disclosure (Cost of material consumed +
    Change in inventories). When it is filled it REPLACES the single opening/
    closing-stock injection: only the stock movement (Opening − Closing) hits the
    balance, split across the Inventories asset, Cost-of-material and Change-in-
    inventories faces; purchases stay in the trial balance.

    `fa` is the optional Fixed Assets disclosure (Capital WIP + Intangible assets
    under development). For each disclosed block the closing balance OVERRIDES that
    face: existing ledger rows for the face are dropped and replaced by the
    disclosure closing, so the Balance-Sheet figure is driven by the schedule."""
    rows = []
    for led, v in (work or {}).items():
        face = v.get('face', 'Not Mapped')
        note, subnote = _fold_l3(v.get('note', ''), v.get('subnote', ''))
        rows.append({
            'ledger': led,
            'face': face,
            'note': note,
            'subnote': subnote,
            'section': fg.face_section(face),
            'closing': _f(v.get('closing', 0.0)),
            'kind': 'ledger',
        })

    if inv and inv.get('disclose'):
        t = fe.inventory_totals(inv, inv_side)
        c_tot, o_tot = t['closing_total'], t['opening_total']
        c_mat, o_mat = t['closing_mat'], t['opening_mat']
        c_fg, o_fg = t['closing_fg'], t['opening_fg']
        # BS asset = total closing stock (replaces the single closing-stock field).
        if abs(c_tot) > 0:
            rows.append({
                'ledger': 'Closing inventories', 'face': CLOSING_STOCK_FACE,
                'note': DISCLOSURE_NOTE, 'subnote': '',
                'section': fg.face_section(CLOSING_STOCK_FACE),
                'closing': -abs(c_tot), 'kind': 'stock',
            })
        # P&L material-stock movement (Opening − Closing) -> Cost of material consumed.
        if abs(c_mat) > 0 or abs(o_mat) > 0:
            rows.append({
                'ledger': 'Material stock movement', 'face': COST_FACE,
                'note': DISCLOSURE_NOTE, 'subnote': '',
                'section': fg.face_section(COST_FACE),
                'closing': c_mat - o_mat, 'kind': 'stock',
            })
        # P&L FG/WIP-stock movement -> Change in inventories.
        if abs(c_fg) > 0 or abs(o_fg) > 0:
            rows.append({
                'ledger': 'Changes in inventories', 'face': CHANGES_FACE,
                'note': DISCLOSURE_NOTE, 'subnote': '',
                'section': fg.face_section(CHANGES_FACE),
                'closing': c_fg - o_fg, 'kind': 'stock',
            })
    else:
        aux = aux or {}
        opening = _f(aux.get('opening_stock'))
        closing = _f(aux.get('closing_stock'))
        if abs(closing) > 0:
            rows.append({
                'ledger': 'Closing Stock', 'face': CLOSING_STOCK_FACE,
                'note': CLOSING_STOCK_NOTE, 'subnote': 'As valued and certified by management',
                'section': fg.face_section(CLOSING_STOCK_FACE),
                'closing': -abs(closing), 'kind': 'stock',
            })
        if abs(opening) > 0 or abs(closing) > 0:
            rows.append({
                'ledger': 'Changes in inventories', 'face': CHANGES_FACE,
                'note': CHANGES_NOTE, 'subnote': '',
                'section': fg.face_section(CHANGES_FACE),
                'closing': abs(closing) - abs(opening), 'kind': 'stock',
            })

    for adj in aux.get('adjustments', []) or []:
        if not isinstance(adj, dict):
            continue
        led = str(adj.get('ledger', '')).strip()
        amt = _f(adj.get('closing'))
        if not led and amt == 0:
            continue
        face = adj.get('face', 'Not Mapped') or 'Not Mapped'
        note, subnote = _fold_l3(adj.get('note', ''), adj.get('subnote', ''))
        rows.append({
            'ledger': led or 'Adjustment',
            'face': face,
            'note': note,
            'subnote': subnote,
            'section': fg.face_section(face),
            'closing': amt,
            'kind': 'adjustment',
        })

    # Fixed Assets disclosure: a disclosed block's closing OVERRIDES its face
    # (drop the ledger rows, inject the schedule closing as the asset value).
    if fa:
        for key, face in (('cwip', CWIP_FACE), ('intan_dev', INTAN_DEV_FACE)):
            blk = fa.get(key, {})
            if fe.fa_block_discloses(blk):
                rows = [r for r in rows if r['face'] != face]
                closing = fe.fa_closing(blk, fa_side)
                if abs(closing) > 0.005:
                    rows.append({
                        'ledger': face, 'face': face,
                        'note': 'Captured in PPE Notes', 'subnote': '',
                        'section': fg.face_section(face),
                        'closing': -closing, 'kind': 'fa',
                    })
    return rows


def compute(work, aux, entity_type="Partnership", inv=None, inv_side='cy',
            fa=None, fa_side='cy'):
    """Aggregate rows into section totals + balance check.
    Returns a dict (all amounts SIGNED, debit negative)."""
    rows = build_rows(work, aux, inv=inv, inv_side=inv_side, fa=fa, fa_side=fa_side)

    section_totals = {k: 0.0 for k in
                      ('asset', 'liability', 'equity', 'income', 'expense', 'unmapped')}
    by_face, by_face_note = {}, {}
    for r in rows:
        section_totals[r['section']] = section_totals.get(r['section'], 0.0) + r['closing']
        by_face[r['face']] = by_face.get(r['face'], 0.0) + r['closing']
        key = (r['face'], r['note'])
        by_face_note[key] = by_face_note.get(key, 0.0) + r['closing']

    income = section_totals['income']
    expense = section_totals['expense']
    profit = income + expense                      # credit-positive => net profit
    assets_signed = section_totals['asset']        # debit-negative
    unmapped = section_totals['unmapped']

    raw_difference = sum(r['closing'] for r in rows)
    # How much current-year profit do we transfer into the surplus / capital face?
    # `base_profit` = the profit Tally already rolled into its extracted surplus = the
    # P&L of the ORIGINAL books (ledgers + stock), EXCLUDING our manual adjustments — a
    # tool-side reconciling entry (e.g. depreciation) was never posted in Tally, so it
    # is NOT inside the extracted capital.
    base_profit = sum(r['closing'] for r in rows
                      if r.get('kind') != 'adjustment'
                      and r['section'] in ('income', 'expense'))
    # Balance-sheet sections across ALL rows (ledgers + stock + adjustments):
    bs_signed = (section_totals['asset'] + section_totals['liability']
                 + section_totals['equity'])
    # Two hypotheses — pick whichever actually ties the balance sheet:
    #   • surplus ALREADY holds base_profit  -> transfer only the un-booked delta
    #     (profit − base_profit). For a Dr P&L / Cr asset adjustment this delta is
    #     NEGATIVE (= −D), pulling the surplus down by exactly the asset reduction, so
    #     the BS still ties AND the brought-forward (= surplus − profit) stays put.
    #   • surplus EXCLUDES the profit         -> transfer the full current profit.
    # Using base_profit (not the full profit) is what makes a tool-side depreciation
    # adjustment balance without shifting the opening capital.
    pta_incl = profit - base_profit
    pta_excl = profit
    diff_incl = bs_signed + pta_incl
    diff_excl = bs_signed + pta_excl
    if abs(diff_incl) <= abs(diff_excl):
        profit_to_add, difference, baked_profit, add_profit = \
            pta_incl, diff_incl, base_profit, False
    else:
        profit_to_add, difference, baked_profit, add_profit = \
            pta_excl, diff_excl, 0.0, True
    funds_signed = (section_totals['equity'] + section_totals['liability'] + profit_to_add)

    return {
        'rows': rows,
        'section_totals': section_totals,
        'by_face': by_face,
        'by_face_note': by_face_note,
        'income': income,
        'expense': expense,
        'profit': profit,
        'add_profit': add_profit,                  # False => surplus already includes profit
        'baked_profit': baked_profit,              # profit Tally already put in the surplus
        'profit_to_add': profit_to_add,            # amount to transfer into the surplus face
        'assets_total': abs(assets_signed),        # presentation (positive)
        'funds_total': funds_signed,               # equity + liab + profit_to_add
        'unmapped_total': unmapped,
        'raw_difference': raw_difference,
        'difference': difference,                  # BS gap (Assets − Funds); ~0 when it ties
        'balanced': abs(difference) < 0.5,
        'has_unmapped': abs(unmapped) > 0.5,
    }


# ── FAR: Income-tax WDV depreciation per asset, rolled up by block ────────────
def compute_far(rows):
    """Per-asset IT-Act WDV depreciation + block roll-up.
    - rate: per-row override, else the block's master rate.
    - opening_net = opening_gross - opening_accumulated (accum optional/zero).
    - dep = rate% on (opening_net + additions<=180d - sale), half rate on additions>180d.
    - total_dep = dep + manual_adj; closing_net = closing_gross - closing_accum.
    Net Block PY column = opening_net (= prior year's closing net).
    """
    from collections import OrderedDict as _OD
    assets, blocks = [], _OD()
    for r in (rows or []):
        cat = (r.get('category') or 'Tangible')
        block = (r.get('block') or '')
        rate = r.get('rate')
        rate = float(rate) if rate not in (None, '') else fg.far_rate(cat, block)
        og = _f(r.get('opening_gross')); oacc = _f(r.get('opening_accum'))
        ab = _f(r.get('add_before180'))           # used >=180 days -> full rate
        aa = _f(r.get('add_after180'))            # used  <180 days -> half rate
        sale = _f(r.get('sale')); madj = _f(r.get('manual_adj'))
        opening_net = og - oacc
        base_full = max(opening_net + ab - sale, 0.0)
        dep = (rate / 100.0) * base_full + (rate / 200.0) * aa
        if dep < 0:
            dep = 0.0
        total_dep = dep + madj
        closing_gross = og + ab + aa - sale
        closing_accum = oacc + total_dep
        closing_net = closing_gross - closing_accum
        assets.append({**r, 'rate': rate, 'opening_net': opening_net, 'dep': dep,
                       'total_dep': total_dep, 'additions': ab + aa,
                       'closing_gross': closing_gross, 'closing_accum': closing_accum,
                       'closing_net': closing_net})
        key = (cat, block)
        b = blocks.get(key)
        if b is None:
            b = dict(category=cat, block=block, g_open=0.0, g_add=0.0, g_ded=0.0,
                     g_close=0.0, d_open=0.0, d_year=0.0, d_ded=0.0, d_close=0.0,
                     n_open=0.0, n_close=0.0)
            blocks[key] = b
        b['g_open'] += og; b['g_add'] += ab + aa; b['g_ded'] += sale
        b['g_close'] += closing_gross
        b['d_open'] += oacc; b['d_year'] += total_dep; b['d_close'] += closing_accum
        b['n_open'] += opening_net; b['n_close'] += closing_net

    faces = {}
    for b in blocks.values():
        f = fg.far_face(b['category'])
        fa = faces.setdefault(f, dict(g_open=0.0, g_add=0.0, g_ded=0.0, g_close=0.0,
                                      d_open=0.0, d_year=0.0, d_ded=0.0, d_close=0.0,
                                      n_open=0.0, n_close=0.0, blocks=[]))
        for k in ('g_open', 'g_add', 'g_ded', 'g_close', 'd_open', 'd_year',
                  'd_ded', 'd_close', 'n_open', 'n_close'):
            fa[k] += b[k]
        fa['blocks'].append(b)
    return {'assets': assets, 'blocks': blocks, 'faces': faces}


def far_seed_rows(computed):
    """Build next-year opening rows from this year's FAR closing (roll-forward):
    opening_gross <- closing_gross, opening_accum <- closing_accum, movements zeroed."""
    seed = []
    for a in computed.get('assets', []):
        seed.append({'id': a.get('id', ''), 'name': a.get('name', ''),
                     'category': a.get('category', 'Tangible'), 'block': a.get('block', ''),
                     'rate': None, 'opening_gross': round(a.get('closing_gross', 0.0), 2),
                     'add_before180': 0.0, 'add_after180': 0.0, 'sale': 0.0,
                     'opening_accum': round(a.get('closing_accum', 0.0), 2),
                     'manual_adj': 0.0})
    return seed


# ── Reconciliation (Check tab): Notes/FAR vs the books (TB), CY + PY ──────────
def reconciliation(company, entity_type=None, work_override=None):
    """List of check items comparing the FAR/Notes figures with the books (TB).
    Each item: {key, particulars, far_cy, books_cy, diff_cy, far_py, books_py, diff_py}.
    `far_*` = as per Notes/FAR, `books_*` = as per Balance Sheet / P&L (ledgers).
    Differences are EXPECTED when FAR depreciation isn't booked in the TB — the user
    reconciles them with a manual adjustment under Grouping & adjustments."""
    ent = fe.load_entity(company)
    entity_type = entity_type or fe.grouping_entity_type(company)
    cy_label = fe.get_current_fy(company) or ''
    py_label = fe.get_previous_fy(company) or ''
    opts = ent.get('options', {})

    inv_cy = fe.load_inventory(company, cy_label)
    fa_cy = fe.load_fixed_assets(company, cy_label)
    work_cy = (work_override if work_override is not None
               else fe.build_working_mapping(company, entity_type))
    rep_cy = compute(work_cy, fe.load_aux(company, cy_label), entity_type,
                     inv=inv_cy, inv_side='cy', fa=fa_cy, fa_side='cy')
    work_py = fe.build_py_working_mapping(company, entity_type)
    rep_py = compute(work_py, fe.load_aux(company, py_label), entity_type) if work_py else None

    def books_face(rep, face):
        return None if not rep else _present(face, rep['by_face'].get(face, 0.0))

    items = []
    if opts.get('depreciation') != 'FAR IT':
        return items

    far_cy = compute_far(fe.load_far(company, cy_label))
    far_py = compute_far(fe.load_far(company, py_label)) if py_label else {'faces': {}, 'blocks': {}}

    def _mk(key, particulars, far_cy_v, books_cy_v, far_py_v, books_py_v):
        def _d(a, b):
            if a is None and b is None:
                return None
            return (a or 0.0) - (b or 0.0)
        items.append({'key': key, 'particulars': particulars,
                      'far_cy': far_cy_v, 'books_cy': books_cy_v, 'diff_cy': _d(far_cy_v, books_cy_v),
                      'far_py': far_py_v, 'books_py': books_py_v, 'diff_py': _d(far_py_v, books_py_v)})

    for face in ('Property Plant and Equipment', 'Intangible assets'):
        fcy = far_cy['faces'].get(face, {}).get('n_close')
        fpy = far_py['faces'].get(face, {}).get('n_close')
        bcy, bpy = books_face(rep_cy, face), books_face(rep_py, face)
        if any(v not in (None, 0, 0.0) for v in (fcy, fpy, bcy, bpy)):
            _mk(f'net::{face}', f'{face} — Note (FAR) vs Balance Sheet', fcy, bcy, fpy, bpy)

    dep_face = 'Depreciation and amortization expenses'
    dcy = sum(b['d_year'] for b in far_cy['blocks'].values()) if far_cy['blocks'] else 0.0
    dpy = sum(b['d_year'] for b in far_py['blocks'].values()) if far_py['blocks'] else 0.0
    _mk('dep', 'Depreciation — Note (FAR) vs Statement of P&L',
        dcy, books_face(rep_cy, dep_face), dpy, books_face(rep_py, dep_face))
    return items


# ── Statement assembly (Balance Sheet / P&L / Notes, with comparatives) ───────
# Presentation sign: liabilities/equity/income shown as-is (credit +); assets and
# expenses flipped to natural positive figures.
_CREDIT_SECTIONS = ('liability', 'equity', 'income')
# Current-year profit is transferred to Reserves & Surplus (Surplus in P&L) — the
# same head Tally's "Profit & Loss A/c" ledger maps to. Configurable later.
PROFIT_FACE = "Reserves and surplus"
PROFIT_NOTE_LABEL = "Add: Profit / (Loss) for the year"
_NEAR_ZERO = 0.5


def _present(face, signed):
    return signed if fg.face_section(face) in _CREDIT_SECTIONS else -signed


def _byface_with_profit(rep):
    """Reserves & Surplus carries the current-year profit. Transfer in only the part
    not already baked into the surplus ledger (rep['profit_to_add'])."""
    d = dict(rep['by_face'])
    d[PROFIT_FACE] = d.get(PROFIT_FACE, 0.0) + rep.get('profit_to_add', 0.0)
    return d


def _nz(*vals):
    return any(v is not None and abs(v) >= _NEAR_ZERO for v in vals)


def statements(company, entity_type=None, work_override=None):
    """Assemble Balance Sheet, Statement of P&L and Notes (current + previous year).
    `work_override` lets the viewer pass the live in-memory current-year mapping so
    statements reflect applied (not-yet-saved-to-disk) grouping edits.
    Returns a dict the UI/exporters render generically."""
    ent = fe.load_entity(company)
    entity_type = entity_type or fe.grouping_entity_type(company)

    cy_label = fe.get_current_fy(company) or ''
    py_label = fe.get_previous_fy(company) or ''

    opts = ent.get('options', {})
    pres = ent.get('presentation', {})
    prnt = ent.get('print', {})
    divisor, units_label = fe.units(pres.get('round_off', 'In Rs'))
    hide_zero = bool(prnt.get('face_hide_zero', True))
    notes_start = int(prnt.get('notes_start', 3) or 3)
    zthresh = 0.5 / divisor   # "non-zero" test on scaled values (= ₹0.5 actual)

    def _nzf(*vals):
        return any(v is not None and abs(v) >= zthresh for v in vals)

    # Current-year profit destination (Reserves by default; optionally capital).
    if opts.get('profit_destination') == "Partners Capital":
        profit_face = ("Owner's Capital Account" if entity_type == "Proprietor"
                       else "Partners Capital Account")
    else:
        profit_face = PROFIT_FACE

    def _bf(rep):
        d = dict(rep['by_face'])
        d[profit_face] = d.get(profit_face, 0.0) + rep.get('profit_to_add', 0.0)
        return d

    inv_cy = fe.load_inventory(company, cy_label)
    inv_py_file = fe.load_inventory(company, py_label) if py_label else fe.inventory_default()
    # PY balance: use the PY year's own inventory file if maintained, else the
    # comparative (PY) columns typed in the current-year disclosure.
    if inv_py_file.get('disclose'):
        inv_py, inv_py_side = inv_py_file, 'cy'
    elif inv_cy.get('disclose'):
        inv_py, inv_py_side = inv_cy, 'py'
    else:
        inv_py, inv_py_side = None, 'cy'

    fa_cy = fe.load_fixed_assets(company, cy_label)
    fa_py_file = fe.load_fixed_assets(company, py_label) if py_label else fe.fixed_assets_default()
    if any(fa_py_file.get(k, {}).get('disclose') for k in ('cwip', 'intan_dev')):
        fa_py, fa_py_side = fa_py_file, 'cy'
    elif any(fa_cy.get(k, {}).get('disclose') for k in ('cwip', 'intan_dev')):
        fa_py, fa_py_side = fa_cy, 'py'
    else:
        fa_py, fa_py_side = None, 'cy'

    work_cy = (work_override if work_override is not None
               else fe.build_working_mapping(company, entity_type))
    rep_cy = compute(work_cy, fe.load_aux(company, cy_label), entity_type,
                     inv=inv_cy, inv_side='cy', fa=fa_cy, fa_side='cy')
    work_py = fe.build_py_working_mapping(company, entity_type)
    rep_py = (compute(work_py, fe.load_aux(company, py_label), entity_type,
                      inv=inv_py, inv_side=inv_py_side, fa=fa_py, fa_side=fa_py_side)
              if work_py else None)

    cy_bf = _bf(rep_cy)
    py_bf = _bf(rep_py) if rep_py else {}

    def _scale(x):
        return None if x is None else x / divisor

    def cy(face):
        return _scale(_present(face, cy_bf.get(face, 0.0)))

    def py(face):
        return _scale(_present(face, py_bf.get(face, 0.0))) if rep_py else None

    # Notes registry (numbered in order of first appearance)
    notes, note_index = [], {}

    def collect_note_labels(face):
        labels = []
        for rep in (rep_cy, rep_py):
            if not rep:
                continue
            for (f, nl) in rep['by_face_note']:
                if f == face and nl not in labels:
                    labels.append(nl)
        return labels

    def note_val(rep, face, nl):
        if not rep:
            return None
        return _scale(_present(face, rep['by_face_note'].get((face, nl), 0.0)))

    def ensure_note(face):
        if face in note_index:
            return note_index[face]
        num = len(notes) + notes_start
        note_index[face] = num
        face_cy, face_py = cy(face), py(face)
        if face == profit_face:
            # Movement schedule: opening + current-year profit = closing (=BS line).
            # Works whether or not the surplus ledger already held the profit.
            prof_cy = _scale(rep_cy['profit'])
            prof_py = _scale(rep_py['profit']) if rep_py else None
            open_cy = (face_cy - prof_cy) if face_cy is not None else None
            open_py = (face_py - prof_py) if (face_py is not None and prof_py is not None) else None
            lines = [
                {'label': "Balance brought forward", 'cy': open_cy, 'py': open_py},
                {'label': PROFIT_NOTE_LABEL, 'cy': prof_cy, 'py': prof_py},
            ]
        else:
            lines = []
            for nl in collect_note_labels(face):
                lines.append({'label': nl if nl else "Others",
                              'cy': note_val(rep_cy, face, nl),
                              'py': note_val(rep_py, face, nl)})
        notes.append({'num': num, 'title': face, 'lines': lines,
                      'cy': face_cy, 'py': face_py})
        return num

    # ---- Balance Sheet ----
    # CWIP / Intangible-under-development always form part of the PPE note (Note 7)
    # — never a separate note number. Their net value shows as a single (ii)/(iii)
    # line; the Opening/Addition/Capitalised/Closing detail appears only when the
    # Fixed Assets disclosure is filled.
    _fa_fold = {CWIP_FACE, INTAN_DEV_FACE}
    _ppe_present = _nzf(cy("Property Plant and Equipment"), py("Property Plant and Equipment"))
    roman_of_face = {}      # face -> roman label as shown on the BS (for Note 7)
    fa_face_val = {}        # face -> (cy, py) scaled BS value (for the Note 7 net rows)
    bs_rows = []
    bs_totals = {}
    for group_label, subs in fg.BS_LAYOUT:
        bs_rows.append({'label': group_label, 'note': '', 'cy': None, 'py': None,
                        'level': 0, 'bold': True})
        g_cy = g_py = 0.0
        for sub_label, lettered, subsubs in subs:
            sub_out = []
            s_cy = s_py = 0.0
            li = 0
            for subsub_label, roman_flag, faces in subsubs:
                visible = []
                for face in faces:
                    c, p = cy(face), py(face)
                    if hide_zero and not _nzf(c, p):
                        continue
                    visible.append((face, c, p))
                if not visible:
                    continue
                if subsub_label is not None:
                    hdr = ((fg.LETTER_SEQ[li] + ' ' if lettered and li < len(fg.LETTER_SEQ)
                            else '') + subsub_label)
                    li += 1
                    sub_out.append({'label': hdr, 'face': '', 'note': '', 'cy': None,
                                    'py': None, 'level': 2, 'bold': True})
                    ri = 0
                    for face, c, p in visible:
                        rom = (fg.ROMAN_SEQ[ri] if roman_flag and ri < len(fg.ROMAN_SEQ) else '')
                        ri += 1
                        roman_of_face[face] = rom
                        if face in _fa_fold and _ppe_present:
                            num = ''          # schedule shown inside the PPE note
                            fa_face_val[face] = (c, p)
                        else:
                            num = ensure_note(face)
                        lbl = (rom + ' ' if rom else '') + face
                        sub_out.append({'label': lbl, 'face': face, 'note': num,
                                        'cy': c, 'py': p, 'level': 3, 'is_face': True})
                        s_cy += c or 0.0
                        s_py += p or 0.0
                else:
                    for face, c, p in visible:
                        num = ensure_note(face)
                        pre = (fg.LETTER_SEQ[li] + ' ' if lettered and li < len(fg.LETTER_SEQ)
                               else '')
                        if lettered:
                            li += 1
                        sub_out.append({'label': pre + face, 'face': face, 'note': num,
                                        'cy': c, 'py': p, 'level': 2, 'is_face': True})
                        s_cy += c or 0.0
                        s_py += p or 0.0
            if sub_out:
                bs_rows.append({'label': sub_label, 'note': '', 'cy': None, 'py': None,
                                'level': 1, 'bold': True})
                bs_rows.extend(sub_out)
                g_cy += s_cy
                g_py += s_py
        bs_rows.append({'label': f"Total — {group_label.title()}", 'note': '',
                        'cy': g_cy, 'py': (g_py if rep_py else None),
                        'level': 0, 'bold': True, 'rule': True})
        bs_totals[group_label] = (g_cy, g_py if rep_py else None)

    # ── Round-off tie (presentation only) ─────────────────────────────────────
    # Each BS line is rounded independently at display, so the rounded line items
    # need not re-add to the rounded total and Assets vs Equity+Liabilities can
    # part by a unit. Absorb that residue SILENTLY into the largest line of each
    # side so the printed statement ties exactly. Imported figures are untouched
    # (this only rewrites the display-scaled values on bs_rows); guarded so it
    # only soaks up rounding-scale noise (≤ ~1 display unit), never a real gap.
    _ndp = 2 if bool(pres.get('two_decimals', False)) else 0
    _q = 10 ** (-_ndp)

    def _rnd(x):
        return None if x is None else round(float(x), _ndp)

    # Segment bs_rows into top-level groups: header (cy None) / face rows / total.
    _groups, _cur = [], None
    for _row in bs_rows:
        _lbl = str(_row.get('label') or '')
        if _row.get('level') == 0 and _row.get('cy') is None and not _lbl.startswith('Total —'):
            _cur = {'faces': [], 'total': None}
            _groups.append(_cur)
        elif _row.get('level') == 0 and _lbl.startswith('Total —'):
            if _cur is not None:
                _cur['total'] = _row
        elif _row.get('is_face') and _cur is not None:
            _cur['faces'].append(_row)

    def _tie_side(faces, total_row, col, target):
        """Force Σ round(face[col]) == target by nudging the largest line; pin the
        total row to target. No-op when target is None or the side has no lines."""
        if target is None or not faces:
            return
        vals = [(_rnd(f.get(col)) or 0.0) for f in faces]
        for f, v in zip(faces, vals):
            f[col] = v
        residue = round(target - sum(vals), _ndp)
        if abs(residue) >= _q / 2:
            _i = max(range(len(faces)), key=lambda i: abs(vals[i]))
            faces[_i][col] = round(vals[_i] + residue, _ndp)
        if total_row is not None:
            total_row[col] = target

    for _col in ('cy', 'py'):
        _tgts = [(_rnd(g['total'].get(_col)) if g['total'] is not None else None)
                 for g in _groups]
        # Cross-side: when the two sides differ only by rounding noise, snap both
        # to the larger rounded total so the smaller side's largest line takes the
        # residue and Assets == Equity+Liabilities exactly.
        if (len(_groups) == 2 and None not in _tgts
                and abs(_tgts[0] - _tgts[1]) <= 1.5 * _q):
            _common = max(_tgts[0], _tgts[1])
            _tgts = [_common, _common]
        for _g, _t in zip(_groups, _tgts):
            _tie_side(_g['faces'], _g['total'], _col, _t)

    # ---- Statement of P&L ----
    pl_rows = []

    def pl_section(faces):
        rows, t_cy, t_py = [], 0.0, 0.0
        for face in faces:
            c, p = cy(face), py(face)
            if hide_zero and not _nzf(c, p):
                continue
            num = ensure_note(face)
            rows.append({'label': face, 'note': num, 'cy': c, 'py': p, 'level': 2})
            t_cy += c or 0.0
            t_py += p or 0.0
        return rows, t_cy, (t_py if rep_py else None)

    inc_rows, inc_cy, inc_py = pl_section(fg.PL_INCOME)
    exp_rows, exp_cy, exp_py = pl_section(fg.PL_EXPENSES)
    exc_rows, exc_cy, exc_py = pl_section(fg.PL_EXCEPTIONAL)
    tax_rows, tax_cy, tax_py = pl_section(fg.PL_TAX)

    def _sub(a, b):
        if a is None or b is None:
            return None
        return a - b

    pl_rows.append({'label': "Revenue", 'note': '', 'cy': None, 'py': None, 'level': 0, 'bold': True})
    pl_rows.extend(inc_rows)
    pl_rows.append({'label': "Total Revenue", 'note': '', 'cy': inc_cy, 'py': inc_py,
                    'level': 0, 'bold': True, 'rule': True})
    pl_rows.append({'label': "Expenses", 'note': '', 'cy': None, 'py': None, 'level': 0, 'bold': True})
    pl_rows.extend(exp_rows)
    pl_rows.append({'label': "Total Expenses", 'note': '', 'cy': exp_cy, 'py': exp_py,
                    'level': 0, 'bold': True, 'rule': True})
    pbe_cy, pbe_py = inc_cy - exp_cy, _sub(inc_py, exp_py)
    pl_rows.append({'label': "Profit before exceptional items & tax", 'note': '',
                    'cy': pbe_cy, 'py': pbe_py, 'level': 0, 'bold': True})
    if exc_rows:
        pl_rows.extend(exc_rows)
    pbt_cy, pbt_py = pbe_cy - exc_cy, _sub(pbe_py, exc_py)
    pl_rows.append({'label': "Profit before tax", 'note': '', 'cy': pbt_cy, 'py': pbt_py,
                    'level': 0, 'bold': True})
    if tax_rows:
        pl_rows.extend(tax_rows)
    pat_cy, pat_py = pbt_cy - tax_cy, _sub(pbt_py, tax_py)
    pl_rows.append({'label': "Profit / (Loss) for the year", 'note': '', 'cy': pat_cy, 'py': pat_py,
                    'level': 0, 'bold': True, 'rule': True})

    # Attach ledger-level detail to each note (annexure within notes)
    py_by_name = {r['ledger']: r['closing'] for r in (rep_py['rows'] if rep_py else [])}
    by_face_rows = {}
    for r in rep_cy['rows']:
        by_face_rows.setdefault(r['face'], []).append(r)
    for n in notes:
        face = n['title']
        leds = []
        for r in by_face_rows.get(face, []):
            leds.append({
                'name': r['ledger'], 'note': r['note'], 'subnote': r['subnote'],
                'cy': _scale(_present(face, r['closing'])),
                'py': (_scale(_present(face, py_by_name[r['ledger']]))
                       if r['ledger'] in py_by_name else None),
            })
        leds.sort(key=lambda x: (str(x['note'] or ''), str(x['name'] or '')))
        n['ledgers'] = leds
        # ---- Sub-note (level-4) third presentation level ----
        # For each note-line, if AT LEAST ONE ledger carries a sub-note, break the
        # line down by sub-note (blank sub-notes collapse into "Others"). If none
        # carry a sub-note, the line stays flat (no `subs`).
        if face != profit_face:
            for ln in n['lines']:
                nl_key = ln['label'] if ln['label'] != 'Others' else ''
                matched = [lg for lg in leds if (lg.get('note') or '') == nl_key]
                if not any((lg.get('subnote') or '').strip() for lg in matched):
                    continue
                agg = {}
                for lg in matched:
                    key = (lg.get('subnote') or '').strip() or 'Others'
                    cyv, pyv = agg.get(key, (None, None))
                    if lg.get('cy') is not None:
                        cyv = (cyv or 0.0) + lg['cy']
                    if lg.get('py') is not None:
                        pyv = (pyv or 0.0) + lg['py']
                    agg[key] = (cyv, pyv)
                subs = [{'label': k, 'cy': v[0], 'py': v[1]}
                        for k, v in agg.items() if k != 'Others']
                if 'Others' in agg:
                    v = agg['Others']
                    subs.append({'label': 'Others', 'cy': v[0], 'py': v[1]})
                ln['subs'] = subs

    # ---- FAR wide-table (Note 7 / Intangibles) when IT-dep register is in use ----
    # Presentation-only this phase: renders the block-wise Gross/Dep/Net schedule;
    # the BS face value still comes from the ledgers (reconcile in the FAR tab).
    if opts.get('depreciation') == 'FAR IT':
        far_rows = fe.load_far(company, cy_label)
        if far_rows:
            far = compute_far(far_rows)
            _KEYS = ('g_open', 'g_add', 'g_ded', 'g_close', 'd_open', 'd_year',
                     'd_ded', 'd_close', 'n_open', 'n_close')
            for n in notes:
                fa = far['faces'].get(n['title'])
                if not fa:
                    continue
                rows_out = [dict({'name': b['block']},
                                 **{k: _scale(b[k]) for k in _KEYS})
                            for b in fa['blocks']]
                total = {k: _scale(fa[k]) for k in _KEYS}
                section = ("(i) Property, Plant and Equipment"
                           if n['title'] == "Property Plant and Equipment"
                           else n['title'])
                n['far'] = {'section': section, 'rows': rows_out, 'total': total}

    # ---- Fixed Assets: CWIP + Intangible-under-development fold into PPE note ----
    # Always show the net (ii)/(iii) line from the TB face value; show the
    # Opening/Addition/Capitalised/Closing detail only when the disclosure is filled.
    def _fa_block_pay(key, face):
        blk = fa_cy.get(key, {})
        ncy, npy = fa_face_val.get(face, (None, None))
        return {
            'present': face in fa_face_val,
            'roman': roman_of_face.get(face, ''),
            'net_cy': ncy, 'net_py': npy,
            'disclose': fe.fa_block_discloses(blk),
            'opening_cy': _scale(_f(blk.get('opening_cy'))),
            'addition_cy': _scale(_f(blk.get('addition_cy'))),
            'capitalised_cy': _scale(_f(blk.get('capitalised_cy'))),
            'closing_cy': _scale(fe.fa_closing(blk, 'cy')),
            'opening_py': _scale(_f(blk.get('opening_py'))),
            'addition_py': _scale(_f(blk.get('addition_py'))),
            'capitalised_py': _scale(_f(blk.get('capitalised_py'))),
            'closing_py': _scale(fe.fa_closing(blk, 'py')),
        }
    _cwip_pay = _fa_block_pay('cwip', CWIP_FACE)
    _intan_pay = _fa_block_pay('intan_dev', INTAN_DEV_FACE)
    if (_cwip_pay['present'] or _intan_pay['present']
            or _cwip_pay['disclose'] or _intan_pay['disclose']):
        payload_fa = {
            'cwip': dict(_cwip_pay, label="Capital Work-in-progress"),
            'intan': dict(_intan_pay, label="Intangible assets under development"),
            'footnotes': fa_cy.get('footnotes', []),
        }
        for n in notes:
            if n['title'] == "Property Plant and Equipment":
                n['fixed_assets'] = payload_fa
                break

    # ---- Partners' capital schedules (Partnership): replace the capital note ----
    if entity_type == "Partnership":
        pdata = fe.load_partners(company, cy_label)
        if pdata.get('rows'):
            def _prow(r, fixed):
                out = {k: _scale(fe._pnum(r.get(k))) for k in
                       ('opening', 'addition', 'withdrawal', 'others_add', 'others_less',
                        'interest', 'remuneration', 'profit')}
                out['name'] = str(r.get('name') or '')
                out['share'] = fe._pnum(r.get('share'))
                out['closing'] = _scale(fe.partners_closing(r, fixed))
                return out

            def _ptot(rows, fixed):
                t = {k: sum(r[k] or 0 for r in rows) for k in
                     ('opening', 'addition', 'withdrawal', 'others_add', 'others_less',
                      'interest', 'remuneration', 'profit', 'closing')}
                t['share'] = sum(r['share'] or 0 for r in rows)
                return t

            def _ppy(d, fixed):
                """Manual PY totals if typed; else auto-fetched from the previous
                FY's saved partners file."""
                d = {k: v for k, v in (d or {}).items() if v not in (None, '', 0, 0.0)}
                if not d:
                    d = fe.partners_py_totals(company, py_label, fixed)
                return {k: (_scale(fe._pnum(v)) if v not in (None, '') else None)
                        for k, v in d.items()}

            cur_rows = [_prow(r, False) for r in pdata['rows']]
            fx_rows = ([_prow(r, True) for r in pdata['fixed_rows']]
                       if pdata.get('fixed_schedule') else [])
            payload = {
                'format': pdata.get('format', 'Vertical'),
                'current': {'rows': cur_rows, 'total': _ptot(cur_rows, False),
                            'py': _ppy(pdata['py'].get('current'), False)},
                'fixed': ({'rows': fx_rows, 'total': _ptot(fx_rows, True),
                           'py': _ppy(pdata['py'].get('fixed'), True)} if fx_rows else None),
            }
            for n in notes:
                if n['title'] == "Partners Capital Account":
                    n['partners'] = payload
                    break

    # ── Trade Receivables ageing schedule (attached to the receivables note) ──
    # Blank rows are suppressed here (built once) so every renderer just iterates.
    # "As per Trial Balance" / "Difference" are NOT in the note — they live in the
    # Disclosures entry screen as a reconciliation check only.
    age = fe.load_tr_ageing(company, cy_label)
    if age.get('disclose'):
        g = age['grid']
        _CATS = (('secured', 'Secured Considered good'),
                 ('unsecured', 'Unsecured Considered good'),
                 ('doubtful', 'Doubtful'),
                 ('provision', 'Less: Provision for doubtful receivables'))

        def _nz(*vals):
            return any(v not in (None, 0) and abs(v) > 0.005 for v in vals)

        sections, total_cy, total_py = [], 0.0, 0.0
        for bucket, title in (('lt6', "Outstanding for a period less than 6 months "
                                       "from the date they are due for receipt"),
                              ('gt6', "Outstanding for a period exceeding 6 months "
                                      "from the date they are due for receipt")):
            srows, sub_cy, sub_py = [], 0.0, 0.0
            for k, lbl in _CATS:
                cy, py = g[k][f'{bucket}_cy'], g[k][f'{bucket}_py']
                sign = -1 if k == 'provision' else 1
                sub_cy += sign * cy
                sub_py += sign * py
                if _nz(cy, py):
                    srows.append({'label': lbl, 'cy': _scale(cy), 'py': _scale(py)})
            if srows:
                sections.append({'title': title, 'rows': srows,
                                 'sub_cy': _scale(sub_cy), 'sub_py': _scale(sub_py)})
            total_cy += sub_cy
            total_py += sub_py

        extras = []
        for key, lbl in (('unbilled', 'Unbilled receivables'), ('undue', 'Undue')):
            cy, py = age[key]['cy'], age[key]['py']
            total_cy += cy
            total_py += py
            if _nz(cy, py):
                extras.append({'label': lbl, 'cy': _scale(cy), 'py': _scale(py)})

        payload_age = {'sections': sections, 'extras': extras,
                       'total_cy': _scale(total_cy), 'total_py': _scale(total_py),
                       'footnotes': age.get('footnotes', [])}
        for n in notes:
            if n['title'] == 'Trade receivables':
                n['ageing'] = payload_age
                break

    # ── Owner's Capital Account schedule (Proprietor/Individual) ─────────────
    # User-entered credit/debit lines + auto Profit/Loss for the period from P&L.
    # Blank rows suppressed; "As per TB"/Difference live only on the entry screen.
    if entity_type == "Proprietor":
        oc = fe.load_owners_capital(company, cy_label)
        if oc.get('disclose'):
            profit_cy = rep_cy['profit']
            profit_py = rep_py['profit'] if rep_py else 0.0

            def _nzoc(*v):
                return any(x not in (None, 0) and abs(x) > 0.005 for x in v)

            cred = list(oc.get('credit', [])) + [
                {'label': 'Profit for the period',
                 'cy': max(profit_cy, 0.0), 'py': max(profit_py, 0.0)}]
            deb = [{'label': 'Loss for the period',
                    'cy': max(-profit_cy, 0.0), 'py': max(-profit_py, 0.0)}] + list(oc.get('debit', []))
            credit_rows = [{'label': r['label'], 'cy': _scale(r['cy']), 'py': _scale(r['py'])}
                           for r in cred if _nzoc(r.get('cy'), r.get('py'))]
            debit_rows = [{'label': r['label'], 'cy': _scale(r['cy']), 'py': _scale(r['py'])}
                          for r in deb if _nzoc(r.get('cy'), r.get('py'))]
            ct_cy = sum(r.get('cy') or 0 for r in cred)
            ct_py = sum(r.get('py') or 0 for r in cred)
            dt_cy = sum(r.get('cy') or 0 for r in deb)
            dt_py = sum(r.get('py') or 0 for r in deb)
            payload_oc = {
                'credit_rows': credit_rows,
                'credit_total_cy': _scale(ct_cy), 'credit_total_py': _scale(ct_py),
                'debit_rows': debit_rows,
                'debit_total_cy': _scale(dt_cy), 'debit_total_py': _scale(dt_py),
                'total_cy': _scale(ct_cy - dt_cy), 'total_py': _scale(ct_py - dt_py),
                'footnotes': oc.get('footnotes', []),
            }
            for n in notes:
                if n['title'] == "Owner's Capital Account":
                    n['owners_capital'] = payload_oc
                    break

    # ── Inventories disclosure (Cost of material consumed + Change in inv.) ────
    # Replaces the auto note bodies for the three inventory faces with the user's
    # detailed schedule. Figures are CY = current-year inputs, PY = the comparative
    # columns typed in the current-year form. Blank rows suppressed.
    if inv_cy.get('disclose'):
        def _nzi(*v):
            return any(x not in (None, 0) and abs(x) > 0.005 for x in v)

        # Note 9 — Inventories (Balance Sheet): closing stock of every category.
        inv_rows = []
        itot_cy = itot_py = 0.0
        for r in inv_cy.get('materials', []):
            ccy, cpy = _f(r.get('closing_cy')), _f(r.get('closing_py'))
            itot_cy += ccy
            itot_py += cpy
            if _nzi(ccy, cpy):
                inv_rows.append({'label': r.get('label') or 'Material',
                                 'cy': _scale(ccy), 'py': _scale(cpy)})
        for r in inv_cy.get('change', []):
            ccy, cpy = _f(r.get('close_cy')), _f(r.get('close_py'))
            itot_cy += ccy
            itot_py += cpy
            if _nzi(ccy, cpy):
                inv_rows.append({'label': r.get('label') or 'Stock',
                                 'cy': _scale(ccy), 'py': _scale(cpy)})
        payload_inv = {'rows': inv_rows,
                       'total_cy': _scale(itot_cy), 'total_py': _scale(itot_py)}

        # Note 16 — Cost of material consumed: per category O + P − C, + Other Mfg.
        mat_rows = []
        grand_cy = grand_py = 0.0
        for r in inv_cy.get('materials', []):
            ocy, pcy, ccy = _f(r.get('opening_cy')), _f(r.get('purchases_cy')), _f(r.get('closing_cy'))
            opy, ppy, cpy = _f(r.get('opening_py')), _f(r.get('purchases_py')), _f(r.get('closing_py'))
            tcy, tpy = ocy + pcy - ccy, opy + ppy - cpy
            grand_cy += tcy
            grand_py += tpy
            if _nzi(ocy, pcy, ccy, opy, ppy, cpy):
                mat_rows.append({'label': r.get('label') or 'Material',
                                 'opening_cy': _scale(ocy), 'purchases_cy': _scale(pcy),
                                 'closing_cy': _scale(ccy), 'total_cy': _scale(tcy),
                                 'opening_py': _scale(opy), 'purchases_py': _scale(ppy),
                                 'closing_py': _scale(cpy), 'total_py': _scale(tpy)})
        mfg_rows, mfg_cy, mfg_py = [], 0.0, 0.0
        for r in inv_cy.get('mfg_expenses', []):
            mcy, mpy = _f(r.get('cy')), _f(r.get('py'))
            mfg_cy += mcy
            mfg_py += mpy
            if _nzi(mcy, mpy):
                mfg_rows.append({'label': r.get('label') or 'Expense',
                                 'group': r.get('group') or '',
                                 'cy': _scale(mcy), 'py': _scale(mpy)})
        grand_cy += mfg_cy
        grand_py += mfg_py
        payload_cost = {'materials': mat_rows, 'mfg': mfg_rows,
                        'mfg_total_cy': _scale(mfg_cy), 'mfg_total_py': _scale(mfg_py),
                        'grand_cy': _scale(grand_cy), 'grand_py': _scale(grand_py),
                        'footnotes': inv_cy.get('mfg_footnotes', [])}

        # Note 18 — Change in inventories of FG / WIP / stock-in-trade.
        open_rows, close_rows = [], []
        ot_cy = ot_py = ct_cy = ct_py = 0.0
        for r in inv_cy.get('change', []):
            ocy, opy = _f(r.get('open_cy')), _f(r.get('open_py'))
            ccy, cpy = _f(r.get('close_cy')), _f(r.get('close_py'))
            ot_cy += ocy
            ot_py += opy
            ct_cy += ccy
            ct_py += cpy
            if _nzi(ocy, opy):
                open_rows.append({'label': r.get('label') or 'Stock',
                                  'cy': _scale(ocy), 'py': _scale(opy)})
            if _nzi(ccy, cpy):
                close_rows.append({'label': r.get('label') or 'Stock',
                                   'cy': _scale(ccy), 'py': _scale(cpy)})
        payload_change = {'opening': open_rows, 'closing': close_rows,
                          'open_total_cy': _scale(ot_cy), 'open_total_py': _scale(ot_py),
                          'close_total_cy': _scale(ct_cy), 'close_total_py': _scale(ct_py),
                          'total_cy': _scale(ot_cy - ct_cy), 'total_py': _scale(ot_py - ct_py),
                          'footnotes': inv_cy.get('change_footnotes', [])}

        # The faces are non-zero whenever data is entered, so their notes already
        # exist from the BS / P&L assembly above — just attach the schedules.
        for n in notes:
            if n['title'] == CLOSING_STOCK_FACE:
                n['inventory'] = payload_inv
            elif n['title'] == COST_FACE:
                n['cost_material'] = payload_cost
            elif n['title'] == CHANGES_FACE:
                n['change_inv'] = payload_change

    e = ent.get('entity', {})
    period = ent.get('period', {})
    cy_header = fe.period_header(period.get('cy')) or (cy_label or "Current year")
    py_header = fe.period_header(period.get('py')) or (py_label or "Previous year")
    address = e.get('address', '') if prnt.get('print_address', 'Address') == 'Address' else \
        (e.get('llpin', '') if prnt.get('print_address') == 'LLPIN' else '')

    return {
        'meta': {
            'company': company,
            'entity_name': e.get('name') or company,
            'entity_type': entity_type,
            'entity_type_label': e.get('type', ''),
            'address': address,
            'pan': e.get('pan', ''),
            'cy_label': cy_label,
            'py_label': py_label,
            'cy_header': cy_header,
            'py_header': py_header,
            'units_label': units_label,
            'two_decimals': bool(pres.get('two_decimals', False)),
            'theme': fg.theme(pres.get('theme', 'Theme 1')),
            'border': fg.border(pres.get('border', 'Layout 1')),
            'theme_name': pres.get('theme', 'Theme 1'),
            'border_name': pres.get('border', 'Layout 1'),
            'round_off': pres.get('round_off', 'In Rs'),
            'font': pres.get('font', 'Calibri'),
            'header_align': (prnt.get('header_align', 'Left') or 'Left').lower(),
            'show_notes_col': bool(prnt.get('show_notes_col', True)),
            'has_py': bool(rep_py),
            'balanced': rep_cy['balanced'],
            'difference': rep_cy['difference'],
            'has_unmapped': rep_cy['has_unmapped'],
            'unmapped_total': rep_cy['unmapped_total'],
            'profit_cy': rep_cy['profit'],
            'profit_py': (rep_py['profit'] if rep_py else None),
            'profit_in_surplus': not rep_cy['add_profit'],
            'profit_face': profit_face,
            'signatories': ent.get('signatories', []),
            'sign': ent.get('sign', {}),
            'auditor': ent.get('auditor', {}),
            'print_ca_details': bool(ent.get('auditor', {}).get('print_ca_details', True)),
        },
        'bs': bs_rows,
        'pl': pl_rows,
        'notes': notes,
        'policies': resolve_policy_notes(company),
    }


# ── Exporters / renderers (theme-aware) ───────────────────────────────────────
def _money(x, meta):
    return fmt_amt(x, decimals=2 if meta.get('two_decimals') else 0)


def _dmy(d):
    """{'date':1,'month':'July','year':2026} -> '1 July 2026'."""
    if not isinstance(d, dict):
        return ""
    parts = [str(d.get('date', '')).strip(), str(d.get('month', '')).strip(),
             str(d.get('year', '')).strip()]
    return " ".join(p for p in parts if p)


def themed_css(meta):
    t = meta['theme']
    bcss = meta['border']['css']
    font = meta['font']
    return f"""<style>
    .fswrap{{font-family:{font},Arial,sans-serif;color:#1a1a1a;}}
    .fswrap h2.ent{{margin:0;color:{t['heading']};font-size:18px;}}
    .fswrap .sub{{color:#444;margin:1px 0;font-size:12px;}}
    .fswrap h3.fst{{margin:6px 0 4px;color:{t['heading']};font-size:15px;}}
    .fswrap .units{{text-align:right;font-size:11px;color:#555;margin:0 0 2px;}}
    table.fs{{border-collapse:collapse;width:100%;margin-bottom:8px;font-size:13px;
             font-family:{font},Arial,sans-serif;}}
    table.fs th,table.fs td{{padding:3px 8px;border:{bcss};}}
    table.fs thead th{{text-align:left;font-weight:700;background:{t['cy_shade']};}}
    table.fs td.amt,table.fs th.amt{{text-align:right;width:130px;}}
    table.fs td.cyamt,table.fs th.cyamt{{text-align:right;width:130px;background:{t['cy_shade']};}}
    table.fs td.note,table.fs th.note{{text-align:center;width:46px;}}
    table.fs tr.b td{{font-weight:700;}}
    table.fs tr.rule td{{border-top:1px solid #333;}}
    .fswrap .sigblk{{margin-top:22px;font-size:12px;width:100%;}}
    .fswrap .sigblk td{{vertical-align:top;padding-right:18px;}}
    </style>"""


def _entity_header_html(meta, title):
    align = meta.get('header_align', 'left')
    addr = f"<div class='sub'>({meta['address']})</div>" if meta.get('address') else ""
    warn = ""
    if not meta['balanced']:
        warn = (f"<div style='background:#fdecea;color:#b3261e;padding:4px 8px;border-radius:4px;"
                f"font-size:12px;margin:4px 0;'>⚠️ Out of balance by "
                f"{_money(meta['difference'], meta)} — review stock / adjustments.</div>")
    return (f"<div class='fswrap' style='text-align:{align};'>"
            f"<h2 class='ent'>{meta['entity_name']}</h2>{addr}"
            f"<h3 class='fst'>{title}</h3></div>"
            f"<div class='units'>({meta['units_label']})</div>{warn}")


def _table_html(rows, meta):
    show_note = meta['show_notes_col']
    note_h = "<th class='note'>Note</th>" if show_note else ""
    py_h = f"<th class='amt'>{meta['py_header']}</th>" if meta['has_py'] else ""
    out = ["<table class='fs'>",
           f"<thead><tr><th>Particulars</th>{note_h}"
           f"<th class='cyamt'>{meta['cy_header']}</th>{py_h}</tr></thead><tbody>"]
    for r in rows:
        cls = []
        if r.get('bold'):
            cls.append('b')
        if r.get('rule'):
            cls.append('rule')
        pad = 8 + int(r.get('level', 0)) * 20
        nv = r.get('note') or ''
        if show_note and nv and meta.get('link_xref'):
            nv = f"<a href='#note-{nv}' style='text-decoration:none'>{nv}</a>"
        note_td = f"<td class='note'>{nv}</td>" if show_note else ""
        cyv = _money(r.get('cy'), meta) if r.get('cy') is not None else ''
        pyv = _money(r.get('py'), meta) if r.get('py') is not None else ''
        py_td = f"<td class='amt'>{pyv}</td>" if meta['has_py'] else ""
        out.append(f"<tr class='{' '.join(cls)}'>"
                   f"<td style='padding-left:{pad}px'>{r['label']}</td>{note_td}"
                   f"<td class='cyamt'>{cyv}</td>{py_td}</tr>")
    out.append("</tbody></table>")
    return "\n".join(out)


def statement_html(title, rows, meta):
    """Entity header + one statement table (used by viewer and standalone HTML)."""
    return _entity_header_html(meta, title) + _table_html(rows, meta)


def notes_header_html(meta):
    """Entity header band for the notes page."""
    return _entity_header_html(meta, "Notes forming part of the Financial Statements")


def _note_title_html(n, meta):
    """Note heading with an `id` anchor; in export mode the title is a back-link to
    the Balance Sheet or P&L (cross-reference)."""
    label = f"{n['num']} {n['title']}"
    if meta.get('link_xref'):
        anchor = ('stmt-pl' if fg.face_section(n['title']) in ('income', 'expense')
                  else 'stmt-bs')
        label = (f"<a href='#{anchor}' style='text-decoration:none;color:inherit' "
                 f"title='Back to statement'>{label}</a>")
    return (f"<div class='fswrap'><h3 id='note-{n['num']}' class='fst' "
            f"style='font-size:13px;'>{label}</h3></div>")


def far_table_html(n, meta, with_title=True):
    """Wide Gross Block / Depreciation / Net Block schedule for a FAR-backed note."""
    far = n['far']
    cyh, pyh = meta['cy_header'], meta['py_header']

    def m(x):
        return _money(x, meta) if x is not None else ''

    out = []
    if with_title:
        out.append(_note_title_html(n, meta))
    out.append("<table class='fs' style='font-size:12px;'>")
    out.append(
        "<thead>"
        "<tr><th rowspan='2'>Name of Assets</th>"
        "<th colspan='4' style='text-align:center'>Gross Block</th>"
        "<th colspan='4' style='text-align:center'>Depreciation</th>"
        "<th colspan='2' style='text-align:center'>Net Block</th></tr>"
        f"<tr><th class='amt'>As on<br>{cyh}<br>(Opening)</th><th class='amt'>Addition</th>"
        "<th class='amt'>Deduction</th><th class='amt'>Closing</th>"
        "<th class='amt'>Opening</th><th class='amt'>For the year</th>"
        "<th class='amt'>Deduction</th><th class='amt'>Closing</th>"
        f"<th class='cyamt'>{cyh}</th><th class='amt'>{pyh}</th></tr>"
        "</thead><tbody>")
    cols = ['g_open', 'g_add', 'g_ded', 'g_close', 'd_open', 'd_year', 'd_ded', 'd_close']
    sec = far.get('section')
    if sec:
        out.append(f"<tr class='b'><td colspan='11'>{sec}</td></tr>")
    for b in far['rows']:
        tds = "".join(f"<td class='amt'>{m(b.get(c))}</td>" for c in cols)
        out.append(f"<tr><td style='padding-left:18px'>{b['name']}</td>{tds}"
                   f"<td class='cyamt'>{m(b.get('n_close'))}</td>"
                   f"<td class='amt'>{m(b.get('n_open'))}</td></tr>")
    t = far['total']
    tds = "".join(f"<td class='amt'>{m(t.get(c))}</td>" for c in cols)
    out.append(f"<tr class='b rule'><td>Total</td>{tds}"
               f"<td class='cyamt'>{m(t.get('n_close'))}</td>"
               f"<td class='amt'>{m(t.get('n_open'))}</td></tr>")
    out.append(f"<tr class='b'><td>Previous Year</td>"
               + "".join("<td class='amt'></td>" for _ in cols)
               + f"<td class='cyamt'>{m(t.get('n_open'))}</td><td class='amt'></td></tr>")
    out.append("</tbody></table>")
    return "\n".join(out)


# Partners' capital schedules — field rows in presentation order
_P_CUR_FIELDS = [("opening", "Opening Capital"), ("addition", "Addition"),
                 ("withdrawal", "Withdrawal"), ("interest", "Interest on Partners' Capital"),
                 ("remuneration", "Partners' Remuneration"),
                 ("profit", "Profit/(loss) during the year")]
_P_FIX_FIELDS = [("opening", "Opening Capital"), ("addition", "Addition"),
                 ("withdrawal", "Withdrawal"), ("others_add", "Others (Add)"),
                 ("others_less", "Others (Less)")]


def _partners_sched_html(title, sched, fields, meta, vertical):
    def m(x):
        return _money(x, meta) if x is not None else ''

    rows, tot, py = sched['rows'], sched['total'], sched.get('py') or {}
    out = [f"<div style='margin:6px 0 2px;font-weight:700;color:{meta['theme']['heading']};"
           f"font-size:12.5px'>{title} <span style='float:right;font-weight:400;"
           f"font-size:11px;color:#555'>({meta['units_label']})</span></div>"]
    if vertical:   # partners as columns
        heads = "".join(f"<th class='amt'>{r['name']}</th>" for r in rows)
        out.append(f"<table class='fs' style='font-size:12px'><thead><tr>"
                   f"<th>Particulars</th>{heads}<th class='cyamt'>Total</th>"
                   f"<th class='amt'>Previous Year</th></tr></thead><tbody>")
        shr = "".join(f"<td class='amt'>{r['share']:.2f}%</td>" for r in rows)
        out.append(f"<tr><td>Partners' Share</td>{shr}"
                   f"<td class='cyamt'>{tot['share']:.2f}%</td><td class='amt'></td></tr>")
        for k, lbl in fields:
            tds = "".join(f"<td class='amt'>{m(r[k])}</td>" for r in rows)
            out.append(f"<tr><td>{lbl}</td>{tds}<td class='cyamt'>{m(tot[k])}</td>"
                       f"<td class='amt'>{m(py.get(k))}</td></tr>")
        tds = "".join(f"<td class='amt'>{m(r['closing'])}</td>" for r in rows)
        out.append(f"<tr class='b rule'><td>Closing Balance</td>{tds}"
                   f"<td class='cyamt'>{m(tot['closing'])}</td>"
                   f"<td class='amt'>{m(py.get('closing'))}</td></tr>")
    else:          # horizontal: partners as rows
        heads = "".join(f"<th class='amt'>{lbl}</th>" for _, lbl in fields)
        out.append(f"<table class='fs' style='font-size:12px'><thead><tr>"
                   f"<th>Name of Partner</th><th class='amt'>Share</th>{heads}"
                   f"<th class='cyamt'>Closing Balance</th></tr></thead><tbody>")
        for r in rows:
            tds = "".join(f"<td class='amt'>{m(r[k])}</td>" for k, _ in fields)
            out.append(f"<tr><td>{r['name']}</td><td class='amt'>{r['share']:.2f}%</td>"
                       f"{tds}<td class='cyamt'>{m(r['closing'])}</td></tr>")
        tds = "".join(f"<td class='amt'>{m(tot[k])}</td>" for k, _ in fields)
        out.append(f"<tr class='b rule'><td>Total</td><td class='amt'>{tot['share']:.2f}%</td>"
                   f"{tds}<td class='cyamt'>{m(tot['closing'])}</td></tr>")
        tds = "".join(f"<td class='amt'>{m(py.get(k))}</td>" for k, _ in fields)
        out.append(f"<tr class='b'><td>Previous Year Total</td><td class='amt'></td>"
                   f"{tds}<td class='cyamt'>{m(py.get('closing'))}</td></tr>")
    out.append("</tbody></table>")
    return "\n".join(out)


def partners_table_html(n, meta, with_title=True):
    """Partners' Contribution (fixed, optional) + Partners' Current Account schedules."""
    p = n['partners']
    vertical = (p.get('format', 'Vertical') == 'Vertical')
    out = []
    if with_title:
        out.append(_note_title_html(n, meta))
    if p.get('fixed'):
        out.append(_partners_sched_html("Partners' Contribution Account", p['fixed'],
                                        _P_FIX_FIELDS, meta, vertical))
        out.append(_partners_sched_html("Partners' Current Account", p['current'],
                                        _P_CUR_FIELDS, meta, vertical))
    else:
        out.append(_partners_sched_html("Partners' Capital Account", p['current'],
                                        _P_CUR_FIELDS, meta, vertical))
    return "\n".join(out)


def one_note_html(n, meta, show_ledgers=False, with_title=True):
    """One note's table. `with_title=False` lets the caller (viewer) render the
    title itself (e.g. with an inline edit pencil)."""
    if n.get('far'):
        html = far_table_html(n, meta, with_title=with_title)
        if n.get('fixed_assets'):
            html += "\n" + fixed_assets_html(n, meta)
        return html
    if n.get('partners'):
        return partners_table_html(n, meta, with_title=with_title)
    if n.get('owners_capital'):
        return owners_capital_html(n, meta, with_title=with_title)
    if n.get('inventory'):
        return inventory_html(n, meta, with_title=with_title)
    if n.get('cost_material'):
        return cost_material_html(n, meta, with_title=with_title)
    if n.get('change_inv'):
        return change_inv_html(n, meta, with_title=with_title)
    py_h = f"<th class='amt'>{meta['py_header']}</th>" if meta['has_py'] else ""
    out = []
    if with_title:
        out.append(_note_title_html(n, meta))
    out.append(f"<table class='fs'><thead><tr><th>Particulars</th>"
               f"<th class='cyamt'>{meta['cy_header']}</th>{py_h}</tr></thead><tbody>")
    empty_py = "<td class='amt'></td>" if meta['has_py'] else ""

    def _led_rows(nl_label, sub_filter, indent):
        rows = []
        for lg in n.get('ledgers', []):
            if (lg.get('note') or '') != (nl_label if nl_label != 'Others' else ''):
                continue
            if sub_filter is not None and \
               (((lg.get('subnote') or '').strip() or 'Others') != sub_filter):
                continue
            lcy = _money(lg.get('cy'), meta) if lg.get('cy') is not None else ''
            lpy = _money(lg.get('py'), meta) if lg.get('py') is not None else ''
            lpy_td = f"<td class='amt' style='color:#666'>{lpy}</td>" if meta['has_py'] else ""
            rows.append(f"<tr style='color:#666;font-size:12px;'>"
                        f"<td style='padding-left:{indent}px'>{lg['name']}</td>"
                        f"<td class='cyamt' style='color:#666'>{lcy}</td>{lpy_td}</tr>")
        return rows

    for ln in n['lines']:
        subs = ln.get('subs')
        if subs:
            # Note-line is a sub-heading; values are carried on the sub-notes below.
            out.append(f"<tr><td style='padding-left:18px'>{ln['label']}</td>"
                       f"<td class='cyamt'></td>{empty_py}</tr>")
            for sb in subs:
                scy = _money(sb.get('cy'), meta) if sb.get('cy') is not None else ''
                spy = _money(sb.get('py'), meta) if sb.get('py') is not None else ''
                spy_td = f"<td class='amt'>{spy}</td>" if meta['has_py'] else ""
                out.append(f"<tr><td style='padding-left:36px'>&ndash;&nbsp;{sb['label']}</td>"
                           f"<td class='cyamt'>{scy}</td>{spy_td}</tr>")
                if show_ledgers:
                    out.extend(_led_rows(ln['label'], sb['label'], 54))
        else:
            cyv = _money(ln.get('cy'), meta) if ln.get('cy') is not None else ''
            pyv = _money(ln.get('py'), meta) if ln.get('py') is not None else ''
            py_td = f"<td class='amt'>{pyv}</td>" if meta['has_py'] else ""
            out.append(f"<tr><td style='padding-left:18px'>{ln['label']}</td>"
                       f"<td class='cyamt'>{cyv}</td>{py_td}</tr>")
            if show_ledgers:
                out.extend(_led_rows(ln['label'], None, 36))
    cyv = _money(n.get('cy'), meta)
    pyv = _money(n.get('py'), meta) if n.get('py') is not None else ''
    py_td = f"<td class='amt'>{pyv}</td>" if meta['has_py'] else ""
    out.append(f"<tr class='b rule'><td>Total</td><td class='cyamt'>{cyv}</td>{py_td}</tr>")
    out.append("</tbody></table>")
    if n.get('ageing'):
        out.append(ageing_html(n, meta))
    if n.get('fixed_assets'):
        out.append(fixed_assets_html(n, meta))
    return "\n".join(out)


def fixed_assets_html(n, meta):
    """Capital WIP + Intangible-under-development: net-block summary rows + the
    movement schedule(s). Folds into the PPE note (Note 7)."""
    a = n.get('fixed_assets')
    if not a:
        return ""
    has_py = meta['has_py']
    cyh, pyh = meta['cy_header'], meta['py_header']

    def m(x):
        return _money(x, meta) if x is not None else ''

    def amts(cy, py):
        s = f"<td class='cyamt'>{m(cy)}</td>"
        if has_py:
            s += f"<td class='amt'>{m(py)}</td>"
        return s

    py_h = f"<th class='amt'>{pyh}</th>" if has_py else ""
    blocks = [a['cwip'], a['intan']]
    out = []
    # Net-block summary rows (from the TB face value) — appear under the PPE total.
    present = [b for b in blocks if b.get('present')]
    if present:
        out.append("<table class='fs'><tbody>")
        for b in present:
            out.append(f"<tr class='b'><td>{b['roman']} {b['label']}</td>"
                       f"{amts(b['net_cy'], b['net_py'])}</tr>")
        out.append("</tbody></table>")
    # Movement schedule for each disclosed block only.
    for b in [b for b in blocks if b.get('disclose')]:
        out.append(f"<div class='fswrap'><h3 class='fst' style='font-size:13px;'>"
                   f"{b['roman']} {b['label']}</h3></div>")
        out.append(f"<table class='fs'><thead><tr><th>Particulars</th>"
                   f"<th class='cyamt'>{cyh}</th>{py_h}</tr></thead><tbody>")
        out.append(f"<tr><td style='padding-left:18px'>Opening Balance</td>"
                   f"{amts(b['opening_cy'], b['opening_py'])}</tr>")
        out.append(f"<tr><td style='padding-left:18px'>Add: Addition during the year</td>"
                   f"{amts(b['addition_cy'], b['addition_py'])}</tr>")
        out.append(f"<tr><td style='padding-left:18px'>Less: Capitalised during the year</td>"
                   f"{amts(b['capitalised_cy'], b['capitalised_py'])}</tr>")
        out.append(f"<tr class='b rule'><td>Closing Balance</td>"
                   f"{amts(b['closing_cy'], b['closing_py'])}</tr>")
        out.append("</tbody></table>")
    if a.get('footnotes'):
        out.append("<div class='fswrap' style='font-size:11px;color:#555;margin:2px 0 8px;'>"
                   "<b>Foot Notes for Tangible Assets &amp; CWIP</b>"
                   "<ol style='margin:2px 0 0 18px;padding:0;'>")
        for fn in a['footnotes']:
            out.append(f"<li>{_pol_escape(fn)}</li>")
        out.append("</ol></div>")
    return "\n".join(out)


def ageing_html(n, meta):
    """Trade Receivables Ageing Schedule (2-bucket) rendered as note X.1.
    Blank rows are already filtered out in `statements()`."""
    a = n.get('ageing')
    if not a:
        return ""
    has_py = meta['has_py']
    cyh, pyh = meta['cy_header'], meta['py_header']

    def m(x):
        return _money(x, meta) if x is not None else ''

    def amts(cy, py):
        s = f"<td class='cyamt'>{m(cy)}</td>"
        if has_py:
            s += f"<td class='amt'>{m(py)}</td>"
        return s

    py_h = f"<th class='amt'>{pyh}</th>" if has_py else ""
    out = [f"<div class='fswrap'><h3 class='fst' style='font-size:13px;'>"
           f"{n['num']}.1 Trade Receivables Ageing Schedule</h3></div>",
           f"<table class='fs'><thead><tr><th>Particulars</th>"
           f"<th class='cyamt'>{cyh}</th>{py_h}</tr></thead><tbody>"]
    for sec in a.get('sections', []):
        blank = "<td class='cyamt'></td>" + ("<td class='amt'></td>" if has_py else "")
        out.append(f"<tr class='b'><td>{sec['title']}</td>{blank}</tr>")
        for r in sec['rows']:
            out.append(f"<tr><td style='padding-left:18px'>{r['label']}</td>"
                       f"{amts(r['cy'], r['py'])}</tr>")
        out.append(f"<tr class='b'><td></td>{amts(sec['sub_cy'], sec['sub_py'])}</tr>")
    for r in a.get('extras', []):
        out.append(f"<tr><td style='padding-left:18px'>{r['label']}</td>"
                   f"{amts(r['cy'], r['py'])}</tr>")
    out.append(f"<tr class='b rule'><td>Total</td>{amts(a['total_cy'], a['total_py'])}</tr>")
    out.append("</tbody></table>")
    if a.get('footnotes'):
        out.append("<div class='fswrap' style='font-size:11px;color:#555;margin:2px 0 8px;'>"
                   "<b>Foot Notes for Trade Receivables</b>"
                   "<ol style='margin:2px 0 0 18px;padding:0;'>")
        for fn in a['footnotes']:
            out.append(f"<li>{_pol_escape(fn)}</li>")
        out.append("</ol></div>")
    return "\n".join(out)


def owners_capital_html(n, meta, with_title=True):
    """Owner's Capital Account schedule (credit/debit sides) — replaces the note."""
    a = n['owners_capital']
    has_py = meta['has_py']
    cyh, pyh = meta['cy_header'], meta['py_header']

    def m(x):
        return _money(x, meta) if x is not None else ''

    def amts(cy, py):
        s = f"<td class='cyamt'>{m(cy)}</td>"
        if has_py:
            s += f"<td class='amt'>{m(py)}</td>"
        return s

    blank = "<td class='cyamt'></td>" + ("<td class='amt'></td>" if has_py else "")
    py_h = f"<th class='amt'>{pyh}</th>" if has_py else ""
    out = []
    if with_title:
        out.append(_note_title_html(n, meta))
    out.append(f"<table class='fs'><thead><tr><th>Particulars</th>"
               f"<th class='cyamt'>{cyh}</th>{py_h}</tr></thead><tbody>")
    for r in a['credit_rows']:
        out.append(f"<tr><td style='padding-left:18px'>{r['label']}</td>{amts(r['cy'], r['py'])}</tr>")
    out.append(f"<tr class='b'><td>Total of Credit Side</td>"
               f"{amts(a['credit_total_cy'], a['credit_total_py'])}</tr>")
    out.append(f"<tr class='b'><td>Less:</td>{blank}</tr>")
    for r in a['debit_rows']:
        out.append(f"<tr><td style='padding-left:18px'>{r['label']}</td>{amts(r['cy'], r['py'])}</tr>")
    out.append(f"<tr class='b'><td>Total of Debit Side</td>"
               f"{amts(a['debit_total_cy'], a['debit_total_py'])}</tr>")
    out.append(f"<tr class='b rule'><td>Total</td>{amts(a['total_cy'], a['total_py'])}</tr>")
    out.append("</tbody></table>")
    if a.get('footnotes'):
        out.append("<div class='fswrap' style='font-size:11px;color:#555;margin:2px 0 8px;'>"
                   "<b>Footnote for Owners Capital</b>"
                   "<ol style='margin:2px 0 0 18px;padding:0;'>")
        for fn in a['footnotes']:
            out.append(f"<li>{_pol_escape(fn)}</li>")
        out.append("</ol></div>")
    return "\n".join(out)


def _inv_meta(meta):
    """Common header bits for the inventory note tables."""
    has_py = meta['has_py']
    py_h = f"<th class='amt'>{meta['py_header']}</th>" if has_py else ""
    blank = "<td class='cyamt'></td>" + ("<td class='amt'></td>" if has_py else "")
    return has_py, py_h, blank


def _inv_amts(cy, py, meta):
    s = f"<td class='cyamt'>{_money(cy, meta) if cy is not None else ''}</td>"
    if meta['has_py']:
        s += f"<td class='amt'>{_money(py, meta) if py is not None else ''}</td>"
    return s


def _inv_footnotes(footnotes, heading):
    if not footnotes:
        return ""
    out = ["<div class='fswrap' style='font-size:11px;color:#555;margin:2px 0 8px;'>"
           f"<b>{heading}</b><ol style='margin:2px 0 0 18px;padding:0;'>"]
    for fn in footnotes:
        out.append(f"<li>{_pol_escape(fn)}</li>")
    out.append("</ol></div>")
    return "\n".join(out)


def inventory_html(n, meta, with_title=True):
    """Note 9 — Inventories (Balance Sheet): closing stock by category."""
    a = n['inventory']
    _, py_h, _ = _inv_meta(meta)
    out = []
    if with_title:
        out.append(_note_title_html(n, meta))
    out.append(f"<table class='fs'><thead><tr><th>Particulars</th>"
               f"<th class='cyamt'>{meta['cy_header']}</th>{py_h}</tr></thead><tbody>")
    for r in a['rows']:
        out.append(f"<tr><td style='padding-left:18px'>{r['label']}</td>"
                   f"{_inv_amts(r['cy'], r['py'], meta)}</tr>")
    out.append(f"<tr class='b rule'><td>Total</td>"
               f"{_inv_amts(a['total_cy'], a['total_py'], meta)}</tr>")
    out.append("</tbody></table>")
    return "\n".join(out)


def cost_material_html(n, meta, with_title=True):
    """Note 16 — Cost of material consumed: per category O + Purchases − C."""
    a = n['cost_material']
    _, py_h, blank = _inv_meta(meta)
    out = []
    if with_title:
        out.append(_note_title_html(n, meta))
    out.append(f"<table class='fs'><thead><tr><th>Particulars</th>"
               f"<th class='cyamt'>{meta['cy_header']}</th>{py_h}</tr></thead><tbody>")
    for m in a['materials']:
        out.append(f"<tr class='b'><td>{m['label']}</td>{blank}</tr>")
        out.append(f"<tr><td style='padding-left:18px'>Opening stock</td>"
                   f"{_inv_amts(m['opening_cy'], m['opening_py'], meta)}</tr>")
        out.append(f"<tr><td style='padding-left:18px'>Purchases</td>"
                   f"{_inv_amts(m['purchases_cy'], m['purchases_py'], meta)}</tr>")
        out.append(f"<tr><td style='padding-left:18px'>Less: Closing stock</td>"
                   f"{_inv_amts(m['closing_cy'], m['closing_py'], meta)}</tr>")
        out.append(f"<tr class='b'><td style='padding-left:18px'>Total</td>"
                   f"{_inv_amts(m['total_cy'], m['total_py'], meta)}</tr>")
    if a['mfg']:
        out.append(f"<tr class='b'><td>Other Manufacturing Expenses</td>{blank}</tr>")
        for r in a['mfg']:
            lbl = r['label'] + (f" <span style='color:#888'>({r['group']})</span>"
                                if r.get('group') else "")
            out.append(f"<tr><td style='padding-left:18px'>{lbl}</td>"
                       f"{_inv_amts(r['cy'], r['py'], meta)}</tr>")
        out.append(f"<tr class='b'><td style='padding-left:18px'>Total</td>"
                   f"{_inv_amts(a['mfg_total_cy'], a['mfg_total_py'], meta)}</tr>")
    out.append(f"<tr class='b rule'><td>Total</td>"
               f"{_inv_amts(a['grand_cy'], a['grand_py'], meta)}</tr>")
    out.append("</tbody></table>")
    out.append(_inv_footnotes(a.get('footnotes'), "Foot Notes for Cost of Material Consumed"))
    return "\n".join(out)


def change_inv_html(n, meta, with_title=True):
    """Note 18 — Change in inventories of FG / WIP / stock-in-trade."""
    a = n['change_inv']
    _, py_h, blank = _inv_meta(meta)
    out = []
    if with_title:
        out.append(_note_title_html(n, meta))
    out.append(f"<table class='fs'><thead><tr><th>Particulars</th>"
               f"<th class='cyamt'>{meta['cy_header']}</th>{py_h}</tr></thead><tbody>")
    out.append(f"<tr class='b'><td>Opening Inventories</td>{blank}</tr>")
    for r in a['opening']:
        out.append(f"<tr><td style='padding-left:18px'>{r['label']}</td>"
                   f"{_inv_amts(r['cy'], r['py'], meta)}</tr>")
    out.append(f"<tr class='b'><td>Less: Closing Inventories</td>{blank}</tr>")
    for r in a['closing']:
        out.append(f"<tr><td style='padding-left:18px'>{r['label']}</td>"
                   f"{_inv_amts(r['cy'], r['py'], meta)}</tr>")
    out.append(f"<tr class='b rule'><td>Total</td>"
               f"{_inv_amts(a['total_cy'], a['total_py'], meta)}</tr>")
    out.append("</tbody></table>")
    out.append(_inv_footnotes(a.get('footnotes'),
                              "Foot Notes for Change in Inventories of WIP & Finished Goods"))
    return "\n".join(out)


# ── Disclosures: Entity information (Note 1) + Accounting policies (Note 2) ────
def resolve_policy_notes(company):
    """Resolve saved policies into render-ready Notes 1 (entity) & 2 (policies).
    Only disclosed heads that actually have text (or a table) are kept, lettered
    a, b, c… in order."""
    import string
    pol = fe.load_policies(company)
    ei = pol.get('entity_info', {})
    entity = ({'text': ei.get('text', '')}
              if ei.get('disclose') and str(ei.get('text', '')).strip() else None)
    items = []
    for p in pol.get('policies', []):
        has_content = bool(str(p.get('text', '')).strip()) or bool(p.get('table'))
        if p.get('disclose') and has_content:
            items.append(p)
    for i, p in enumerate(items):
        p['letter'] = string.ascii_lowercase[i] if i < 26 else str(i + 1)
    return {'entity': entity, 'policies': items}


def _pol_escape(s):
    return (str(s or '').replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;'))


def _policy_text_html(s):
    return _pol_escape(s).replace('\n', '<br>')


def _policy_table_html(p, meta):
    headers = p.get('table_headers') or ['Classification', 'Valuation Policy']
    cols = p.get('table_cols') or ['classification', 'policy']
    rows = [r for r in (p.get('table') or [])
            if any(str(r.get(c, '')).strip() for c in cols)]
    if not rows:
        return ""
    th = "".join(f"<th style='text-align:left'>{_pol_escape(h)}</th>" for h in headers)
    body = []
    for r in rows:
        body.append("<tr>" + "".join(
            f"<td>{_pol_escape(r.get(c, ''))}</td>" for c in cols) + "</tr>")
    return (f"<table class='fs' style='max-width:560px;margin:4px 0 8px 24px;'>"
            f"<thead><tr>{th}</tr></thead><tbody>{''.join(body)}</tbody></table>")


def policies_html(meta, pol):
    """Render Notes 1–2 (entity info + accounting policies). No section header —
    the caller emits `notes_header_html` once for the whole Notes section."""
    if not pol or (not pol.get('entity') and not pol.get('policies')):
        return ""
    hcol = meta['theme']['heading']
    out = []
    if pol.get('entity'):
        out.append(f"<div class='fswrap'><h3 class='fst' style='font-size:13px;'>"
                   f"1 ENTITY INFORMATION</h3>"
                   f"<div style='text-align:justify;margin:2px 0 8px;'>"
                   f"{_policy_text_html(pol['entity']['text'])}</div></div>")
    if pol.get('policies'):
        out.append(f"<div class='fswrap'><h3 class='fst' style='font-size:13px;'>"
                   f"2 SIGNIFICANT ACCOUNTING POLICIES</h3>")
        for p in pol['policies']:
            out.append(f"<div style='margin:8px 0 2px;'>"
                       f"<span style='display:inline-block;width:18px;color:{hcol};'>"
                       f"{p.get('letter','')}</span>"
                       f"<b style='color:{hcol};'>{_pol_escape(p.get('head',''))}</b></div>")
            if str(p.get('text', '')).strip():
                out.append(f"<div style='text-align:justify;margin:0 0 4px 18px;'>"
                           f"{_policy_text_html(p['text'])}</div>")
            if p.get('table'):
                out.append(_policy_table_html(p, meta))
        out.append("</div>")
    return "\n".join(out)


def notes_html(notes, meta, show_ledgers=False, policies=None):
    out = [notes_header_html(meta)]
    if policies:
        ph = policies_html(meta, policies)
        if ph:
            out.append(ph)
    for n in notes:
        out.append(one_note_html(n, meta, show_ledgers, with_title=True))
    return "\n".join(out)


def signature_html(meta):
    """Auditor (left) + entity signatories (right) block."""
    aud = meta.get('auditor', {})
    sign = meta.get('sign', {})
    spd = aud.get('show_place_date', 'Both')
    # auditor (left)
    left = ["As per our report of even date<br>"]
    if meta.get('print_ca_details', True) and aud.get('firm_name'):
        left.append(f"<b>For {aud.get('firm_name','')}</b><br>Chartered Accountants<br>")
        if aud.get('frn'):
            left.append(f"Firm's Registration No. {aud['frn']}<br>")
        left.append("<br>")
        if aud.get('ca_name'):
            left.append(f"{aud['ca_name']}<br>")
        left.append(f"{aud.get('designation','Chartered Accountant')}<br>")
        if aud.get('membership_no'):
            left.append(f"Membership No. {aud['membership_no']}<br>")
        if aud.get('show_udin', True):
            left.append(f"UDIN: {aud.get('udin','') or ''}<br>")
        adate = _dmy(aud)
        if spd in ('Both', 'Place') and aud.get('place'):
            left.append(f"Place: {aud['place']}<br>")
        if spd in ('Both', 'Date') and adate:
            left.append(f"Date: {adate}<br>")
    # entity signatories (right)
    sigs = meta.get('signatories', []) or []
    cells = []
    for s in sigs:
        if not (s.get('name') or s.get('pan')):
            continue
        cells.append(f"<td>{s.get('name','')}<br>{s.get('designation','')}<br>"
                     f"{('PAN: ' + s['pan']) if s.get('pan') else ''}</td>")
    sig_row = f"<table><tr>{''.join(cells)}</tr></table>" if cells else ""
    sdate = _dmy(sign)
    place_line = f"Place: {sign.get('place','')}" if sign.get('place') else ""
    date_line = f"Date: {sdate}" if sdate else ""
    right = (f"<b>For {meta['entity_name']}</b><br><br>{sig_row}"
             f"<div style='margin-top:6px'>{place_line}&nbsp;&nbsp;&nbsp;{date_line}</div>")
    return (f"<div class='fswrap'><table class='sigblk'><tr>"
            f"<td style='width:48%'>{''.join(left)}</td><td>{right}</td>"
            f"</tr></table>"
            f"<div style='font-size:11px;color:#555;margin-top:10px'>"
            f"See accompanying notes which form part of the financial statements</div></div>")


def build_html(stmts):
    """Print-ready standalone HTML (open in a browser → Print → Save as PDF).
    Note numbers in the BS/P&L link to the matching note; each note title links back
    to the statement (works because everything is on one page here)."""
    meta = dict(stmts['meta'], link_xref=True)   # enable cross-reference hyperlinks
    cyh = meta['cy_header']
    body = "\n".join([
        themed_css(meta),
        "<div style='max-width:900px;margin:16px auto;'>",
        "<a id='stmt-bs'></a>",
        statement_html(f"Balance Sheet as at {cyh}", stmts['bs'], meta),
        signature_html(meta),
        "<div style='page-break-before:always'></div>",
        "<a id='stmt-pl'></a>",
        statement_html(f"Statement of Profit and Loss for the year ended {cyh}", stmts['pl'], meta),
        signature_html(meta),
        "<div style='page-break-before:always'></div>",
        notes_html(stmts['notes'], meta, policies=stmts.get('policies')),
        "</div>",
    ])
    return f"<!doctype html><html><head><meta charset='utf-8'></head><body>{body}</body></html>"


# ── Real PDF (reportlab): paginated, themed, auto page-breaks + borders ────────
def _pdf_font(name):
    n = (name or "").lower()
    if "times" in n or "georgia" in n:
        return "Times-Roman", "Times-Bold"
    return "Helvetica", "Helvetica-Bold"


def _pdf_esc(s):
    return (str(s if s is not None else "")
            .replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def build_pdf(stmts):
    """True multi-page PDF via reportlab — Balance Sheet, Statement of P&L and
    Notes, each on its own page(s), with automatic page-breaks, repeating table
    headers, themed header shading and borders that match the chosen layout."""
    from io import BytesIO
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.lib import colors
    from reportlab.platypus import (SimpleDocTemplate, Table, TableStyle, Paragraph,
                                    Spacer, PageBreak, KeepTogether)
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.enums import TA_LEFT, TA_RIGHT, TA_CENTER, TA_JUSTIFY

    meta = stmts['meta']
    cyh, pyh = meta['cy_header'], meta['py_header']
    has_py = meta['has_py']
    show_note = bool(meta.get('show_notes_col', True))
    theme = meta['theme']
    head_col = colors.HexColor(theme['heading'])
    shade = colors.HexColor(theme['cy_shade'])
    bstyle = meta['border']
    xl = bstyle.get('xl')                                   # 'thin' | 'hair' | None
    grid = xl is not None
    grid_col = colors.HexColor('#333333') if xl == 'thin' else colors.HexColor('#bbbbbb')
    base_font, bold_font = _pdf_font(meta['font'])
    align_map = {'left': TA_LEFT, 'center': TA_CENTER, 'right': TA_RIGHT}
    head_align = align_map.get(meta.get('header_align', 'left'), TA_LEFT)

    def m(x):
        return _money(x, meta) if x is not None else ''

    def P(txt, size=8, bold=False, color=colors.black, align=TA_LEFT, indent=0):
        s = ParagraphStyle('c', fontName=bold_font if bold else base_font,
                           fontSize=size, leading=size + 2.5, textColor=color,
                           alignment=align, leftIndent=indent, wordWrap='CJK')
        return Paragraph(_pdf_esc(txt).replace("\n", "<br/>"), s)

    page_w = A4[0]
    usable = page_w - 30 * mm

    def entity_header(title):
        flow = [P(meta['entity_name'], 12.5, True, head_col, head_align)]
        if meta.get('address'):
            flow.append(P(f"({meta['address']})", 8, align=head_align))
        flow.append(P(title, 10.5, True, head_col, head_align))
        flow.append(P(f"({meta['units_label']})", 7.5, align=TA_RIGHT))
        if not meta['balanced']:
            flow.append(P(f"Out of balance by {m(meta['difference'])} — review stock / adjustments.",
                          8, True, colors.HexColor('#b3261e')))
        flow.append(Spacer(1, 4))
        return flow

    def base_style(nrows):
        s = [('VALIGN', (0, 0), (-1, -1), 'TOP'),
             ('TOPPADDING', (0, 0), (-1, -1), 1.6),
             ('BOTTOMPADDING', (0, 0), (-1, -1), 1.6),
             ('LEFTPADDING', (0, 0), (-1, -1), 4),
             ('RIGHTPADDING', (0, 0), (-1, -1), 4),
             ('BACKGROUND', (0, 0), (-1, 0), shade)]
        if grid:
            s.append(('GRID', (0, 0), (-1, -1), 0.4, grid_col))
        else:
            s.append(('LINEBELOW', (0, 0), (-1, 0), 0.7, colors.black))
        return s

    def stmt_table(rows):
        if show_note and has_py:
            widths = [usable * .50, usable * .08, usable * .21, usable * .21]
        elif show_note:
            widths = [usable * .64, usable * .10, usable * .26]
        elif has_py:
            widths = [usable * .56, usable * .22, usable * .22]
        else:
            widths = [usable * .72, usable * .28]
        cy_idx = 1 + (1 if show_note else 0)
        hdr = [P('Particulars', 8, True)]
        if show_note:
            hdr.append(P('Note', 8, True, align=TA_CENTER))
        hdr.append(P(cyh, 8, True, align=TA_RIGHT))
        if has_py:
            hdr.append(P(pyh, 8, True, align=TA_RIGHT))
        data = [hdr]
        style = base_style(len(rows) + 1)
        style.append(('BACKGROUND', (cy_idx, 1), (cy_idx, -1), shade))
        ri = 1
        for row in rows:
            b = bool(row.get('bold'))
            lvl = int(row.get('level', 0))
            cells = [P(row['label'], 8, b, indent=lvl * 9)]
            if show_note:
                cells.append(P(row.get('note') or '', 8, align=TA_CENTER))
            cells.append(P(m(row.get('cy')) if row.get('cy') is not None else '', 8, b, align=TA_RIGHT))
            if has_py:
                cells.append(P(m(row.get('py')) if row.get('py') is not None else '', 8, b, align=TA_RIGHT))
            data.append(cells)
            if row.get('rule'):
                style.append(('LINEABOVE', (0, ri), (-1, ri), 0.7, colors.black))
            ri += 1
        t = Table(data, colWidths=widths, repeatRows=1)
        t.setStyle(TableStyle(style))
        return t

    def sig_flow():
        aud = meta.get('auditor', {}) or {}
        sign = meta.get('sign', {}) or {}
        spd = aud.get('show_place_date', 'Both')
        left = ["As per our report of even date"]
        if meta.get('print_ca_details', True) and aud.get('firm_name'):
            left += [f"<b>For {_pdf_esc(aud.get('firm_name',''))}</b>", "Chartered Accountants"]
            if aud.get('frn'):
                left.append(f"Firm's Registration No. {_pdf_esc(aud['frn'])}")
            left += ["", "", "", ""]      # blank space for signature & seal
            if aud.get('ca_name'):
                left.append(_pdf_esc(aud['ca_name']))
            left.append(_pdf_esc(aud.get('designation', 'Chartered Accountant')))
            if aud.get('membership_no'):
                left.append(f"Membership No. {_pdf_esc(aud['membership_no'])}")
            if aud.get('show_udin', True):
                left.append(f"UDIN: {_pdf_esc(aud.get('udin','') or '')}")
            adate = _dmy(aud)
            if spd in ('Both', 'Place') and aud.get('place'):
                left.append(f"Place: {_pdf_esc(aud['place'])}")
            if spd in ('Both', 'Date') and adate:
                left.append(f"Date: {_pdf_esc(adate)}")
        right = [f"<b>For {_pdf_esc(meta['entity_name'])}</b>", "", "", "", ""]  # signing space
        for s in (meta.get('signatories', []) or []):
            if not (s.get('name') or s.get('pan')):
                continue
            right.append(_pdf_esc(s.get('name', '')))
            right.append(_pdf_esc(s.get('designation', '')))
            if s.get('pan'):
                right.append(f"PAN: {_pdf_esc(s['pan'])}")
            right.append("")
        sdate = _dmy(sign)
        if sign.get('place'):
            right.append(f"Place: {_pdf_esc(sign['place'])}")
        if sdate:
            right.append(f"Date: {_pdf_esc(sdate)}")
        lstyle = ParagraphStyle('l', fontName=base_font, fontSize=8, leading=12.5)
        lp = Paragraph("<br/>".join(left), lstyle)
        rp = Paragraph("<br/>".join(right), lstyle)
        t = Table([[lp, rp]], colWidths=[usable * .5, usable * .5])
        t.setStyle(TableStyle([('VALIGN', (0, 0), (-1, -1), 'TOP'),
                               ('LEFTPADDING', (0, 0), (-1, -1), 0),
                               ('TOPPADDING', (0, 0), (-1, -1), 6)]))
        return [Spacer(1, 26), t,
                P("See accompanying notes which form part of the financial statements",
                  7.5, color=colors.HexColor('#555555'))]

    def note_table(n):
        cols2 = [usable * (.60 if has_py else .72)]
        cols2.append(usable * (.20 if has_py else .28))
        if has_py:
            cols2.append(usable * .20)
        hdr = [P('Particulars', 8, True), P(cyh, 8, True, align=TA_RIGHT)]
        if has_py:
            hdr.append(P(pyh, 8, True, align=TA_RIGHT))
        data = [hdr]
        style = base_style(0)
        for ln in n['lines']:
            subs = ln.get('subs')
            if subs:
                row = [P(ln['label'], 8, indent=9), P('', 8)]
                if has_py:
                    row.append(P('', 8))
                data.append(row)
                for sb in subs:
                    r2 = [P("– " + str(sb['label']), 8, indent=18),
                          P(m(sb.get('cy')) if sb.get('cy') is not None else '', 8, align=TA_RIGHT)]
                    if has_py:
                        r2.append(P(m(sb.get('py')) if sb.get('py') is not None else '', 8, align=TA_RIGHT))
                    data.append(r2)
            else:
                r1 = [P(ln['label'], 8, indent=9),
                      P(m(ln.get('cy')) if ln.get('cy') is not None else '', 8, align=TA_RIGHT)]
                if has_py:
                    r1.append(P(m(ln.get('py')) if ln.get('py') is not None else '', 8, align=TA_RIGHT))
                data.append(r1)
        tot = [P('Total', 8, True), P(m(n.get('cy')), 8, True, align=TA_RIGHT)]
        if has_py:
            tot.append(P(m(n.get('py')) if n.get('py') is not None else '', 8, True, align=TA_RIGHT))
        data.append(tot)
        style.append(('LINEABOVE', (0, len(data) - 1), (-1, len(data) - 1), 0.7, colors.black))
        t = Table(data, colWidths=cols2, repeatRows=1)
        t.setStyle(TableStyle(style))
        return t

    def far_table(n):
        far = n['far']
        heads = ['Name of Assets', 'Gross\nOpening', 'Addn', 'Dedn', 'Gross\nClosing',
                 'Dep\nOpening', 'Dep\nYear', 'Dep\nDedn', 'Dep\nClosing',
                 f'Net\n{cyh}', f'Net\n{pyh}']
        ckeys = ['g_open', 'g_add', 'g_ded', 'g_close', 'd_open', 'd_year',
                 'd_ded', 'd_close', 'n_close', 'n_open']
        data = [[P(h, 6, True, align=TA_CENTER) for h in heads]]
        style = base_style(0)
        if far.get('section'):
            data.append([P(far['section'], 6, True)] + [P('', 6)] * 10)
        for b in far['rows']:
            data.append([P(b['name'], 6)] +
                        [P(m(b.get(k)), 6, align=TA_RIGHT) for k in ckeys])
        t = far['total']
        data.append([P('Total', 6, True)] + [P(m(t.get(k)), 6, True, align=TA_RIGHT) for k in ckeys])
        w0 = usable * .18
        wr = (usable - w0) / 10
        tb = Table(data, colWidths=[w0] + [wr] * 10, repeatRows=1)
        tb.setStyle(TableStyle(style))
        return tb

    def partners_table(n):
        p = n['partners']
        scheds = ([("Partners' Contribution Account", p['fixed'], _P_FIX_FIELDS),
                   ("Partners' Current Account", p['current'], _P_CUR_FIELDS)]
                  if p.get('fixed') else
                  [("Partners' Capital Account", p['current'], _P_CUR_FIELDS)])
        flows = []
        for title, sched, fields in scheds:
            flows.append(P(title, 8.5, True, head_col))
            heads = ['Name of Partner', 'Share %'] + [lbl for _, lbl in fields] + ['Closing']
            data = [[P(h, 6.5, True, align=(TA_RIGHT if i else TA_LEFT))
                     for i, h in enumerate(heads)]]
            style = base_style(0)
            for row in sched['rows']:
                line = [P(row['name'], 6.5), P(f"{row['share']:.2f}", 6.5, align=TA_RIGHT)]
                line += [P(m(row[k]), 6.5, align=TA_RIGHT) for k, _ in fields]
                line.append(P(m(row['closing']), 6.5, align=TA_RIGHT))
                data.append(line)
            tt = sched['total']
            line = [P('Total', 6.5, True), P(f"{tt['share']:.2f}", 6.5, True, align=TA_RIGHT)]
            line += [P(m(tt[k]), 6.5, True, align=TA_RIGHT) for k, _ in fields]
            line.append(P(m(tt['closing']), 6.5, True, align=TA_RIGHT))
            data.append(line)
            nc = len(heads)
            w0 = usable * .20
            wr = (usable - w0) / (nc - 1)
            tb = Table(data, colWidths=[w0] + [wr] * (nc - 1), repeatRows=1)
            tb.setStyle(TableStyle(style))
            flows += [tb, Spacer(1, 4)]
        return flows

    def ageing_pdf(n):
        a = n['ageing']
        flow = [P(f"{n['num']}.1  Trade Receivables Ageing Schedule", 8.5, True, head_col)]
        cols2 = [usable * (.60 if has_py else .72), usable * (.20 if has_py else .28)]
        if has_py:
            cols2.append(usable * .20)
        hdr = [P('Particulars', 8, True), P(cyh, 8, True, align=TA_RIGHT)]
        if has_py:
            hdr.append(P(pyh, 8, True, align=TA_RIGHT))
        data = [hdr]
        style = base_style(0)

        def row(label, cy, py, bold=False, indent=14):
            cells = [P(label, 8, bold, indent=indent),
                     P(m(cy) if cy is not None else '', 8, bold, align=TA_RIGHT)]
            if has_py:
                cells.append(P(m(py) if py is not None else '', 8, bold, align=TA_RIGHT))
            data.append(cells)

        for sec in a.get('sections', []):
            row(sec['title'], None, None, bold=True, indent=4)
            for r in sec['rows']:
                row(r['label'], r['cy'], r['py'])
            row('', sec['sub_cy'], sec['sub_py'], bold=True)
        for r in a.get('extras', []):
            row(r['label'], r['cy'], r['py'])
        row("Total", a['total_cy'], a['total_py'], bold=True, indent=4)
        style.append(('LINEABOVE', (0, len(data) - 1), (-1, len(data) - 1), 0.7, colors.black))
        t = Table(data, colWidths=cols2, repeatRows=1)
        t.setStyle(TableStyle(style))
        flow.append(t)
        for fn in a.get('footnotes', []):
            flow.append(P("• " + fn, 7.5, color=colors.HexColor('#555555'), indent=4))
        return flow

    def owners_pdf(n):
        a = n['owners_capital']
        cols2 = [usable * (.60 if has_py else .72), usable * (.20 if has_py else .28)]
        if has_py:
            cols2.append(usable * .20)
        hdr = [P('Particulars', 8, True), P(cyh, 8, True, align=TA_RIGHT)]
        if has_py:
            hdr.append(P(pyh, 8, True, align=TA_RIGHT))
        data = [hdr]
        style = base_style(0)

        def row(label, cy, py, bold=False, indent=14):
            cells = [P(label, 8, bold, indent=indent),
                     P(m(cy) if cy is not None else '', 8, bold, align=TA_RIGHT)]
            if has_py:
                cells.append(P(m(py) if py is not None else '', 8, bold, align=TA_RIGHT))
            data.append(cells)

        for r in a['credit_rows']:
            row(r['label'], r['cy'], r['py'])
        row("Total of Credit Side", a['credit_total_cy'], a['credit_total_py'], bold=True, indent=4)
        row("Less:", None, None, bold=True, indent=4)
        for r in a['debit_rows']:
            row(r['label'], r['cy'], r['py'])
        row("Total of Debit Side", a['debit_total_cy'], a['debit_total_py'], bold=True, indent=4)
        row("Total", a['total_cy'], a['total_py'], bold=True, indent=4)
        style.append(('LINEABOVE', (0, len(data) - 1), (-1, len(data) - 1), 0.7, colors.black))
        t = Table(data, colWidths=cols2, repeatRows=1)
        t.setStyle(TableStyle(style))
        flow = [t]
        for fn in a.get('footnotes', []):
            flow.append(P("• " + fn, 7.5, color=colors.HexColor('#555555'), indent=4))
        return flow

    def _inv_cols():
        c = [usable * (.60 if has_py else .72), usable * (.20 if has_py else .28)]
        if has_py:
            c.append(usable * .20)
        return c

    def _inv_hdr():
        h = [P('Particulars', 8, True), P(cyh, 8, True, align=TA_RIGHT)]
        if has_py:
            h.append(P(pyh, 8, True, align=TA_RIGHT))
        return h

    def _inv_row(data, label, cy, py, bold=False, indent=14):
        cells = [P(label, 8, bold, indent=indent),
                 P(m(cy) if cy is not None else '', 8, bold, align=TA_RIGHT)]
        if has_py:
            cells.append(P(m(py) if py is not None else '', 8, bold, align=TA_RIGHT))
        data.append(cells)

    def inventory_pdf(n):
        a = n['inventory']
        data, style = [_inv_hdr()], base_style(0)
        for r in a['rows']:
            _inv_row(data, r['label'], r['cy'], r['py'])
        _inv_row(data, 'Total', a['total_cy'], a['total_py'], bold=True, indent=4)
        style.append(('LINEABOVE', (0, len(data) - 1), (-1, len(data) - 1), 0.7, colors.black))
        t = Table(data, colWidths=_inv_cols(), repeatRows=1)
        t.setStyle(TableStyle(style))
        return [t]

    def cost_material_pdf(n):
        a = n['cost_material']
        data, style = [_inv_hdr()], base_style(0)
        for mt in a['materials']:
            _inv_row(data, mt['label'], None, None, bold=True, indent=4)
            _inv_row(data, 'Opening stock', mt['opening_cy'], mt['opening_py'])
            _inv_row(data, 'Purchases', mt['purchases_cy'], mt['purchases_py'])
            _inv_row(data, 'Less: Closing stock', mt['closing_cy'], mt['closing_py'])
            _inv_row(data, 'Total', mt['total_cy'], mt['total_py'], bold=True, indent=14)
        if a['mfg']:
            _inv_row(data, 'Other Manufacturing Expenses', None, None, bold=True, indent=4)
            for r in a['mfg']:
                lbl = r['label'] + (f" ({r['group']})" if r.get('group') else "")
                _inv_row(data, lbl, r['cy'], r['py'])
            _inv_row(data, 'Total', a['mfg_total_cy'], a['mfg_total_py'], bold=True, indent=14)
        _inv_row(data, 'Total', a['grand_cy'], a['grand_py'], bold=True, indent=4)
        style.append(('LINEABOVE', (0, len(data) - 1), (-1, len(data) - 1), 0.7, colors.black))
        t = Table(data, colWidths=_inv_cols(), repeatRows=1)
        t.setStyle(TableStyle(style))
        flow = [t]
        for fn in a.get('footnotes', []):
            flow.append(P("• " + fn, 7.5, color=colors.HexColor('#555555'), indent=4))
        return flow

    def change_inv_pdf(n):
        a = n['change_inv']
        data, style = [_inv_hdr()], base_style(0)
        _inv_row(data, 'Opening Inventories', None, None, bold=True, indent=4)
        for r in a['opening']:
            _inv_row(data, r['label'], r['cy'], r['py'])
        _inv_row(data, 'Less: Closing Inventories', None, None, bold=True, indent=4)
        for r in a['closing']:
            _inv_row(data, r['label'], r['cy'], r['py'])
        _inv_row(data, 'Total', a['total_cy'], a['total_py'], bold=True, indent=4)
        style.append(('LINEABOVE', (0, len(data) - 1), (-1, len(data) - 1), 0.7, colors.black))
        t = Table(data, colWidths=_inv_cols(), repeatRows=1)
        t.setStyle(TableStyle(style))
        flow = [t]
        for fn in a.get('footnotes', []):
            flow.append(P("• " + fn, 7.5, color=colors.HexColor('#555555'), indent=4))
        return flow

    def fixed_assets_pdf(n):
        a = n['fixed_assets']
        blocks = [a['cwip'], a['intan']]
        present = [b for b in blocks if b.get('present')]
        disclosed = [b for b in blocks if b.get('disclose')]
        if not present and not disclosed:
            return []
        flow = []
        if present:
            data, style = [_inv_hdr()], base_style(0)
            for b in present:
                _inv_row(data, f"{b['roman']} {b['label']}", b['net_cy'], b['net_py'],
                         bold=True, indent=4)
            tsum = Table(data, colWidths=_inv_cols(), repeatRows=1)
            tsum.setStyle(TableStyle(style))
            flow += [tsum, Spacer(1, 4)]
        for b in disclosed:
            flow.append(P(f"{b['roman']} {b['label']}", 8.5, True, head_col))
            data, style = [_inv_hdr()], base_style(0)
            _inv_row(data, "Opening Balance", b['opening_cy'], b['opening_py'])
            _inv_row(data, "Add: Addition during the year", b['addition_cy'], b['addition_py'])
            _inv_row(data, "Less: Capitalised during the year",
                     b['capitalised_cy'], b['capitalised_py'])
            _inv_row(data, "Closing Balance", b['closing_cy'], b['closing_py'], bold=True)
            style.append(('LINEABOVE', (0, len(data) - 1), (-1, len(data) - 1), 0.7, colors.black))
            t = Table(data, colWidths=_inv_cols(), repeatRows=1)
            t.setStyle(TableStyle(style))
            flow += [t, Spacer(1, 3)]
        for fn in a.get('footnotes', []):
            flow.append(P("• " + fn, 7.5, color=colors.HexColor('#555555'), indent=4))
        return flow

    # ── Assemble the document ─────────────────────────────────────────────────
    story = []
    story += entity_header(f"Balance Sheet as at {cyh}")
    story.append(stmt_table(stmts['bs']))
    story += sig_flow()
    story.append(PageBreak())
    story += entity_header(f"Statement of Profit and Loss for the year ended {cyh}")
    story.append(stmt_table(stmts['pl']))
    story += sig_flow()
    story.append(PageBreak())
    story += entity_header("Notes forming part of the Financial Statements")

    pol = stmts.get('policies') or {}
    if pol.get('entity'):
        story.append(P("1  ENTITY INFORMATION", 9.5, True, head_col))
        story.append(P(pol['entity']['text'], 8, align=TA_JUSTIFY))
        story.append(Spacer(1, 5))
    if pol.get('policies'):
        story.append(P("2  SIGNIFICANT ACCOUNTING POLICIES", 9.5, True, head_col))
        for pp in pol['policies']:
            story.append(P(f"{pp.get('letter','')}  {pp.get('head','')}", 8.5, True, head_col))
            if str(pp.get('text', '')).strip():
                story.append(P(pp['text'], 8, align=TA_JUSTIFY, indent=10))
            story.append(Spacer(1, 3))

    for n in stmts['notes']:
        # Keep each note (title + its table) on one page — if it doesn't fit in the
        # space left, reportlab moves the whole note to the next page rather than
        # splitting it. (A note genuinely taller than a full page still flows.)
        blk = [P(f"{n['num']}  {n['title']}", 9, True, head_col)]
        if n.get('far'):
            blk.append(far_table(n))
        elif n.get('partners'):
            blk += partners_table(n)
        elif n.get('owners_capital'):
            blk += owners_pdf(n)
        elif n.get('inventory'):
            blk += inventory_pdf(n)
        elif n.get('cost_material'):
            blk += cost_material_pdf(n)
        elif n.get('change_inv'):
            blk += change_inv_pdf(n)
        else:
            blk.append(note_table(n))
        story.append(Spacer(1, 5))
        story.append(KeepTogether(blk))
        if n.get('ageing'):
            story.append(Spacer(1, 4))
            story.append(KeepTogether(ageing_pdf(n)))
        if n.get('fixed_assets'):
            story.append(Spacer(1, 4))
            story.append(KeepTogether(fixed_assets_pdf(n)))

    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=15 * mm, rightMargin=15 * mm,
                            topMargin=15 * mm, bottomMargin=14 * mm,
                            title=f"{meta['entity_name']} Financials")

    def _foot(canvas, d):
        canvas.saveState()
        canvas.setFont(base_font, 7)
        canvas.setFillColor(colors.HexColor('#777777'))
        canvas.drawRightString(page_w - 15 * mm, 8 * mm, f"Page {d.page}")
        canvas.restoreState()

    doc.build(story, onFirstPage=_foot, onLaterPages=_foot)
    return buf.getvalue()


def build_excel(stmts):
    """Workbook bytes (BS / P&L / Notes sheets) via openpyxl, theme-aware."""
    from io import BytesIO
    from openpyxl import Workbook
    from openpyxl.styles import Font, Border, Side, Alignment, PatternFill

    meta = stmts['meta']
    cyh, pyh = meta['cy_header'], meta['py_header']
    has_py = meta['has_py']
    font_name = meta['font']
    theme = meta['theme']
    head_hex = theme['heading'].lstrip('#').upper()
    shade_hex = theme['cy_shade'].lstrip('#').upper()
    xl_side = meta['border'].get('xl')

    base = Font(name=font_name)
    bold = Font(name=font_name, bold=True)
    title_f = Font(name=font_name, bold=True, size=13, color=head_hex)
    shade = PatternFill("solid", fgColor=shade_hex)
    top = Border(top=Side(style='thin'))
    cell_border = Border(*([Side(style=xl_side)] * 4)) if xl_side else None
    right = Alignment(horizontal='right')
    nfmt = '#,##0.00;(#,##0.00)' if meta.get('two_decimals') else '#,##0;(#,##0)'
    link_font = Font(name=font_name, color="0563C1", underline="single")
    link_bold = Font(name=font_name, color="0563C1", underline="single", bold=True)
    wb = Workbook()

    note_rows = {}        # note num -> row of its title cell in the Notes sheet
    face_stmt_ref = {}    # face title -> (statement sheet title, row) for back-links

    def amt(x):
        if x is None:
            return None
        return round(float(x), 2) if meta.get('two_decimals') else round(float(x))

    def write_stmt(ws, title, rows):
        ws['A1'] = meta['entity_name']; ws['A1'].font = title_f
        if meta.get('address'):
            ws['A2'] = f"({meta['address']})"; ws['A2'].font = base
        ws['A3'] = title; ws['A3'].font = title_f
        ws['A4'] = f"({meta['units_label']})"; ws['A4'].font = base
        hr = 5
        cy_col = 3
        py_col = 4
        ws.cell(hr, 1, "Particulars").font = bold
        ws.cell(hr, 2, "Note").font = bold
        hc = ws.cell(hr, cy_col, cyh); hc.font = bold; hc.fill = shade
        if has_py:
            ws.cell(hr, py_col, pyh).font = bold
        r = hr + 1
        for row in rows:
            ws.cell(r, 1, ("    " * int(row.get('level', 0))) + str(row['label'])).font = base
            nv = row.get('note') or ''
            nc = ws.cell(r, 2, nv)
            if nv and nv in note_rows:                 # forward link: Note no. -> Notes sheet
                nc.hyperlink = f"#'Notes'!A{note_rows[nv]}"
                nc.font = link_font
            if nv and row.get('is_face'):               # remember where this face sits
                face_stmt_ref[str(row.get('face') or row['label'])] = (ws.title, r)
            v_cy = amt(row.get('cy'))
            cc = ws.cell(r, cy_col, v_cy); cc.fill = shade
            if v_cy is not None:
                cc.number_format = nfmt; cc.alignment = right
            if has_py:
                v_py = amt(row.get('py'))
                cp = ws.cell(r, py_col, v_py)
                if v_py is not None:
                    cp.number_format = nfmt; cp.alignment = right
            ncols = py_col if has_py else cy_col
            if row.get('bold'):
                for col in range(1, ncols + 1):
                    cur = ws.cell(r, col)
                    cur.font = Font(name=font_name, bold=True)
            if row.get('rule'):
                for col in range(1, ncols + 1):
                    ws.cell(r, col).border = top
            r += 1
        ws.column_dimensions['A'].width = 48
        ws.column_dimensions['B'].width = 7
        ws.column_dimensions['C'].width = 16
        ws.column_dimensions['D'].width = 16

    # Tab order: Balance Sheet, P&L, Notes. Notes is WRITTEN FIRST so we know each
    # note's row before linking the statements to it.
    ws1 = wb.active; ws1.title = "Balance Sheet"
    ws2 = wb.create_sheet("Statement of P&L")
    wsn = wb.create_sheet("Notes")
    wsn['A1'] = meta['entity_name']; wsn['A1'].font = title_f
    wsn['A2'] = "Notes forming part of the Financial Statements"; wsn['A2'].font = title_f
    r = 4

    # Notes 1–2 — Entity information + Accounting policies
    pol = stmts.get('policies') or {}
    if pol.get('entity'):
        wsn.cell(r, 1, "1  ENTITY INFORMATION").font = bold; r += 1
        wsn.cell(r, 1, str(pol['entity'].get('text', '')).replace('\n', ' ')).font = base; r += 2
    if pol.get('policies'):
        wsn.cell(r, 1, "2  SIGNIFICANT ACCOUNTING POLICIES").font = bold; r += 1
        for p in pol['policies']:
            wsn.cell(r, 1, f"{p.get('letter','')}  {p.get('head','')}").font = bold; r += 1
            if str(p.get('text', '')).strip():
                wsn.cell(r, 1, "    " + str(p['text']).replace('\n', ' ')).font = base; r += 1
            for tr in (p.get('table') or []):
                cells = [str(tr.get(c, '')) for c in (p.get('table_cols') or [])]
                if any(c.strip() for c in cells):
                    wsn.cell(r, 1, "        " + " — ".join(cells)).font = base; r += 1
            r += 1
        r += 1

    def _write_far_excel(n, r):
        far = n['far']
        wsn.cell(r, 1, f"{n['num']} {n['title']}").font = bold; note_rows[n['num']] = r
        r += 1
        heads = ["Name of Assets", "Gross Opening", "Addition", "Deduction",
                 "Gross Closing", "Dep Opening", "Dep For Year", "Dep Deduction",
                 "Dep Closing", f"Net {cyh}", f"Net {pyh}"]
        for ci, h in enumerate(heads, start=1):
            cc = wsn.cell(r, ci, h); cc.font = bold
            if ci == 10:
                cc.fill = shade
        r += 1
        ckeys = ['g_open', 'g_add', 'g_ded', 'g_close', 'd_open', 'd_year',
                 'd_ded', 'd_close', 'n_close', 'n_open']
        if far.get('section'):
            wsn.cell(r, 1, far['section']).font = bold; r += 1

        def _frow(name, d, boldrow=False):
            nonlocal r
            nm = wsn.cell(r, 1, str(name)); nm.font = bold if boldrow else base
            for ci, k in enumerate(ckeys, start=2):
                v = amt(d.get(k))
                cell = wsn.cell(r, ci, v)
                if ci == 10:
                    cell.fill = shade
                if v is not None:
                    cell.number_format = nfmt; cell.alignment = right
                if boldrow:
                    cell.font = bold
            r += 1

        for b in far['rows']:
            _frow(b['name'], b)
        _frow("Total", far['total'], boldrow=True)
        _frow("Previous Year", {'n_close': far['total'].get('n_open')}, boldrow=True)
        return r + 1

    def _write_partners_excel(n, r):
        p = n['partners']
        wsn.cell(r, 1, f"{n['num']} {n['title']}").font = bold; note_rows[n['num']] = r
        r += 1
        scheds = ([("Partners' Contribution Account", p['fixed'], _P_FIX_FIELDS),
                   ("Partners' Current Account", p['current'], _P_CUR_FIELDS)]
                  if p.get('fixed') else
                  [("Partners' Capital Account", p['current'], _P_CUR_FIELDS)])
        for title, sched, fields in scheds:
            wsn.cell(r, 1, title).font = bold
            r += 1
            # header: Name | Share | fields... | Closing  (horizontal layout in Excel)
            heads = ["Name of Partner", "Share %"] + [lbl for _, lbl in fields] + ["Closing"]
            for ci, h in enumerate(heads, start=1):
                wsn.cell(r, ci, h).font = bold
            r += 1
            def _pxrow(label, share, vals, closing, boldrow=False):
                nonlocal r
                wsn.cell(r, 1, label).font = bold if boldrow else base
                if share is not None:
                    wsn.cell(r, 2, share)
                for ci, v in enumerate(vals, start=3):
                    vv = amt(v) if v is not None else None
                    c = wsn.cell(r, ci, vv)
                    if vv is not None:
                        c.number_format = nfmt; c.alignment = right
                    if boldrow:
                        c.font = bold
                cc = wsn.cell(r, 2 + len(vals) + 1, amt(closing) if closing is not None else None)
                cc.fill = shade
                if cc.value is not None:
                    cc.number_format = nfmt; cc.alignment = right
                if boldrow:
                    cc.font = bold
                r += 1
            for row in sched['rows']:
                _pxrow(row['name'], row['share'], [row[k] for k, _ in fields], row['closing'])
            t = sched['total']
            _pxrow("Total", t['share'], [t[k] for k, _ in fields], t['closing'], boldrow=True)
            py = sched.get('py') or {}
            _pxrow("Previous Year", None, [py.get(k) for k, _ in fields],
                   py.get('closing'), boldrow=True)
            r += 1
        return r + 1

    def _write_owners_excel(n, r):
        a = n['owners_capital']
        wsn.cell(r, 1, f"{n['num']} {n['title']}").font = bold; note_rows[n['num']] = r
        hc = wsn.cell(r, 3, cyh); hc.font = bold; hc.fill = shade
        if has_py:
            wsn.cell(r, 4, pyh).font = bold
        r += 1

        def w(label, cy_v, py_v, boldrow=False, indent=1):
            nonlocal r
            wsn.cell(r, 1, ("    " * indent) + str(label)).font = bold if boldrow else base
            v = amt(cy_v)
            c = wsn.cell(r, 3, v); c.fill = shade
            if v is not None:
                c.number_format = nfmt; c.alignment = right
            if boldrow:
                c.font = bold
            if has_py:
                vp = amt(py_v)
                cp = wsn.cell(r, 4, vp)
                if vp is not None:
                    cp.number_format = nfmt; cp.alignment = right
                if boldrow:
                    cp.font = bold
            r += 1

        for rr in a['credit_rows']:
            w(rr['label'], rr['cy'], rr['py'])
        w("Total of Credit Side", a['credit_total_cy'], a['credit_total_py'], boldrow=True, indent=0)
        w("Less:", None, None, boldrow=True, indent=0)
        for rr in a['debit_rows']:
            w(rr['label'], rr['cy'], rr['py'])
        w("Total of Debit Side", a['debit_total_cy'], a['debit_total_py'], boldrow=True, indent=0)
        w("Total", a['total_cy'], a['total_py'], boldrow=True, indent=0)
        for fn in a.get('footnotes', []):
            wsn.cell(r, 1, "• " + str(fn)).font = base; r += 1
        return r + 1

    def _inv_excel_head(n, r):
        wsn.cell(r, 1, f"{n['num']} {n['title']}").font = bold; note_rows[n['num']] = r
        hc = wsn.cell(r, 3, cyh); hc.font = bold; hc.fill = shade
        if has_py:
            wsn.cell(r, 4, pyh).font = bold
        return r + 1

    def _inv_excel_row(r, label, cy_v, py_v, boldrow=False, indent=1, top_border=False):
        wsn.cell(r, 1, ("    " * indent) + str(label)).font = bold if boldrow else base
        v = amt(cy_v)
        c = wsn.cell(r, 3, v); c.fill = shade
        if v is not None:
            c.number_format = nfmt; c.alignment = right
        if boldrow:
            c.font = bold
        if top_border:
            c.border = top
        if has_py:
            vp = amt(py_v)
            cp = wsn.cell(r, 4, vp)
            if vp is not None:
                cp.number_format = nfmt; cp.alignment = right
            if boldrow:
                cp.font = bold
            if top_border:
                cp.border = top
        return r + 1

    def _write_inventory_excel(n, r):
        a = n['inventory']
        r = _inv_excel_head(n, r)
        for rr in a['rows']:
            r = _inv_excel_row(r, rr['label'], rr['cy'], rr['py'])
        r = _inv_excel_row(r, "Total", a['total_cy'], a['total_py'], boldrow=True, indent=0, top_border=True)
        return r + 1

    def _write_cost_excel(n, r):
        a = n['cost_material']
        r = _inv_excel_head(n, r)
        for mt in a['materials']:
            r = _inv_excel_row(r, mt['label'], None, None, boldrow=True, indent=0)
            r = _inv_excel_row(r, "Opening stock", mt['opening_cy'], mt['opening_py'])
            r = _inv_excel_row(r, "Purchases", mt['purchases_cy'], mt['purchases_py'])
            r = _inv_excel_row(r, "Less: Closing stock", mt['closing_cy'], mt['closing_py'])
            r = _inv_excel_row(r, "Total", mt['total_cy'], mt['total_py'], boldrow=True, indent=1)
        if a['mfg']:
            r = _inv_excel_row(r, "Other Manufacturing Expenses", None, None, boldrow=True, indent=0)
            for rr in a['mfg']:
                lbl = rr['label'] + (f" ({rr['group']})" if rr.get('group') else "")
                r = _inv_excel_row(r, lbl, rr['cy'], rr['py'])
            r = _inv_excel_row(r, "Total", a['mfg_total_cy'], a['mfg_total_py'], boldrow=True, indent=1)
        r = _inv_excel_row(r, "Total", a['grand_cy'], a['grand_py'], boldrow=True, indent=0, top_border=True)
        for fn in a.get('footnotes', []):
            wsn.cell(r, 1, "• " + str(fn)).font = base; r += 1
        return r + 1

    def _write_change_excel(n, r):
        a = n['change_inv']
        r = _inv_excel_head(n, r)
        r = _inv_excel_row(r, "Opening Inventories", None, None, boldrow=True, indent=0)
        for rr in a['opening']:
            r = _inv_excel_row(r, rr['label'], rr['cy'], rr['py'])
        r = _inv_excel_row(r, "Less: Closing Inventories", None, None, boldrow=True, indent=0)
        for rr in a['closing']:
            r = _inv_excel_row(r, rr['label'], rr['cy'], rr['py'])
        r = _inv_excel_row(r, "Total", a['total_cy'], a['total_py'], boldrow=True, indent=0, top_border=True)
        for fn in a.get('footnotes', []):
            wsn.cell(r, 1, "• " + str(fn)).font = base; r += 1
        return r + 1

    def _write_fa_excel(n, r):
        a = n['fixed_assets']
        blocks = [a['cwip'], a['intan']]
        present = [b for b in blocks if b.get('present')]
        disclosed = [b for b in blocks if b.get('disclose')]
        if not present and not disclosed:
            return r
        for b in present:
            r = _inv_excel_row(r, f"{b['roman']} {b['label']}", b['net_cy'], b['net_py'],
                               boldrow=True, indent=0)
        if present:
            r += 1
        for b in disclosed:
            wsn.cell(r, 1, f"{b['roman']} {b['label']}").font = bold; r += 1
            r = _inv_excel_row(r, "Opening Balance", b['opening_cy'], b['opening_py'])
            r = _inv_excel_row(r, "Add: Addition during the year",
                               b['addition_cy'], b['addition_py'])
            r = _inv_excel_row(r, "Less: Capitalised during the year",
                               b['capitalised_cy'], b['capitalised_py'])
            r = _inv_excel_row(r, "Closing Balance", b['closing_cy'], b['closing_py'],
                               boldrow=True, top_border=True)
            r += 1
        for fn in a.get('footnotes', []):
            wsn.cell(r, 1, "• " + str(fn)).font = base; r += 1
        return r + 1

    for n in stmts['notes']:
        if n.get('far'):
            r = _write_far_excel(n, r)
            if n.get('fixed_assets'):
                r = _write_fa_excel(n, r)
            continue
        if n.get('partners'):
            r = _write_partners_excel(n, r)
            continue
        if n.get('owners_capital'):
            r = _write_owners_excel(n, r)
            continue
        if n.get('inventory'):
            r = _write_inventory_excel(n, r)
            continue
        if n.get('cost_material'):
            r = _write_cost_excel(n, r)
            continue
        if n.get('change_inv'):
            r = _write_change_excel(n, r)
            continue
        wsn.cell(r, 1, f"{n['num']} {n['title']}").font = bold; note_rows[n['num']] = r
        hc = wsn.cell(r, 3, cyh); hc.font = bold; hc.fill = shade
        if has_py:
            wsn.cell(r, 4, pyh).font = bold
        r += 1
        def _wrow(label, cy_v, py_v, indent):
            nonlocal r
            wsn.cell(r, 1, ("    " * indent) + str(label)).font = base
            v = amt(cy_v)
            c = wsn.cell(r, 3, v); c.fill = shade
            if v is not None:
                c.number_format = nfmt; c.alignment = right
            if has_py:
                vp = amt(py_v)
                cp = wsn.cell(r, 4, vp)
                if vp is not None:
                    cp.number_format = nfmt; cp.alignment = right
            r += 1

        for ln in n['lines']:
            if ln.get('subs'):
                _wrow(ln['label'], None, None, 1)          # note-line header (no amount)
                for sb in ln['subs']:
                    _wrow("– " + str(sb['label']), sb.get('cy'), sb.get('py'), 2)
            else:
                _wrow(ln['label'], ln.get('cy'), ln.get('py'), 1)
        tc = wsn.cell(r, 1, "Total"); tc.font = bold
        v = amt(n.get('cy'))
        c = wsn.cell(r, 3, v); c.font = bold; c.fill = shade; c.border = top
        if v is not None:
            c.number_format = nfmt; c.alignment = right
        if has_py:
            vp = amt(n.get('py'))
            cp = wsn.cell(r, 4, vp); cp.font = bold; cp.border = top
            if vp is not None:
                cp.number_format = nfmt; cp.alignment = right
        r += 2
        if n.get('ageing'):
            a = n['ageing']
            wsn.cell(r, 1, f"{n['num']}.1  Trade Receivables Ageing Schedule").font = bold
            hc = wsn.cell(r, 3, cyh); hc.font = bold; hc.fill = shade
            if has_py:
                wsn.cell(r, 4, pyh).font = bold
            r += 1
            for sec in a.get('sections', []):
                wsn.cell(r, 1, sec['title']).font = bold; r += 1
                for rr in sec['rows']:
                    _wrow(rr['label'], rr['cy'], rr['py'], 1)
                _wrow("", sec['sub_cy'], sec['sub_py'], 1)
            for rr in a.get('extras', []):
                _wrow(rr['label'], rr['cy'], rr['py'], 1)
            tc = wsn.cell(r, 1, "Total"); tc.font = bold
            v = amt(a.get('total_cy'))
            c = wsn.cell(r, 3, v); c.font = bold; c.fill = shade; c.border = top
            if v is not None:
                c.number_format = nfmt; c.alignment = right
            if has_py:
                vp = amt(a.get('total_py'))
                cp = wsn.cell(r, 4, vp); cp.font = bold; cp.border = top
                if vp is not None:
                    cp.number_format = nfmt; cp.alignment = right
            r += 1
            for fn in a.get('footnotes', []):
                wsn.cell(r, 1, "• " + str(fn)).font = base; r += 1
            r += 1
        if n.get('fixed_assets'):
            r = _write_fa_excel(n, r)
    wsn.column_dimensions['A'].width = 48
    wsn.column_dimensions['C'].width = 16
    wsn.column_dimensions['D'].width = 16

    # Statements last (note rows are now known) — adds forward links on the Note
    # column and records each face's row for the note-title back-links.
    write_stmt(ws1, f"Balance Sheet as at {cyh}", stmts['bs'])
    write_stmt(ws2, f"Statement of Profit and Loss for the year ended {cyh}", stmts['pl'])
    for n in stmts['notes']:                # back-link: note title -> BS / P&L line
        tgt = face_stmt_ref.get(n['title'])
        rr = note_rows.get(n['num'])
        if tgt and rr:
            c = wsn.cell(rr, 1)
            c.hyperlink = f"#'{tgt[0]}'!A{tgt[1]}"
            c.font = link_bold

    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()
