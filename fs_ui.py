"""Financials (NCE) UI — the whole NCE division (Master Data, Grouping, FAR,
Check, Disclosures, Statements). Split out of streamlit_app.py so the main file
stays small and this logic is separate.

Call fs_ui.render_nce(company_name) inside the NCE division tab."""
import pandas as pd
import streamlit as st

import fs_engine
import fs_grouping
import fs_reports
import profile_engine


def _export_sig(stmts):
    """A stable content fingerprint of the statements. download_button serves the
    LAST-rendered bytes; if `data` is rebuilt (new object) every rerun, the media
    id churns and a click can fetch a stale/empty payload — so we cache the bytes
    on this signature and only rebuild when the figures/look actually change."""
    import hashlib, json
    m = stmts['meta']
    head = [m.get('company'), m.get('cy_label'), m.get('py_label'), m.get('theme_name'),
            m.get('border_name'), m.get('round_off'), m.get('two_decimals'),
            m.get('has_py'), m.get('font'), m.get('show_notes_col')]

    def amts(rows):
        return [(r.get('label'), r.get('note'), r.get('cy'), r.get('py')) for r in rows]
    blob = json.dumps([head, amts(stmts['bs']), amts(stmts['pl']),
                       [(n.get('num'), n.get('title'), n.get('cy'), n.get('py'))
                        for n in stmts['notes']]], default=str, sort_keys=True)
    return hashlib.md5(blob.encode('utf-8')).hexdigest()


@st.cache_data(show_spinner=False, max_entries=8)
def _build_excel_cached(sig, _stmts):
    return fs_reports.build_excel(_stmts)


@st.cache_data(show_spinner=False, max_entries=8)
def _build_pdf_cached(sig, _stmts):
    return fs_reports.build_pdf(_stmts)


def render_nce(company_name, active_fy=None):
    # NCE follows the header's active tax year — keep the FY pointers + the
    # period (CY/PY year-ended dates) in sync with the selected tax year.
    if company_name and active_fy:
        try:
            _a = int(str(active_fy)[:4])            # '2025-26' -> 2025
        except Exception:
            _a = None
        if _a is not None:
            if fs_engine.get_current_fy(company_name) != active_fy:
                fs_engine.set_current_fy(company_name, active_fy)
                fs_engine.set_previous_fy(company_name, f"{_a - 1}-{str(_a)[-2:]}")
            # Indian FY ends 31 March: FY 25-26 -> CY ended 31-03-2026, PY 31-03-2025.
            _ent = fs_engine.load_entity(company_name)
            _cy_y = (_ent.get("period", {}).get("cy") or {}).get("year")
            _py_y = (_ent.get("period", {}).get("py") or {}).get("year")
            if _cy_y != _a + 1 or _py_y != _a:
                _ent["period"]["cy"] = {"date": 31, "month": "March", "year": _a + 1}
                _ent["period"]["py"] = {"date": 31, "month": "March", "year": _a}
                fs_engine.save_entity(company_name, _ent)
                # reset the two date widgets so they reload the derived dates
                for _k in ("fs_m_cyend", "fs_m_pyend"):
                    st.session_state.pop(_k, None)
    st.markdown("""
    <div class="card">
        <div class="card-title">🧾 Financial Statements — NCE format</div>
        <div class="card-desc">
            Map each trial-balance ledger to its Face / Note / Sub-Note grouping.
            Predefined defaults are applied automatically — review and adjust the
            exceptions. Saved per company and carried forward to next year.
        </div>
    </div>
    """, unsafe_allow_html=True)

    if not company_name:
        st.markdown('<div class="status-error">⚠️ Select a company first.</div>',
                    unsafe_allow_html=True)
    else:
        # Entity master, extraction and roll-over now live in the 📇 Master Data inner tab.
        # Flash messages (extraction / save / roll-over) show regardless of readiness.
        _flash_fs = st.session_state.pop("flash_fs", None)
        if _flash_fs:
            getattr(st, _flash_fs[0])(_flash_fs[1])

        # 🔄 Sync (top bar) on the NCE page routes here: re-pull the year-end master.
        _open_master = st.session_state.pop("fs_open_master_extract", False)
        if _open_master:
            st.info("🔄 **Sync** → re-pull the year-end master in "
                    "**📇 Master Data → 📅 Year & master extraction** (opened below).")

        # ── Load working mapping into session (rebuild per company + year) ─────
        _fs_ready = fs_engine.tb_available(company_name)
        _fs_key = f"{company_name}|{fs_engine.get_current_fy(company_name)}"
        if _fs_ready and st.session_state.get("fs_work_company") != _fs_key:
            etype = fs_engine.grouping_entity_type(company_name)
            st.session_state["fs_work"] = fs_engine.build_working_mapping(company_name, etype)
            st.session_state["fs_work_company"] = _fs_key
            st.session_state["fs_dirty"] = False
            # reset Step-2 widgets so stock/adjustments reload for the new company/year
            for _k in ("fs_stock_editor", "fs_adj_editor", "fs_far_editor"):
                st.session_state.pop(_k, None)

        work = st.session_state.get("fs_work", {})
        # Face dropdown options — hides 'Reserves and surplus' unless the entity
        # is an LLP (proprietor/firm carry it on the capital account instead).
        _elabel = fs_engine.entity_type_label(company_name) if company_name else ""
        _face_opts = fs_grouping.face_list_for(_elabel)

        # The whole editor runs inside a fragment so filter/dropdown/selection
        # interactions rerun ONLY this block, not all 7 tabs (big speed-up).
        @st.fragment
        def _fs_editor():
            work = st.session_state["fs_work"]
            n_total = len(work)
            n_unmapped = sum(1 for v in work.values() if v.get('face') == 'Not Mapped')

            def _fmt_amt(x):
                """Indian-grouped amount, no decimals (e.g. -12,34,567)."""
                try:
                    x = float(x)
                except (TypeError, ValueError):
                    return ""
                neg = x < 0
                ip = str(int(abs(round(x))))
                if len(ip) > 3:
                    last3, rest, groups = ip[-3:], ip[:-3], []
                    while len(rest) > 2:
                        groups.append(rest[-2:]); rest = rest[:-2]
                    if rest:
                        groups.append(rest)
                    groups.reverse()
                    ip = ",".join(groups) + "," + last3
                return ("-" if neg else "") + ip

            # ── Balance check + Step 2 (stock & adjustments) ──────────────────
            aux = fs_engine.load_aux(company_name)
            rep = fs_reports.compute(work, aux)
            _ok = rep['balanced']
            _strip = ("✅ Balance check OK" if _ok else
                      f"⚠️ Out of balance by {_fmt_amt(rep['difference'])} — "
                      "check stock / adjustments (Step 2)")
            _unm = (f" &nbsp;·&nbsp; ⚠️ unmapped {_fmt_amt(rep['unmapped_total'])}"
                    if rep['has_unmapped'] else "")
            _grouped = ('✅ all grouped' if n_unmapped == 0
                        else f'⚠️ {n_unmapped} not grouped')

            # Inter-branch check: net of all "Branch / Divisions" ledgers should be
            # 0 after consolidation (each branch's inter-branch account cancels its
            # counterpart). If not, the number is shown in RED so the CA can fix the
            # mismatch before finalising. Only shown when such ledgers exist.
            _bdiv_ledgers = [v for v in work.values()
                             if 'branch' in str(v.get('primary_group', '')).lower()
                             and 'division' in str(v.get('primary_group', '')).lower()]
            _bdiv = ""
            if _bdiv_ledgers:
                _bnet = sum(float(v.get('closing', 0.0) or 0.0) for v in _bdiv_ledgers)
                if round(_bnet, 2) == 0:
                    _bdiv = (" &nbsp;|&nbsp; <span style='color:#1b6b34'>"
                             "✅ Branch/Division net 0</span>")
                else:
                    _bdiv = (" &nbsp;|&nbsp; <span style='color:#b3261e;font-weight:700'>"
                             f"⚠️ Branch/Division net {_fmt_amt(_bnet)} (should be 0)</span>")
            st.markdown(
                f"<div style='background:{'#e7f6ec' if _ok else '#fdecea'};"
                f"color:{'#1b6b34' if _ok else '#b3261e'};padding:3px 10px;border-radius:6px;"
                f"font-weight:600;font-size:13px;'>"
                f"<span style='color:#333'><b>{n_total} ledgers</b> &nbsp;|&nbsp; {_grouped}</span>"
                f" &nbsp;|&nbsp; {_strip}{_bdiv}"
                f"<span style='float:right;color:#333;font-weight:500'>Profit for the year: "
                f"<b>{_fmt_amt(rep['profit'])}</b>{_unm}</span></div>",
                unsafe_allow_html=True)

            # Make the "not grouped" warning actionable — jump straight to the
            # ungrouped ledgers in the table below so the CA can select + map them.
            if n_unmapped:
                if st.button(f"👉 Show the {n_unmapped} ungrouped ledger(s) to map them",
                             key="fs_show_unmapped"):
                    st.session_state["fs_f_face"] = "⚠️ Not Mapped"
                    st.session_state["fs_f_prim"] = "All"
                    st.session_state["fs_f_par"] = "All"
                    st.session_state["fs_f_note"] = "All"
                    st.rerun(scope="fragment")

            with st.expander("📦 Step 2 — Stock & manual adjustments"):
                op_default = (abs(float(aux['opening_stock']))
                              or fs_engine.default_opening_stock(company_name))
                # Compact, Excel-style cell — type the figure straight into the grid.
                stock_df = pd.DataFrame([{
                    "Opening stock (₹)": float(op_default),
                    "Closing stock (₹)": abs(float(aux['closing_stock'])),
                }])
                edited_stock = st.data_editor(
                    stock_df, key="fs_stock_editor", width="content",
                    hide_index=True, num_rows="fixed",
                    column_config={
                        "Opening stock (₹)": st.column_config.NumberColumn(
                            format="%.2f", min_value=0.0,
                            help="Defaults to last year's closing stock."),
                        "Closing stock (₹)": st.column_config.NumberColumn(
                            format="%.2f", min_value=0.0,
                            help="Goes to Inventories on the Balance Sheet."),
                    })
                _srow = edited_stock.to_dict('records')[0] if len(edited_stock) else {}
                op = float(_srow.get("Opening stock (₹)") or 0.0)
                cl = float(_srow.get("Closing stock (₹)") or 0.0)
                st.caption("Closing stock → Inventories (Balance Sheet). "
                           "Opening − Closing → Changes in inventories (P&L). "
                           "Double-click a cell to type the figure directly.")
                st.markdown("**Manual adjustment rows** &nbsp;<span style='font-size:12px;color:#888;'>"
                            "(plug reconciling items — amount is signed: debit −, credit +)</span>",
                            unsafe_allow_html=True)
                adj_df = pd.DataFrame(aux.get('adjustments') or [],
                                      columns=['ledger', 'closing', 'face', 'note', 'subnote'])
                edited_adj = st.data_editor(
                    adj_df, num_rows="dynamic", key="fs_adj_editor", width="stretch",
                    column_config={
                        'ledger': st.column_config.TextColumn("Particulars"),
                        'closing': st.column_config.NumberColumn("Amount (Dr − / Cr +)", format="%.2f"),
                        'face': st.column_config.SelectboxColumn("Face", options=_face_opts),
                        'note': st.column_config.TextColumn("Note"),
                        'subnote': st.column_config.TextColumn("Sub-Note"),
                    })
                if st.button("💾 Save stock & adjustments", key="fs_save_aux"):
                    rows_out = []
                    for r in edited_adj.to_dict('records'):
                        led = str(r.get('ledger') or '').strip()
                        amt = r.get('closing')
                        if not led and not amt:
                            continue
                        rows_out.append({
                            'ledger': led, 'closing': float(amt or 0.0),
                            'face': r.get('face') or 'Not Mapped',
                            'note': r.get('note') or '', 'subnote': r.get('subnote') or '',
                        })
                    fs_engine.save_aux(company_name, None, {
                        'opening_stock': float(op), 'closing_stock': float(cl),
                        'adjustments': rows_out})
                    st.toast("Stock & adjustments saved", icon="✅")
                    st.rerun(scope="fragment")

            st.markdown("#### 🎯 Map ledgers")
            # Compact dropdown text across the whole grouping editor.
            st.markdown("<style>div[data-baseweb='select']>div{font-size:11px;min-height:30px;}"
                        "ul[role='listbox'] li,div[data-baseweb='popover'] li{font-size:11px;}</style>",
                        unsafe_allow_html=True)

            # Filters: Tally Primary & Parent groups + Face + Note (Note cascades from Face)
            prim_vals = sorted({str(v.get('primary_group', '')) for v in work.values()
                                if str(v.get('primary_group', '')).strip() not in ('', 'nan')})
            par_vals = sorted({str(v.get('parent', '')) for v in work.values()
                               if str(v.get('parent', '')).strip() not in ('', 'nan')})
            # Bordered box = the filter options; the bulk change & apply strip is below it.
            with st.container(border=True):
                fcl, fc1, fc2, fc3, fc4 = st.columns([0.6, 3, 3, 3, 3],
                                                     vertical_alignment="bottom")
                fcl.markdown("<div style='font-size:12px;font-weight:700;color:#6b7280;"
                             "padding-bottom:9px;'>🔎 Filter&nbsp;by</div>",
                             unsafe_allow_html=True)
                f_prim = fc1.selectbox("Primary Group (Tally)", ["All"] + prim_vals, key="fs_f_prim")
                f_par = fc2.selectbox("Parent Group (Tally)", ["All"] + par_vals, key="fs_f_par")
                f_face = fc3.selectbox("Face Grouping", ["All", "⚠️ Not Mapped"] + _face_opts,
                                       key="fs_f_face")
                note_filter_opts = (["All"] + fs_grouping.FACE_NOTE_VOCAB.get(f_face, [])
                                    if f_face in fs_grouping.FACE_LIST
                                    else ["All"] + fs_grouping.ALL_NOTES)
                if st.session_state.get("fs_f_note") not in note_filter_opts:
                    st.session_state["fs_f_note"] = "All"
                f_note = fc4.selectbox("Note Grouping", note_filter_opts, key="fs_f_note")
                py_edit = st.checkbox("✏️ Edit previous-year grouping (regrouping)", key="fs_py_edit")
            if py_edit:
                st.markdown("<div style='background:#fff3cd;color:#7a5b00;padding:4px 10px;"
                            "border-radius:6px;font-size:12px;margin:2px 0 4px 0;'>"
                            "⚠️ PREVIOUS-YEAR edit mode — Apply changes the PY grouping, not current."
                            "</div>", unsafe_allow_html=True)

            def _fs_match(v):
                if f_prim != "All" and v.get('primary_group', '') != f_prim:
                    return False
                if f_par != "All" and v.get('parent', '') != f_par:
                    return False
                if f_face == "⚠️ Not Mapped":
                    if v.get('face') != 'Not Mapped':
                        return False
                elif f_face != "All" and v.get('face') != f_face:
                    return False
                if f_note != "All" and v.get('note', '') != f_note:
                    return False
                return True

            view_ledgers = [l for l, v in work.items() if _fs_match(v)]
            cap = 400
            shown = view_ledgers[:cap]

            # When the filter changes, pre-set the assign-strip Face to the face the
            # filtered ledgers are ALREADY grouped under (the most common / top one),
            # so the Note cascades to match — easy to review and tweak.
            filt_sig = (f_prim, f_par, f_face, f_note)
            if st.session_state.get("fs_last_filter_sig") != filt_sig:
                st.session_state["fs_last_filter_sig"] = filt_sig
                if view_ledgers:
                    from collections import Counter
                    common = Counter(work[l].get('face', '')
                                     for l in view_ledgers).most_common(1)[0][0]
                    if common in _face_opts:
                        st.session_state["fs_assign_face"] = common

            view_df = pd.DataFrame([{
                'Ledger': l,
                'Closing': _fmt_amt(work[l].get('closing', 0.0)),
                'Face': work[l].get('face', ''),
                'Note': work[l].get('note', ''),
                'Sub-Note': work[l].get('subnote', ''),
                'PY Face': work[l].get('py_face', ''),
                'PY Note': work[l].get('py_note', ''),
                'PY Sub-Note': work[l].get('py_subnote', ''),
                'PY Closing': _fmt_amt(work[l].get('py_closing', 0.0)),
            } for l in shown])
            tbl_key = f"fs_table_{f_prim}_{f_par}_{f_face}_{f_note}"

            # Assign controls in a compact horizontal strip -> table below is full width.
            ac1, ac2, ac3, ac4, ac5, ac6 = st.columns([3, 3, 3, 2, 1, 1],
                                                       vertical_alignment="bottom")
            sel_face = ac1.selectbox("Face Grouping", _face_opts, key="fs_assign_face")
            sel_note = ac2.selectbox("Note Grouping",
                                     fs_grouping.FACE_NOTE_VOCAB.get(sel_face, []))  # cascades on face
            _l3 = fs_grouping.is_specify_l3(sel_note)
            sel_sub = ac3.text_input("Sub-Note (MANDATORY — shown at note level)" if _l3
                                     else "Sub-Note (optional)", key="fs_assign_sub")
            apply_clicked = ac4.button("✅ Apply to PY" if py_edit else "✅ Apply",
                                       key="fs_apply", width="stretch")
            save_clicked = ac5.button("💾", key="fs_save_map", width="stretch",
                                      type="primary", help="Save mapping")
            reset_clicked = ac6.button("🔄", key="fs_reset", width="stretch",
                                       help="Reset to defaults")

            if apply_clicked:
                sel_rows = (st.session_state.get(tbl_key, {})
                            .get("selection", {}).get("rows", []))
                ledgers = [shown[i] for i in sel_rows if i < len(shown)]
                if _l3 and not (sel_sub or "").strip():
                    st.error("This note is **Specify at Level 3** — the Sub-Note is "
                             "mandatory (it will display at note level).")
                elif ledgers:
                    for l in ledgers:
                        if py_edit:
                            work[l]['py_face'] = sel_face
                            work[l]['py_note'] = sel_note or ''
                            work[l]['py_subnote'] = sel_sub or ''
                        else:
                            work[l]['face'] = sel_face
                            work[l]['note'] = sel_note or ''
                            work[l]['subnote'] = sel_sub or ''
                    st.session_state["fs_work"] = work
                    st.session_state["fs_dirty"] = True
                    st.session_state.pop(tbl_key, None)   # clear row checkboxes after apply
                    st.toast(f"Applied to {len(ledgers)} ledger(s)"
                             + (" (PY)" if py_edit else ""), icon="✏️")
                    st.rerun(scope="fragment")
                else:
                    st.warning("Tick row(s) in the table first.")
            if save_clicked:
                fs_engine.save_grouping(company_name, {
                    l: {'face': v['face'], 'note': v['note'], 'subnote': v['subnote']}
                    for l, v in work.items()})
                fs_engine.save_grouping_py(company_name, {
                    l: {'face': v['py_face'], 'note': v['py_note'], 'subnote': v['py_subnote']}
                    for l, v in work.items() if v.get('py_face')})
                st.session_state["fs_dirty"] = False
                st.toast("Mapping saved", icon="✅")
            if reset_clicked:
                etype = fs_engine.grouping_entity_type(company_name)
                fs_engine.save_grouping(company_name, {})
                st.session_state["fs_work"] = fs_engine.build_working_mapping(company_name, etype)
                st.session_state["fs_dirty"] = False
                st.session_state.pop(tbl_key, None)
                st.toast("Reset to defaults", icon="↩️")
                st.rerun(scope="fragment")
            if st.session_state.get("fs_dirty"):
                st.caption("● Unsaved changes — click **💾 Save**.")

            # ── Full-width table with row checkboxes (tick rows to select) ─────
            st.markdown(f"**📋 Current grouping** &nbsp;<span style='font-size:12px;color:#888;'>"
                        f"({len(view_ledgers)} shown — tick rows to select)</span>",
                        unsafe_allow_html=True)
            st.dataframe(
                view_df,
                on_select="rerun",
                selection_mode="multi-row",
                key=tbl_key,
                hide_index=True,
                width="stretch",
                height=min(len(view_df) * 30 + 36, 600),
                column_config={
                    'Ledger': st.column_config.TextColumn("Ledger", width="medium"),
                    'Closing': st.column_config.TextColumn("Closing", width="small", alignment="right"),
                    'PY Closing': st.column_config.TextColumn("PY Closing", width="small", alignment="right"),
                },
            )
            total_val = sum(work[l].get('closing', 0.0) for l in view_ledgers)
            st.markdown(
                f"**Total (closing) of {len(view_ledgers)} ledger(s): "
                f"{_fmt_amt(total_val)}**")
            if len(view_ledgers) > cap:
                st.caption(f"(Table shows first {cap}; total above covers all {len(view_ledgers)}.)")

        # ── Statements viewer (BS / P&L / Notes) ──────────────────────────────
        # IMPORTANT: the toolbar (with the Excel/PDF download buttons) MUST live in
        # the main script flow, NOT inside the @st.fragment below — a download_button
        # rendered inside a fragment never serves the file to the browser (the click
        # is a no-op). So we build the statements + exports here and pass them in.
        def _fs_toolbar():
            etype = fs_engine.grouping_entity_type(company_name)
            try:
                # live in-memory current-year mapping, so applied edits show immediately
                stmts = fs_reports.statements(company_name, etype,
                                              work_override=st.session_state.get("fs_work"))
            except Exception as e:
                st.error(f"Could not build statements: {e}")
                return None
            meta = stmts['meta']

            # Live look-preview overrides (set by the 🎨 Look popover) — applied BEFORE
            # the toolbar so the on-screen statements AND the Excel/PDF exports all use
            # the chosen theme/border. Not persisted: Save in Master Data ▸ Presentation.
            _pk = f"{company_name}|{meta.get('cy_label') or 'CY'}"
            _thn = st.session_state.get(f"fs_prev_theme_{_pk}", meta['theme_name'])
            _bdn = st.session_state.get(f"fs_prev_border_{_pk}", meta['border_name'])
            if _thn in fs_grouping.THEME_LIST:
                meta['theme'] = fs_grouping.theme(_thn); meta['theme_name'] = _thn
            if _bdn in fs_grouping.BORDER_LIST:
                meta['border'] = fs_grouping.border(_bdn); meta['border_name'] = _bdn

            # One-row toolbar: Refresh | status strip | Look | Excel | PDF
            tb1, tb2, tbL, tb3, tb4 = st.columns([1, 2.7, 0.9, 0.9, 1.1],
                                                 vertical_alignment="center")
            if tb1.button("🔄 Refresh", key="fs_refresh_stmt", width="stretch",
                          help="Recompute after changing grouping, stock or adjustments "
                               "(reflects applied grouping + saved stock/adjustments)"):
                st.toast("Financials refreshed", icon="🔄")
            with tbL.popover("🎨 Look", use_container_width=True):
                st.selectbox("Theme", fs_grouping.THEME_LIST,
                             index=fs_grouping.THEME_LIST.index(_thn)
                             if _thn in fs_grouping.THEME_LIST else 0,
                             key=f"fs_prev_theme_{_pk}")
                st.selectbox("Border", fs_grouping.BORDER_LIST,
                             index=fs_grouping.BORDER_LIST.index(_bdn)
                             if _bdn in fs_grouping.BORDER_LIST else 0,
                             key=f"fs_prev_border_{_pk}")
                st.caption("Live preview only — Save in **Master Data ▸ Presentation** to keep.")
            _bal = ("<span style='color:#1b6b34'>✅ balanced</span>" if meta['balanced'] else
                    f"<span style='color:#b3261e'>⚠️ out of balance "
                    f"{fs_reports.fmt_amt(meta['difference'])}</span>")
            _prof = ("profit already in surplus" if meta.get('profit_in_surplus')
                     else f"profit → {meta.get('profit_face')}")
            _cap = (f"<b>{meta['entity_name']}</b> · {meta.get('entity_type_label') or meta['entity_type']}"
                    f" · FY ended {meta['cy_header']} · {_bal}"
                    f" · <span title='Profit treatment'>{_prof}</span>")
            tb2.markdown(f"<div style='font-size:12.5px;color:#444;line-height:1.3'>{_cap}</div>",
                         unsafe_allow_html=True)
            # Build once, cache on a content signature → stable bytes.
            _sig = _export_sig(stmts)
            try:
                _xlsx = _build_excel_cached(_sig, stmts)
            except Exception as e:
                _xlsx = None
                tb3.error("Excel ✗")
                st.caption(f"Excel build failed: {e}")
            try:
                _pdf = _build_pdf_cached(_sig, stmts)
            except Exception as e:
                _pdf = None
                tb4.error("PDF ✗")
                st.caption(f"PDF build failed: {e}")
            _fname = f"{company_name}_Financials_{meta['cy_label'] or 'CY'}"
            if _xlsx is not None:
                tb3.download_button(
                    "⬇ Excel", data=_xlsx, file_name=f"{_fname}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    key="fs_dl_xlsx", width="stretch")
            if _pdf is not None:
                tb4.download_button(
                    "⬇ PDF", data=_pdf, file_name=f"{_fname}.pdf",
                    mime="application/pdf", key="fs_dl_pdf", width="stretch",
                    help="Real multi-page PDF with page breaks & borders.")
            if meta['has_unmapped']:
                st.caption(f"⚠️ Unmapped balances total {fs_reports.fmt_amt(meta['unmapped_total'])} "
                           "are excluded — group them in the Grouping tab.")
            return stmts

        @st.fragment
        def _fs_viewer(stmts):
            meta = stmts['meta']
            st.markdown(fs_reports.themed_css(meta), unsafe_allow_html=True)
            cyh = meta['cy_header']

            @st.dialog("Regroup ledger")
            def _regroup_dialog(led):
                w = st.session_state.get("fs_work", {})
                v = w.get(led)
                if not v:
                    st.warning("Ledger not found — refresh.")
                    return
                if st.session_state.get("fs_rg_led") != led:
                    st.session_state["fs_rg_led"] = led
                    st.session_state["fs_rg_face"] = (v.get('face') if v.get('face') in
                                                      _face_opts else _face_opts[0])
                    st.session_state.pop("fs_rg_note", None)
                    st.session_state["fs_rg_sub"] = v.get('subnote', '')
                st.markdown(f"**{led}** &nbsp;<span style='color:#888;font-size:12px'>"
                            f"(currently {v.get('face')} ▸ {v.get('note')})</span>",
                            unsafe_allow_html=True)
                f = st.selectbox("Face grouping", _face_opts, key="fs_rg_face")
                nopts = fs_grouping.FACE_NOTE_VOCAB.get(f, [])
                if st.session_state.get("fs_rg_note") not in nopts:
                    st.session_state["fs_rg_note"] = (v.get('note') if v.get('note') in nopts
                                                      else (nopts[0] if nopts else ""))
                n = st.selectbox("Note grouping", nopts, key="fs_rg_note")
                _l3d = fs_grouping.is_specify_l3(n)
                sub = st.text_input("Sub-Note (MANDATORY — shown at note level)" if _l3d
                                    else "Sub-Note (optional)", key="fs_rg_sub")
                if st.button("✅ Apply & save", type="primary", width="stretch"):
                    if _l3d and not (sub or "").strip():
                        st.error("This note is **Specify at Level 3** — enter the Sub-Note.")
                        return
                    w[led]['face'] = f
                    w[led]['note'] = n or ''
                    w[led]['subnote'] = sub or ''
                    st.session_state["fs_work"] = w
                    fs_engine.save_grouping(company_name, {
                        l: {'face': x['face'], 'note': x['note'], 'subnote': x['subnote']}
                        for l, x in w.items()})
                    st.session_state["fs_dirty"] = False
                    st.session_state.pop("fs_note_annex", None)
                    st.session_state.pop("fs_annex_opened_for", None)
                    st.toast(f"Regrouped {led}", icon="✏️")
                    st.rerun()

            sv1, sv2, sv3, sv4 = st.tabs(["🧮 Balance Sheet", "📈 Statement of P&L",
                                          "🗒 Policies (Notes 1–2)", "🔢 Notes"])
            with sv1:
                st.markdown(fs_reports.statement_html(f"Balance Sheet as at {cyh}",
                                                      stmts['bs'], meta), unsafe_allow_html=True)
                st.markdown(fs_reports.signature_html(meta), unsafe_allow_html=True)
            with sv2:
                st.markdown(fs_reports.statement_html(
                    f"Statement of Profit and Loss for the year ended {cyh}",
                    stmts['pl'], meta), unsafe_allow_html=True)
                st.markdown(fs_reports.signature_html(meta), unsafe_allow_html=True)
            with sv3:
                st.markdown(fs_reports.notes_header_html(meta), unsafe_allow_html=True)
                _pol_html = fs_reports.policies_html(meta, stmts.get('policies'))
                if _pol_html:
                    st.markdown(_pol_html, unsafe_allow_html=True)
                else:
                    st.info("No disclosures yet — fill them in the **📝 Disclosures** tab.")
            with sv4:
                # apply a pending "edit this note" jump BEFORE the widgets are created
                _req = st.session_state.pop("fs_notes_edit_req", None)
                if _req:
                    st.session_state["fs_notes_edit"] = True
                    st.session_state["fs_note_stmt"] = _req["stmt"]
                    st.session_state["fs_note_face"] = _req["face"]
                    st.session_state["fs_note_search"] = ""
                    st.session_state["fs_note_filtsig"] = None
                    st.session_state.pop("fs_note_annex", None)
                    st.session_state.pop("fs_annex_opened_for", None)
                nc1, nc2 = st.columns(2)
                show_led = nc1.checkbox("🔍 Show ledger details", key="fs_notes_showled",
                                        help="List the ledgers making up each note (annexure).")
                edit_grp = nc2.checkbox("✏️ Edit grouping", key="fs_notes_edit",
                                        help="Click a ledger row (or a note's ✏️) to change grouping — saved instantly.")
                if edit_grp:
                    st.caption("Filter to the note you're reviewing, then click a ledger row to "
                               "change its Face / Note / Sub-Note — saved instantly.")
                    work = st.session_state.get("fs_work", {})
                    full = [{'Ledger': l, 'Face': v.get('face', ''), 'Note': v.get('note', ''),
                             'Sub-Note': v.get('subnote', ''), 'Closing': v.get('closing', 0.0),
                             '_sec': fs_grouping.face_section(v.get('face', ''))}
                            for l, v in work.items()]
                    fdf = pd.DataFrame(full, columns=['Ledger', 'Face', 'Note', 'Sub-Note',
                                                      'Closing', '_sec'])
                    ef1, ef2, ef3 = st.columns([1, 2, 2])
                    stmt = ef1.selectbox("Statement", ["All", "Balance Sheet", "Profit & Loss"],
                                         key="fs_note_stmt")
                    _BS, _PL = {'asset', 'liability', 'equity'}, {'income', 'expense'}
                    sdf = (fdf[fdf['_sec'].isin(_BS)] if stmt == "Balance Sheet"
                           else fdf[fdf['_sec'].isin(_PL)] if stmt == "Profit & Loss" else fdf)
                    face_opts = ["All"] + sorted(x for x in sdf['Face'].unique() if str(x).strip())
                    if st.session_state.get("fs_note_face") not in face_opts:
                        st.session_state["fs_note_face"] = "All"
                    face_f = ef2.selectbox("Face (note head)", face_opts, key="fs_note_face")
                    search = ef3.text_input("Search ledger", key="fs_note_search")
                    view = sdf if face_f == "All" else sdf[sdf['Face'] == face_f]
                    if search.strip():
                        view = view[view['Ledger'].str.contains(search.strip(), case=False, na=False)]
                    # clear stale row-selection whenever the filter changes
                    filt_sig = (stmt, face_f, search.strip())
                    if st.session_state.get("fs_note_filtsig") != filt_sig:
                        st.session_state["fs_note_filtsig"] = filt_sig
                        st.session_state.pop("fs_note_annex", None)
                        st.session_state.pop("fs_annex_opened_for", None)
                    adf = (view.drop(columns=['_sec'])
                           .sort_values(['Face', 'Note', 'Ledger']).reset_index(drop=True))
                    st.caption(f"{len(adf)} ledger(s)")
                    disp = adf.copy()
                    disp['Closing'] = disp['Closing'].map(lambda x: fs_reports.fmt_amt(x))
                    st.dataframe(
                        disp, on_select="rerun", selection_mode="single-row", key="fs_note_annex",
                        hide_index=True, width="stretch", height=min(len(disp) * 30 + 36, 560),
                        column_config={
                            'Ledger': st.column_config.TextColumn("Ledger", width="large"),
                            'Closing': st.column_config.TextColumn("Closing", alignment="right"),
                        })
                    sel = (st.session_state.get("fs_note_annex", {})
                           .get("selection", {}).get("rows", []))
                    if sel and sel[0] < len(adf):
                        led = adf.iloc[sel[0]]['Ledger']
                        if st.session_state.get("fs_annex_opened_for") != led:
                            st.session_state["fs_annex_opened_for"] = led
                            _regroup_dialog(led)
                    else:
                        st.session_state.pop("fs_annex_opened_for", None)
                else:
                    st.markdown(fs_reports.notes_header_html(meta), unsafe_allow_html=True)
                    _hcol = meta['theme']['heading']
                    for n in stmts['notes']:
                        title = (f"<div style='color:{_hcol};font-weight:700;font-size:13px;"
                                 f"margin-top:8px'>{n['num']} {n['title']}</div>")
                        if n.get('ledgers'):
                            tc1, tc2 = st.columns([12, 1], vertical_alignment="center")
                            tc1.markdown(title, unsafe_allow_html=True)
                            if tc2.button("✏️", key=f"fs_ne_{n['num']}",
                                          help=f"Edit grouping for '{n['title']}'"):
                                _sec = fs_grouping.face_section(n['title'])
                                st.session_state["fs_notes_edit_req"] = {
                                    "face": n['title'],
                                    "stmt": ("Balance Sheet" if _sec in ('asset', 'liability', 'equity')
                                             else "Profit & Loss" if _sec in ('income', 'expense')
                                             else "All")}
                                st.rerun()
                        else:
                            st.markdown(title, unsafe_allow_html=True)
                        st.markdown(fs_reports.one_note_html(n, meta, show_ledgers=show_led,
                                                             with_title=False), unsafe_allow_html=True)

        # ── Master Data (compact, sectioned collapsed expanders) ──────────────
        @st.fragment
        def _fs_master():
            import datetime as _dt
            # reset master widgets when the company changes (avoid stale prefill)
            if st.session_state.get("fs_master_company") != company_name:
                for _k in [k for k in list(st.session_state.keys())
                           if k.startswith("fs_m_") or k in
                           ("fs_ext_fy", "fs_sel_cur", "fs_sel_prev", "fs_ro_confirm", "fs_sig_editor")]:
                    st.session_state.pop(_k, None)
                st.session_state["fs_master_company"] = company_name
            ent = fs_engine.load_entity(company_name)
            e, per, aud = ent['entity'], ent['period'], ent['auditor']
            opt, pre, prn, sgn = ent['options'], ent['presentation'], ent['print'], ent['sign']
            months = fs_engine._MONTHS
            MIND, MAXD = _dt.date(1990, 1, 1), _dt.date(2100, 12, 31)

            def _idx(lst, val, d=0):
                return lst.index(val) if val in lst else d

            def _to_date(dd, dy):
                try:
                    mi = months.index(dd.get('month') or 'March') + 1
                except ValueError:
                    mi = 3
                try:
                    return _dt.date(int(dd.get('year') or dy), mi, int(dd.get('date') or 31))
                except Exception:
                    return _dt.date(int(dd.get('year') or dy), mi, 28)

            def _from_date(d):
                return {"date": d.day, "month": months[d.month - 1], "year": d.year}

            # ── Year & master extraction (year driven by the header picker) ────
            with st.expander("📅 Year & master extraction", expanded=bool(_open_master)):
                cur_fy = fs_engine.get_current_fy(company_name)
                prev_fy = fs_engine.get_previous_fy(company_name)
                have = fs_engine.list_master_fys(company_name)
                _is_group = fs_engine.get_is_group(company_name)
                st.caption(f"Current year **{cur_fy or '—'}** · previous **{prev_fy or '—'}** — "
                           f"{'Group concern' if _is_group else 'Single company'}; set in the "
                           "header tax-year picker.")
                if not cur_fy:
                    st.info("Select a tax year in the header first.")
                else:
                    from engines import extract_engine as _ee
                    # Keep the controls in a narrow column so the block stays neat.
                    _wrap = st.columns([5, 4])[0]
                    with _wrap:
                        st.markdown("**Year-end master source**")
                        st.caption("Saved only for NCE — the Ledger Scrutiny master is "
                                   "never changed.")

                        # ── Source 1: reuse the Ledger Scrutiny master (no Tally) ──
                        _has_ls = fs_engine.ls_master_exists(company_name, cur_fy)
                        if _has_ls:
                            st.caption("📥 Reuse the **Ledger Scrutiny** master for "
                                       f"**{cur_fy}** — no Tally needed"
                                       + (", branches summed by ledger + primary group."
                                          if _is_group else "."))
                            if st.button("📥 Use LS data", key="fs_master_from_ls",
                                         width="stretch"):
                                with st.spinner("Building NCE master from Ledger Scrutiny…"):
                                    try:
                                        n = _ee.build_nce_master_from_ls(company_name, cur_fy)
                                        st.session_state["fs_work_company"] = None
                                        st.session_state["flash_fs"] = (
                                            "success", f"✅ FY {cur_fy}: {n} ledgers from Ledger Scrutiny.")
                                    except Exception as ex:
                                        st.session_state["flash_fs"] = ("error", f"❌ {ex}")
                                st.rerun()
                        else:
                            st.caption("📥 Reuse Ledger Scrutiny data — not available "
                                       "(no LS master extracted for this year).")
                            st.button("📥 Use LS data", key="fs_master_from_ls",
                                      width="stretch", disabled=True)

                        st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)

                        # ── Source 2: extract fresh from Tally ────────────────────
                        if not _is_group:
                            st.caption(f"⤓ Or extract fresh — open the **{cur_fy}** company "
                                       "in Tally, then Extract.")
                            if st.button("⤓ Extract from Tally", key="fs_extract_master",
                                         width="stretch"):
                                with st.spinner(f"Extracting FY {cur_fy}…"):
                                    try:
                                        _ee.extract_nce_master(company_name, cur_fy)
                                        st.session_state["fs_work_company"] = None
                                        st.session_state["flash_fs"] = ("success", f"✅ FY {cur_fy} extracted.")
                                    except Exception as ex:
                                        st.session_state["flash_fs"] = ("error", f"❌ {ex}")
                                st.rerun()
                        else:
                            st.caption(f"⤓ Or extract fresh **branch by branch** — open each "
                                       f"branch's **{cur_fy}** company in Tally, type its branch "
                                       "name, Extract; repeat; then Consolidate.")
                            _bn = st.text_input("Branch name", key="fs_master_branch",
                                                placeholder="e.g. Bangalore, Mumbai, HO...")
                            if st.button("⤓ Extract branch", key="fs_extract_master_branch",
                                         width="stretch"):
                                if not _bn.strip():
                                    st.session_state["flash_fs"] = (
                                        "error", "⚠️ Enter the branch name open in Tally.")
                                else:
                                    with st.spinner(f"Extracting branch {_bn.strip()}…"):
                                        try:
                                            _ee.extract_nce_master(company_name, cur_fy, _bn.strip())
                                            st.session_state["flash_fs"] = (
                                                "success", f"✅ Branch '{_bn.strip()}' extracted.")
                                        except Exception as ex:
                                            st.session_state["flash_fs"] = ("error", f"❌ {ex}")
                                st.rerun()
                            _bmasters = _ee.list_nce_branch_masters(company_name, cur_fy)
                            if _bmasters:
                                st.caption(f"Branches extracted: **{', '.join(_bmasters)}**")
                                if st.button("🔗 Consolidate branches → NCE master",
                                             key="fs_consolidate_master", width="stretch"):
                                    with st.spinner("Consolidating branch masters…"):
                                        try:
                                            nb, nl = _ee.consolidate_nce_master(company_name, cur_fy)
                                            st.session_state["fs_work_company"] = None
                                            st.session_state["flash_fs"] = (
                                                "success", f"✅ Consolidated {nb} branch(es) → {nl} ledgers.")
                                        except Exception as ex:
                                            st.session_state["flash_fs"] = ("error", f"❌ {ex}")
                                    st.rerun()

                        st.caption(f"Years with an NCE master: {', '.join(have) if have else 'none yet'}. "
                                   "Grouping carries forward; comparatives load automatically.")

            # ── Entity & period ────────────────────────────────────────────────
            with st.expander("🏢 Entity & period", expanded=False):
                r1 = st.columns([2, 1, 1])
                m_name = r1[0].text_input("Name of entity", e.get('name') or company_name, key="fs_m_name")
                _types = fs_grouping.ENTITY_TYPE_OPTIONS
                m_type = r1[1].selectbox("Type", _types, index=_idx(_types, e.get('type'), 1),
                                         key="fs_m_type")
                m_pan = r1[2].text_input("PAN", e.get('pan', ''), key="fs_m_pan")
                m_addr = st.text_input("Address", e.get('address', ''), key="fs_m_addr")
                r2 = st.columns(3)
                m_llpin = r2[0].text_input("LLPIN (if LLP)", e.get('llpin', ''), key="fs_m_llpin")
                m_cy_date = r2[1].date_input("Current year ended", value=_to_date(per.get('cy', {}), 2026),
                                             min_value=MIND, max_value=MAXD, format="DD/MM/YYYY",
                                             key="fs_m_cyend")
                m_py_date = r2[2].date_input("Previous year ended", value=_to_date(per.get('py', {}), 2025),
                                             min_value=MIND, max_value=MAXD, format="DD/MM/YYYY",
                                             key="fs_m_pyend")

            # ── Signatories & sign-off ─────────────────────────────────────────
            with st.expander("✍️ Signatories & sign-off"):
                sig_df = pd.DataFrame(ent.get('signatories') or [],
                                      columns=['name', 'designation', 'pan'])
                edited_sig = st.data_editor(
                    sig_df, num_rows="dynamic", key="fs_sig_editor", width="stretch",
                    column_config={
                        'name': st.column_config.TextColumn("Name"),
                        'designation': st.column_config.SelectboxColumn(
                            "Designation", options=fs_grouping.DESIGNATION_OPTIONS),
                        'pan': st.column_config.TextColumn("PAN"),
                    })
                sc = st.columns([1, 1, 2])
                m_sgn_place = sc[0].text_input("Place", sgn.get('place', ''), key="fs_m_sgnplace")
                m_sgn_date = sc[1].date_input("Date of sign", value=_to_date(sgn, 2026),
                                              min_value=MIND, max_value=MAXD, format="DD/MM/YYYY",
                                              key="fs_m_sgndate")

            # ── Auditor (firm + signing CA come from the Firm Profile) ─────────
            with st.expander("🧾 Auditor"):
                _prof = profile_engine.load_profile()
                _pnames = profile_engine.partner_names(_prof)
                if not _pnames:
                    st.info("No CA partners in the **Firm Profile** yet. Add the firm + "
                            "partners via **👤 Firm profile** in the sidebar, then pick the "
                            "signing CA here. Using the last saved values for now.")
                    m_caname = aud.get('ca_name', '')
                    m_amno = aud.get('membership_no', '')
                    m_afirm = aud.get('firm_name', '')
                    m_afrn = aud.get('frn', '')
                else:
                    _def = aud.get('ca_name', '')
                    _i0 = _pnames.index(_def) if _def in _pnames else 0
                    m_caname = st.selectbox("Signing CA (from Firm Profile)", _pnames,
                                            index=_i0, key="fs_m_caname_sel")
                    _sel = profile_engine.get_partner(_prof, m_caname)
                    m_amno = _sel.get('membership_no', '')
                    m_afirm = _prof.get('firm_name', '')
                    m_afrn = _prof.get('frn', '')
                    st.caption(f"**Firm:** {m_afirm or '—'} &nbsp;·&nbsp; **FRN:** {m_afrn or '—'} "
                               f"&nbsp;·&nbsp; **Membership No.:** {m_amno or '—'} &nbsp;"
                               "<span style='color:#888'>(edit in 👤 Firm profile)</span>",
                               unsafe_allow_html=True)
                b2 = st.columns(3)
                m_adesig = b2[0].text_input("Designation", aud.get('designation', 'Chartered Accountant'),
                                            key="fs_m_adesig")
                m_audin = b2[1].text_input("UDIN", aud.get('udin', ''), key="fs_m_audin")
                m_aplace = b2[2].text_input("Place", aud.get('place', ''), key="fs_m_aplace")
                b3 = st.columns(3)
                m_aud_date = b3[0].date_input("Date of report", value=_to_date(aud, 2026),
                                              min_value=MIND, max_value=MAXD, format="DD/MM/YYYY",
                                              key="fs_m_auddate")
                _spd = ["Both", "Place", "Date", "None"]
                m_spd = b3[1].selectbox("Show place/date", _spd,
                                        index=_idx(_spd, aud.get('show_place_date'), 0), key="fs_m_spd")
                m_show_udin = b3[2].checkbox("Show UDIN", bool(aud.get('show_udin', True)),
                                             key="fs_m_showudin")
                m_printca = st.checkbox("Print CA firm details",
                                        bool(aud.get('print_ca_details', True)), key="fs_m_printca")

            # ── Options, presentation & print ──────────────────────────────────
            with st.expander("⚙️ Options, presentation & print"):
                o = st.columns(3)
                _dep = ["FAR IT", "Manual", "None"]
                m_dep = o[0].selectbox("Depreciation", _dep, index=_idx(_dep, opt.get('depreciation'), 0),
                                       key="fs_m_dep")
                _pd = ["Reserves", "Partners Capital"]
                m_profdest = o[1].selectbox("Profit to", _pd,
                                            index=_idx(_pd, opt.get('profit_destination'), 0),
                                            key="fs_m_profdest")
                m_comp = o[2].checkbox("Comparative", bool(opt.get('comparative', True)), key="fs_m_comp")
                m_cash = bool(opt.get('cash_flow', False))   # cash flow not built yet — hidden
                m_annex = o[0].checkbox("Annexures", bool(opt.get('annexures', True)), key="fs_m_annex")
                m_itr = o[1].checkbox("ITR 3/5", bool(opt.get('itr_35', True)), key="fs_m_itr")
                p = st.columns(3)
                m_round = p[0].selectbox("Round off", fs_grouping.ROUND_OFF_OPTIONS,
                                         index=_idx(fs_grouping.ROUND_OFF_OPTIONS, pre.get('round_off'), 0),
                                         key="fs_m_round")
                m_theme = p[1].selectbox("Theme", fs_grouping.THEME_LIST,
                                         index=_idx(fs_grouping.THEME_LIST, pre.get('theme'), 0),
                                         key="fs_m_theme")
                m_border = p[2].selectbox("Border", fs_grouping.BORDER_LIST,
                                          index=_idx(fs_grouping.BORDER_LIST, pre.get('border'), 0),
                                          key="fs_m_border")
                m_font = p[0].selectbox("Font", fs_grouping.FONTS,
                                        index=_idx(fs_grouping.FONTS, pre.get('font'), 0), key="fs_m_font")
                _align = ["Left", "Center", "Right"]
                m_align = p[1].selectbox("Header align", _align,
                                         index=_idx(_align, prn.get('header_align'), 0), key="fs_m_align")
                _pa = ["Address", "LLPIN", "None"]
                m_paddr = p[2].selectbox("Print Addr/LLPIN", _pa,
                                         index=_idx(_pa, prn.get('print_address'), 0), key="fs_m_paddr")
                q = st.columns(3)
                m_notes_start = q[0].number_input("Notes start no.", 1, 50,
                                                   int(prn.get('notes_start', 3) or 3), key="fs_m_nstart")
                m_2dp = q[1].checkbox("2 decimals", bool(pre.get('two_decimals', False)), key="fs_m_2dp")
                m_hidezero = q[2].checkbox("Hide nil faces", bool(prn.get('face_hide_zero', True)),
                                           key="fs_m_hidezero")
                m_notescol = q[0].checkbox("Note column", bool(prn.get('show_notes_col', True)),
                                           key="fs_m_notescol")
                m_ppol = q[1].checkbox("Print policies", bool(prn.get('print_policies', True)),
                                       key="fs_m_ppol")

            if st.button("💾 Save master data", key="fs_save_master", type="primary", width="stretch"):
                sigs = []
                for r in edited_sig.to_dict('records'):
                    if str(r.get('name') or '').strip() or str(r.get('pan') or '').strip():
                        sigs.append({'name': (r.get('name') or '').strip(),
                                     'designation': r.get('designation') or 'Partner',
                                     'pan': (r.get('pan') or '').strip()})
                fs_engine.save_entity(company_name, {
                    "current_fy": fs_engine.get_current_fy(company_name) or None,
                    "previous_fy": fs_engine.get_previous_fy(company_name) or None,
                    "entity": {"name": m_name, "address": m_addr, "type": m_type,
                               "pan": m_pan, "llpin": m_llpin,
                               "nature_of_business": e.get('nature_of_business', '')},
                    "period": {"cy": _from_date(m_cy_date), "py": _from_date(m_py_date)},
                    "signatories": sigs,
                    "sign": dict(_from_date(m_sgn_date), place=m_sgn_place,
                                 theme_color=sgn.get('theme_color', True)),
                    "auditor": {"firm_name": m_afirm, "frn": m_afrn, "membership_no": m_amno,
                                "ca_name": m_caname, "designation": m_adesig, "place": m_aplace,
                                **_from_date(m_aud_date), "udin": m_audin,
                                "show_udin": m_show_udin, "show_place_date": m_spd,
                                "print_ca_details": m_printca},
                    "options": {"depreciation": m_dep, "cash_flow": m_cash, "annexures": m_annex,
                                "itr_35": m_itr, "comparative": m_comp,
                                "round_tally_import": opt.get('round_tally_import', True),
                                "profit_destination": m_profdest},
                    "presentation": {"round_off": m_round, "two_decimals": m_2dp, "theme": m_theme,
                                     "border": m_border, "font": m_font},
                    "print": {"header_align": m_align, "print_address": m_paddr,
                              "face_hide_zero": m_hidezero, "print_policies": m_ppol,
                              "notes_start": int(m_notes_start), "show_notes_col": m_notescol},
                })
                st.session_state["fs_work_company"] = None   # rebuild with new entity type
                # Drop the live "🎨 Look" preview overrides so the viewer + exports
                # re-seed from the theme/border just saved here.
                for _k in [k for k in list(st.session_state.keys())
                           if k.startswith("fs_prev_theme_") or k.startswith("fs_prev_border_")]:
                    st.session_state.pop(_k, None)
                st.toast("Master data saved", icon="✅")
                st.rerun()

        @st.fragment
        def _fs_far():
            """Fixed Assets Register — Income-tax block depreciation feeding Note 7."""
            cy_fy = fs_engine.get_current_fy(company_name)
            opts = fs_engine.load_entity(company_name).get("options", {})
            far_on = opts.get("depreciation") == "FAR IT"
            st.markdown("#### 🏭 Fixed Assets & Depreciation (Income-tax Act, 1961)")
            if not far_on:
                st.info("Depreciation source is **not** set to *FAR IT*. Set it under "
                        "**📇 Master Data → Options** to feed this register into Note 7. "
                        "You can still enter the register here.")

            with st.expander("📋 Block depreciation rates (Income-tax)", expanded=False):
                ref = [{"Category": c, "Asset Block": b, "Rate %": r}
                       for c, blocks in fs_grouping.FAR_RATES.items()
                       for b, r in blocks.items()]
                st.dataframe(pd.DataFrame(ref), hide_index=True, width="stretch")
                st.caption("Leave a row's **Rate %** blank to use the block's default above; "
                           "enter a value to override it.")

            all_blocks = sorted({b for bl in fs_grouping.FAR_RATES.values() for b in bl})
            far_rows = fs_engine.load_far(company_name, cy_fy)
            _pfy = fs_engine.get_previous_fy(company_name)
            _py_far = fs_engine.load_far(company_name, _pfy) if _pfy else []
            if not far_rows and _py_far:
                # First open of a new year: auto-seed opening WDV from PY closing.
                seed = fs_reports.far_seed_rows(fs_reports.compute_far(_py_far))
                if seed:
                    fs_engine.save_far(company_name, cy_fy, seed)
                    far_rows = fs_engine.load_far(company_name, cy_fy)
                    st.info(f"↪️ Opening WDV auto-seeded from {_pfy} closing "
                            f"({len(seed)} asset(s)).")
            if not far_rows:
                far_rows = [fs_engine.far_default_row()]
            disp = pd.DataFrame([{
                "Name of Asset": r.get("name", ""),
                "Category": r.get("category", "Tangible"),
                "Asset Block": r.get("block", ""),
                "Rate % (blank=auto)": r.get("rate"),
                "Opening Gross WDV": r.get("opening_gross", 0.0),
                "Addn <180d (full)": r.get("add_before180", 0.0),
                "Addn >180d (half)": r.get("add_after180", 0.0),
                "Sale Consideration": r.get("sale", 0.0),
                "Opening Accum. Dep": r.get("opening_accum", 0.0),
                "Manual Dep Adj": r.get("manual_adj", 0.0),
            } for r in far_rows])

            cseed1, cseed2 = st.columns([3, 1])
            with cseed1:
                if not _pfy:
                    st.caption("↪️ Seeding needs a **Previous year** set in Master Data.")
                elif not _py_far:
                    st.caption(f"↪️ No FAR saved for **{_pfy}** — nothing to seed from. "
                               f"(This year's register is saved as {cy_fy}.)")
            with cseed2:
                if _pfy and st.button("↪️ Seed opening from PY", width="stretch",
                                      disabled=not _py_far,
                                      help=f"Roll {_pfy} closing WDV into this year's opening "
                                           f"(replaces the current rows)"):
                    seed = fs_reports.far_seed_rows(fs_reports.compute_far(_py_far))
                    if seed:
                        fs_engine.save_far(company_name, cy_fy, seed)
                        st.session_state.pop("fs_far_editor", None)
                        st.toast("Opening seeded from previous year", icon="↪️")
                        st.rerun(scope="fragment")
                    else:
                        st.warning(f"FAR for {_pfy} has no usable rows.")

            _more = st.toggle("More columns (sale / opening accum. / manual adj)",
                              key="fs_far_more",
                              help="Show the rarely-used columns. Hidden values are kept.")
            _cc = {
                "Name of Asset": st.column_config.TextColumn("Name of Asset", width="medium"),
                "Category": st.column_config.SelectboxColumn(
                    "Category", options=fs_grouping.FAR_CATEGORIES),
                "Asset Block": st.column_config.SelectboxColumn(
                    "Asset Block", options=all_blocks),
                "Rate % (blank=auto)": st.column_config.NumberColumn(
                    "Rate %", min_value=0, max_value=100, step=0.5),
                "Opening Gross WDV": st.column_config.NumberColumn(format="accounting"),
                "Addn <180d (full)": st.column_config.NumberColumn(format="accounting"),
                "Addn >180d (half)": st.column_config.NumberColumn(format="accounting"),
                "Sale Consideration": st.column_config.NumberColumn(format="accounting"),
                "Opening Accum. Dep": st.column_config.NumberColumn(format="accounting"),
                "Manual Dep Adj": st.column_config.NumberColumn(format="accounting"),
            }
            if not _more:
                for _h in ("Sale Consideration", "Opening Accum. Dep", "Manual Dep Adj"):
                    _cc[_h] = None
            edited = st.data_editor(
                disp, num_rows="dynamic", key="fs_far_editor", width="stretch",
                column_config=_cc)

            def _num(x):
                """Safe float: blank/NaN/None/garbage -> 0.0 (NaN is truthy, so
                `x or 0.0` is NOT enough)."""
                try:
                    return 0.0 if pd.isna(x) else float(x)
                except (TypeError, ValueError):
                    return 0.0

            def _rows_from_editor(df):
                out = []
                for _, row in df.iterrows():
                    rate = row.get("Rate % (blank=auto)")
                    out.append({
                        "name": ("" if pd.isna(row.get("Name of Asset"))
                                 else str(row.get("Name of Asset")).strip()),
                        "category": ("Tangible" if pd.isna(row.get("Category"))
                                     else (row.get("Category") or "Tangible")),
                        "block": ("" if pd.isna(row.get("Asset Block"))
                                  else str(row.get("Asset Block"))),
                        "rate": (None if pd.isna(rate) else float(rate)),
                        "opening_gross": _num(row.get("Opening Gross WDV")),
                        "add_before180": _num(row.get("Addn <180d (full)")),
                        "add_after180": _num(row.get("Addn >180d (half)")),
                        "sale": _num(row.get("Sale Consideration")),
                        "opening_accum": _num(row.get("Opening Accum. Dep")),
                        "manual_adj": _num(row.get("Manual Dep Adj")),
                    })
                return out

            live = _rows_from_editor(edited)
            comp = fs_reports.compute_far(live)

            # Computed preview (read-only) — Indian-grouped strings (guaranteed format)
            _ia = lambda v: fs_reports.fmt_amt(v, dash_zero=False)
            _cols = ("opening_net", "dep", "total_dep", "closing_gross", "closing_net")
            _disp = [a for a in comp["assets"] if a.get("name") or a.get("opening_gross")]
            prev_rows, totals = [], {k: 0.0 for k in _cols}
            for a in _disp:
                for k in _cols:
                    totals[k] += a.get(k, 0.0)
                prev_rows.append({
                    "Name": a.get("name", ""), "Block": a.get("block", ""),
                    "Rate %": ("" if a.get("rate") is None else f"{a.get('rate'):g}"),
                    "Opening Net": _ia(a.get("opening_net", 0.0)),
                    "Depreciation": _ia(a.get("dep", 0.0)),
                    "Total Dep": _ia(a.get("total_dep", 0.0)),
                    "Closing Gross": _ia(a.get("closing_gross", 0.0)),
                    "Closing Net WDV": _ia(a.get("closing_net", 0.0)),
                })
            if prev_rows:
                prev_rows.append({
                    "Name": "Total", "Block": "", "Rate %": "",
                    "Opening Net": _ia(totals["opening_net"]),
                    "Depreciation": _ia(totals["dep"]),
                    "Total Dep": _ia(totals["total_dep"]),
                    "Closing Gross": _ia(totals["closing_gross"]),
                    "Closing Net WDV": _ia(totals["closing_net"]),
                })
                with st.expander("🧮 Computed (formula-locked)", expanded=False):
                    st.dataframe(pd.DataFrame(prev_rows), hide_index=True, width="stretch")

            # Reconciliation vs the ledger fixed-asset balance in the trial balance
            far_net = sum(a.get("closing_net", 0.0) for a in comp["assets"])
            far_dep = sum(a.get("total_dep", 0.0) for a in comp["assets"])
            if st.button("🔄 Refresh ‘Fixed assets per TB’ from saved grouping",
                         key="fs_far_refresh_tb",
                         help="Rebuilds the working mapping so this reflects the latest "
                              "Grouping & adjustments edits."):
                _ret = fs_engine.grouping_entity_type(company_name)
                st.session_state["fs_work"] = fs_engine.build_working_mapping(company_name, _ret)
                st.toast("Refreshed from saved grouping", icon="🔄")
                st.rerun(scope="fragment")
            rep = fs_reports.compute(st.session_state.get("fs_work", {}),
                                     fs_engine.load_aux(company_name, cy_fy))
            bf = rep.get("by_face", {})
            tb_fa = -(bf.get("Property Plant and Equipment", 0.0)
                      + bf.get("Intangible assets", 0.0))   # debit-negative -> positive
            diff = far_net - tb_fa
            _ia = lambda v: fs_reports.fmt_amt(v, dash_zero=False)   # Indian commas, no symbol
            m1, m2, m3, m4 = st.columns(4)
            m1.metric("FAR closing net (CY)", _ia(far_net))
            m2.metric("Fixed assets per TB", _ia(tb_fa))
            m3.metric("Difference", _ia(diff),
                      delta=("ties" if abs(diff) < 1 else "review"),
                      delta_color=("normal" if abs(diff) < 1 else "inverse"))
            m4.metric("Depreciation for the year", _ia(far_dep))
            if abs(diff) >= 1:
                st.caption("ℹ️ FAR net differs from the books. FAR drives the Notes; the Balance "
                           "Sheet/P&L stay from the TB. Track & reconcile every gap on the "
                           "**✅ Check** tab, then book it under *Grouping & adjustments*.")

            if st.button("💾 Save FAR", type="primary", key="fs_far_save"):
                fs_engine.save_far(company_name, cy_fy, live)
                st.toast("Fixed Assets Register saved", icon="✅")
                st.rerun(scope="fragment")

        @st.fragment
        def _fs_check():
            """Reconciliation worksheet — Notes/FAR vs the books (TB), CY + PY, with
            editable comments and a tie/review status. User books any gap as a manual
            adjustment under Grouping & adjustments; differences then go to zero."""
            cy_fy = fs_engine.get_current_fy(company_name)
            st.markdown("#### ✅ Reconciliation checks")
            items = fs_reports.reconciliation(
                company_name, work_override=st.session_state.get("fs_work"))
            saved = fs_engine.load_checks(company_name, cy_fy)
            comments = dict(saved.get("comments", {}))

            def _f(x):
                return fs_reports.fmt_amt(x) if x is not None else ""

            if not items:
                st.info("No automated checks yet. These appear once **Depreciation = FAR IT** "
                        "is set (Master Data → Options) and the Fixed Assets Register has data.")
            else:
                rows = []
                for it in items:
                    ok = (abs(it.get("diff_cy") or 0) < 1) and (abs(it.get("diff_py") or 0) < 1)
                    rows.append({
                        "Status": "✅" if ok else "⚠️",
                        "Particulars": it["particulars"],
                        "Notes/FAR (CY)": _f(it.get("far_cy")),
                        "Books (CY)": _f(it.get("books_cy")),
                        "Difference (CY)": _f(it.get("diff_cy")),
                        "Notes/FAR (PY)": _f(it.get("far_py")),
                        "Books (PY)": _f(it.get("books_py")),
                        "Difference (PY)": _f(it.get("diff_py")),
                        "Comment": comments.get(it["key"], ""),
                    })
                cdf = pd.DataFrame(rows)
                edited = st.data_editor(
                    cdf, key="fs_check_editor", width="stretch", hide_index=True,
                    disabled=[c for c in cdf.columns if c != "Comment"],
                    column_config={
                        "Status": st.column_config.TextColumn("✓", width="small"),
                        "Particulars": st.column_config.TextColumn("Particulars", width="large"),
                        "Comment": st.column_config.TextColumn("Comment / how reconciled",
                                                               width="large"),
                    })
                st.caption("Differences are expected where FAR depreciation isn't booked in Tally. "
                           "Book the gap under **🗂 Grouping & adjustments** (an adjustment row) "
                           "and the difference returns to zero here.")

                st.markdown("**➕ Custom checks** (your own reconciliations)")
                cust = saved.get("custom", []) or []
                custdf = pd.DataFrame([{
                    "Particulars": c.get("particulars", ""),
                    "Amount (CY)": c.get("amount_cy"),
                    "Amount (PY)": c.get("amount_py"),
                    "Comment": c.get("comment", ""),
                } for c in cust])
                if custdf.empty:
                    custdf = pd.DataFrame({
                        "Particulars": pd.Series(dtype="object"),
                        "Amount (CY)": pd.Series(dtype="float"),
                        "Amount (PY)": pd.Series(dtype="float"),
                        "Comment": pd.Series(dtype="object")})
                cust_ed = st.data_editor(
                    custdf, key="fs_check_custom", num_rows="dynamic", width="stretch",
                    hide_index=True,
                    column_config={
                        "Particulars": st.column_config.TextColumn(width="large"),
                        "Amount (CY)": st.column_config.NumberColumn(format="%.2f"),
                        "Amount (PY)": st.column_config.NumberColumn(format="%.2f"),
                        "Comment": st.column_config.TextColumn(width="large"),
                    })

                if st.button("💾 Save checks & comments", type="primary", key="fs_check_save"):
                    new_comments = {it["key"]: str(edited.iloc[i]["Comment"] or "").strip()
                                    for i, it in enumerate(items)}
                    new_custom = []
                    for _, r in cust_ed.iterrows():
                        part = r.get("Particulars")
                        if pd.isna(part) or not str(part).strip():
                            continue
                        new_custom.append({
                            "particulars": str(part).strip(),
                            "amount_cy": (None if pd.isna(r.get("Amount (CY)"))
                                          else float(r.get("Amount (CY)"))),
                            "amount_py": (None if pd.isna(r.get("Amount (PY)"))
                                          else float(r.get("Amount (PY)"))),
                            "comment": ("" if pd.isna(r.get("Comment"))
                                        else str(r.get("Comment")).strip()),
                        })
                    fs_engine.save_checks(company_name, cy_fy,
                                          {"comments": new_comments, "custom": new_custom})
                    st.toast("Checks saved", icon="✅")
                    st.rerun(scope="fragment")

        @st.fragment
        def _fs_disclosures():
            """Edit Note 1 (Entity Information) + Note 2 (Significant Accounting
            Policies): toggle each head's disclosure and edit its prefilled text.
            Policies are carried forward (stored per company)."""
            st.markdown("#### 📝 Disclosures — Accounting Policies")
            st.caption("These render as **Note 1 (Entity Information)** and **Note 2 "
                       "(Significant Accounting Policies)**, after the P&L and before the "
                       "numbered notes. Only heads toggled **Disclose** that have text "
                       "appear, lettered a, b, c…")
            _pol_key = f"{company_name}|{fs_engine.get_current_fy(company_name)}"
            if st.session_state.get("fs_pol_co") != _pol_key:
                st.session_state["fs_pol"] = fs_engine.load_policies(company_name)
                st.session_state["fs_pol_co"] = _pol_key
            pol = st.session_state["fs_pol"]

            with st.expander("1 — Entity Information", expanded=False):
                ei = pol['entity_info']
                ei['disclose'] = st.checkbox("Disclose in notes",
                                             value=bool(ei.get('disclose', True)),
                                             key="fs_pol_ei_disc")
                ei['text'] = st.text_area("Entity information", value=ei.get('text', ''),
                                          key="fs_pol_ei_txt", height=80,
                                          label_visibility="collapsed")

            with st.expander("2 — Significant Accounting Policies", expanded=False):
                st.caption("Tick the policies to disclose:")
                hdf = pd.DataFrame([{
                    "Head": p['head'], "Disclose": bool(p['disclose']),
                    "Has text": "✓" if (str(p.get('text', '')).strip() or p.get('table')) else "—",
                } for p in pol['policies']])
                hed = st.data_editor(
                    hdf, key="fs_pol_heads", hide_index=True, width="stretch",
                    disabled=["Head", "Has text"],
                    column_config={
                        "Head": st.column_config.TextColumn(width="large"),
                        "Disclose": st.column_config.CheckboxColumn("Disclose"),
                        "Has text": st.column_config.TextColumn("Text?", width="small"),
                    })
                for i, row in hed.iterrows():
                    if i < len(pol['policies']):
                        pol['policies'][i]['disclose'] = bool(row['Disclose'])

                names = [p['head'] for p in pol['policies']]
                sidx = st.selectbox("Edit a policy's text", range(len(names)),
                                    format_func=lambda i: names[i], key="fs_pol_sel")
                p = pol['policies'][sidx]
                p['text'] = st.text_area(f"Text — {p['head']}", value=p.get('text', ''),
                                         key=f"fs_pol_txt_{p['key']}", height=80)
                if 'table' in p:
                    st.caption(f"Sub-table shown under “{p['head']}”")
                    cols = p.get('table_cols', [])
                    headers = p.get('table_headers', cols)
                    tdf = pd.DataFrame(p.get('table') or [], columns=cols)
                    tdf.columns = headers
                    ted = st.data_editor(tdf, key=f"fs_pol_tbl_{p['key']}",
                                         num_rows="dynamic", hide_index=True, width="stretch")
                    newrows = []
                    for _, rr in ted.iterrows():
                        vals = {c: ('' if pd.isna(rr[h]) else str(rr[h]))
                                for c, h in zip(cols, headers)}
                        if any(v.strip() for v in vals.values()):
                            newrows.append(vals)
                    p['table'] = newrows

                shown = [pp['head'] for pp in pol['policies']
                         if pp['disclose'] and (str(pp.get('text', '')).strip() or pp.get('table'))]
                st.caption("**Will appear in Note 2:** " + (", ".join(shown) if shown else "— none —"))

                if st.button("💾 Save policies", type="primary", key="fs_pol_save"):
                    fs_engine.save_policies(company_name, pol)
                    st.toast("Policies saved — open Statements → Notes to see them", icon="✅")
                    st.rerun(scope="fragment")

            # ── Trade Receivables Ageing Schedule ─────────────────────────────
            with st.expander("3 — Trade Receivables Ageing Schedule", expanded=False):
                cyf = fs_engine.get_current_fy(company_name)
                age = fs_engine.load_tr_ageing(company_name, cyf)
                age['disclose'] = st.checkbox(
                    "Disclose this schedule (renders as **10.x** below the Trade "
                    "receivables note)", value=bool(age.get('disclose', False)),
                    key="fs_age_disc")
                st.caption("Auto-fetch FIFO-ages the debtor ledgers from transactions and "
                           "prefills **Unsecured – Considered good**. It's an estimate "
                           "(no bill-wise data in Tally export) — review & edit any cell.")
                if st.button("🔄 Auto-fetch from transactions (FIFO)", key="fs_age_auto"):
                    et = fs_engine.grouping_entity_type(company_name)
                    cyw = (st.session_state.get("fs_work")
                           or fs_engine.build_working_mapping(company_name, et))
                    a_cy = fs_engine.receivables_ageing(company_name, cyf, cyw)
                    pyf = fs_engine.get_previous_fy(company_name)
                    pyw = fs_engine.build_py_working_mapping(company_name, et)
                    a_py = (fs_engine.receivables_ageing(company_name, pyf, pyw)
                            if pyw else {"lt6": 0.0, "gt6": 0.0})
                    g = age['grid']['unsecured']
                    g['lt6_cy'], g['gt6_cy'] = a_cy['lt6'], a_cy['gt6']
                    g['lt6_py'], g['gt6_py'] = a_py['lt6'], a_py['gt6']
                    fs_engine.save_tr_ageing(company_name, cyf, age)
                    st.toast(f"Filled Unsecured CG — <6m {a_cy['lt6']:,.0f}, "
                             f">6m {a_cy['gt6']:,.0f}", icon="✅")
                    st.rerun(scope="fragment")

                _num = lambda x: 0.0 if pd.isna(x) else float(x)
                _ROWS = [("secured", "Secured Considered good"),
                         ("unsecured", "Unsecured Considered good"),
                         ("doubtful", "Doubtful"),
                         ("provision", "Less: Provision for doubtful receivables")]
                _AC = ["< 6m CY", "< 6m PY", "> 6m CY", "> 6m PY"]
                gdf = pd.DataFrame([{
                    "Particulars": lbl, "< 6m CY": age['grid'][k]['lt6_cy'],
                    "< 6m PY": age['grid'][k]['lt6_py'], "> 6m CY": age['grid'][k]['gt6_cy'],
                    "> 6m PY": age['grid'][k]['gt6_py']} for k, lbl in _ROWS])
                ged = st.data_editor(
                    gdf, key="fs_age_grid", hide_index=True, width="stretch", num_rows="fixed",
                    disabled=["Particulars"],
                    column_config={c: st.column_config.NumberColumn(format="%.2f") for c in _AC})
                xdf = pd.DataFrame([
                    {"Particulars": "Unbilled receivables", "CY": age['unbilled']['cy'],
                     "PY": age['unbilled']['py']},
                    {"Particulars": "Undue", "CY": age['undue']['cy'], "PY": age['undue']['py']}])
                xed = st.data_editor(
                    xdf, key="fs_age_extra", hide_index=True, width="stretch", num_rows="fixed",
                    disabled=["Particulars"],
                    column_config={"CY": st.column_config.NumberColumn(format="%.2f"),
                                   "PY": st.column_config.NumberColumn(format="%.2f")})

                # ── Reconciliation (entry-screen only; NOT printed in the note) ───
                def _bsum(col):     # secured + unsecured + doubtful − provision
                    return (_num(ged.iloc[0][col]) + _num(ged.iloc[1][col])
                            + _num(ged.iloc[2][col]) - _num(ged.iloc[3][col]))
                tot_cy = (_bsum("< 6m CY") + _bsum("> 6m CY")
                          + _num(xed.iloc[0]["CY"]) + _num(xed.iloc[1]["CY"]))
                tot_py = (_bsum("< 6m PY") + _bsum("> 6m PY")
                          + _num(xed.iloc[0]["PY"]) + _num(xed.iloc[1]["PY"]))
                try:
                    _et = fs_engine.grouping_entity_type(company_name)
                    _cyw = (st.session_state.get("fs_work")
                            or fs_engine.build_working_mapping(company_name, _et))
                    _pyw = fs_engine.build_py_working_mapping(company_name, _et)
                    tb_cy = -sum(float(v.get('closing') or 0) for v in _cyw.values()
                                 if v.get('face') == 'Trade receivables')
                    tb_py = (-sum(float(v.get('closing') or 0) for v in _pyw.values()
                                  if v.get('face') == 'Trade receivables')) if _pyw else 0.0
                except Exception:
                    tb_cy = tb_py = 0.0   # master not set up yet
                recon_df = pd.DataFrame([
                    {"Particulars": "Total as per schedule", "Current Year": tot_cy,
                     "Previous Year": tot_py},
                    {"Particulars": "As per Trial Balance", "Current Year": tb_cy,
                     "Previous Year": tb_py},
                    {"Particulars": "Difference", "Current Year": tot_cy - tb_cy,
                     "Previous Year": tot_py - tb_py}])
                st.caption("Reconciliation (for your check — not printed in the note):")
                st.dataframe(recon_df, hide_index=True, width="stretch",
                             column_config={
                                 "Current Year": st.column_config.NumberColumn(format="%.2f"),
                                 "Previous Year": st.column_config.NumberColumn(format="%.2f")})
                if abs(tot_cy - tb_cy) > 0.5:
                    st.warning(f"⚠️ Current-year difference {tot_cy - tb_cy:,.2f} — "
                               "schedule doesn't tie to the trade-receivables balance.")

                fn_text = st.text_area("Foot notes (one per line)",
                                       value="\n".join(age.get('footnotes', [])),
                                       key="fs_age_fn", height=70)
                if st.button("💾 Save ageing schedule", type="primary", key="fs_age_save"):
                    for i, (k, _l) in enumerate(_ROWS):
                        r = ged.iloc[i]
                        age['grid'][k] = {"lt6_cy": _num(r["< 6m CY"]), "lt6_py": _num(r["< 6m PY"]),
                                          "gt6_cy": _num(r["> 6m CY"]), "gt6_py": _num(r["> 6m PY"])}
                    age['unbilled'] = {"cy": _num(xed.iloc[0]["CY"]), "py": _num(xed.iloc[0]["PY"])}
                    age['undue'] = {"cy": _num(xed.iloc[1]["CY"]), "py": _num(xed.iloc[1]["PY"])}
                    age['footnotes'] = [ln.strip() for ln in fn_text.splitlines() if ln.strip()]
                    fs_engine.save_tr_ageing(company_name, cyf, age)
                    st.toast("Ageing schedule saved — see Statements → Notes", icon="✅")
                    st.rerun(scope="fragment")

            # ── Owner's Capital Account (Proprietor / Individual only) ─────────
            if fs_engine.grouping_entity_type(company_name) == "Proprietor":
                with st.expander("4 — Owner's Capital Account", expanded=False):
                    ocf = fs_engine.get_current_fy(company_name)
                    oc = fs_engine.load_owners_capital(company_name, ocf)
                    oc['disclose'] = st.checkbox(
                        "Disclose this schedule (renders as the Owner's Capital Account note)",
                        value=bool(oc.get('disclose', False)), key="fs_oc_disc")
                    st.caption("Applies to Individual / HUF / Proprietor. Everything is user-"
                               "entered **except Profit / Loss for the period** (auto from P&L). "
                               "Add rows (Capital Receipts, Personal Expenses…) as needed.")
                    _ocnum = lambda x: 0.0 if pd.isna(x) else float(x)
                    try:
                        _oet = fs_engine.grouping_entity_type(company_name)
                        _ocyw = (st.session_state.get("fs_work")
                                 or fs_engine.build_working_mapping(company_name, _oet))
                        rep_cy = fs_reports.compute(_ocyw, fs_engine.load_aux(company_name, ocf))
                        _opyf = fs_engine.get_previous_fy(company_name)
                        _opyw = fs_engine.build_py_working_mapping(company_name, _oet)
                        rep_py = (fs_reports.compute(_opyw, fs_engine.load_aux(company_name, _opyf))
                                  if _opyw else None)
                    except Exception:
                        rep_cy, rep_py = None, None
                        st.caption("ℹ️ Set up the master/grouping to auto-fill Profit/Loss "
                                   "and the TB check.")
                    profit_cy = rep_cy['profit'] if rep_cy else 0.0
                    profit_py = rep_py['profit'] if rep_py else 0.0
                    st.caption(f"Profit/(Loss) for the period (auto) — CY {profit_cy:,.2f}, "
                               f"PY {profit_py:,.2f}")

                    def _oc_editor(rows, key, title):
                        st.markdown(f"**{title}**")
                        df = pd.DataFrame([{"Particulars": r['label'], "CY": r['cy'],
                                            "PY": r['py']} for r in rows])
                        if df.empty:
                            df = pd.DataFrame({"Particulars": pd.Series(dtype="object"),
                                               "CY": pd.Series(dtype="float"),
                                               "PY": pd.Series(dtype="float")})
                        return st.data_editor(
                            df, key=key, num_rows="dynamic", hide_index=True, width="stretch",
                            column_config={"Particulars": st.column_config.TextColumn(width="large"),
                                           "CY": st.column_config.NumberColumn(format="%.2f"),
                                           "PY": st.column_config.NumberColumn(format="%.2f")})

                    ced = _oc_editor(oc['credit'], "fs_oc_credit",
                                     "Credit side (capital introduced / receipts)")
                    ded = _oc_editor(oc['debit'], "fs_oc_debit",
                                     "Debit side (drawings / personal expenses)")

                    def _coltot(ed, col):
                        return sum(_ocnum(v) for v in ed[col]) if col in ed else 0.0
                    cred_cy = _coltot(ced, "CY") + max(profit_cy, 0.0)
                    cred_py = _coltot(ced, "PY") + max(profit_py, 0.0)
                    deb_cy = _coltot(ded, "CY") + max(-profit_cy, 0.0)
                    deb_py = _coltot(ded, "PY") + max(-profit_py, 0.0)
                    tot_cy, tot_py = cred_cy - deb_cy, cred_py - deb_py
                    _face = "Owner's Capital Account"
                    tb_cy = ((rep_cy['by_face'].get(_face, 0.0) + rep_cy.get('profit_to_add', 0.0))
                             if rep_cy else 0.0)
                    tb_py = ((rep_py['by_face'].get(_face, 0.0) + rep_py.get('profit_to_add', 0.0))
                             if rep_py else 0.0)
                    recon = pd.DataFrame([
                        {"Particulars": "Total of Credit Side", "Current Year": cred_cy,
                         "Previous Year": cred_py},
                        {"Particulars": "Total of Debit Side", "Current Year": deb_cy,
                         "Previous Year": deb_py},
                        {"Particulars": "Total (closing capital)", "Current Year": tot_cy,
                         "Previous Year": tot_py},
                        {"Particulars": "As per Trial Balance", "Current Year": tb_cy,
                         "Previous Year": tb_py},
                        {"Particulars": "Difference", "Current Year": tot_cy - tb_cy,
                         "Previous Year": tot_py - tb_py}])
                    st.caption("Reconciliation (for your check — not printed in the note):")
                    st.dataframe(recon, hide_index=True, width="stretch",
                                 column_config={
                                     "Current Year": st.column_config.NumberColumn(format="%.2f"),
                                     "Previous Year": st.column_config.NumberColumn(format="%.2f")})
                    if abs(tot_cy - tb_cy) > 0.5:
                        st.warning(f"⚠️ Current-year difference {tot_cy - tb_cy:,.2f} — "
                                   "schedule doesn't tie to the capital balance.")
                    fn2 = st.text_area("Foot notes (one per line)",
                                       value="\n".join(oc.get('footnotes', [])),
                                       key="fs_oc_fn", height=70)
                    if st.button("💾 Save Owner's Capital schedule", type="primary",
                                 key="fs_oc_save"):
                        def _collect(ed):
                            out = []
                            for _, rr in ed.iterrows():
                                lbl = rr.get("Particulars")
                                if pd.isna(lbl) or not str(lbl).strip():
                                    continue
                                out.append({"label": str(lbl).strip(),
                                            "cy": _ocnum(rr.get("CY")), "py": _ocnum(rr.get("PY"))})
                            return out
                        oc['credit'] = _collect(ced)
                        oc['debit'] = _collect(ded)
                        oc['footnotes'] = [ln.strip() for ln in fn2.splitlines() if ln.strip()]
                        fs_engine.save_owners_capital(company_name, ocf, oc)
                        st.toast("Owner's Capital schedule saved", icon="✅")
                        st.rerun(scope="fragment")

            # ── Inventories (Cost of material consumed + Change in inventories) ─
            with st.expander("5 — Inventories", expanded=False):
                invf = fs_engine.get_current_fy(company_name)
                inv = fs_engine.load_inventory(company_name, invf)
                _inv_filled = fs_engine.inventory_has_data(inv)
                inv['disclose'] = st.checkbox(
                    "Show these schedules in the notes (drive the **Inventories**, **Cost of "
                    "material consumed** and **Change in inventories** notes)",
                    value=bool(inv.get('disclose', False)) or _inv_filled, key="fs_inv_disc")
                if _inv_filled and not inv.get('disclose'):
                    st.info("Figures are entered but this is currently OFF — tick the box "
                            "above and press 💾 Save to show them in the notes.")
                st.caption("Optional. When blank, the simple Opening/Closing stock figures "
                           "(Step 2) are used. Only the stock movement (Opening − Closing) "
                           "affects the balance — purchases stay in the trial balance, so "
                           "map your purchase ledgers to the relevant face and reconcile "
                           "using the Difference rows below.")
                _ivn = lambda x: 0.0 if pd.isna(x) else float(x)

                # Books figures (no inventory injection) for the TB-check references.
                try:
                    _iet = fs_engine.grouping_entity_type(company_name)
                    _icyw = (st.session_state.get("fs_work")
                             or fs_engine.build_working_mapping(company_name, _iet))
                    _ipyf = fs_engine.get_previous_fy(company_name)
                    _ipyw = fs_engine.build_py_working_mapping(company_name, _iet)
                    _irep_cy = fs_reports.compute(_icyw, fs_engine.load_aux(company_name, invf), _iet)
                    _irep_py = (fs_reports.compute(_ipyw, fs_engine.load_aux(company_name, _ipyf), _iet)
                                if _ipyw else None)
                except Exception:
                    _irep_cy = _irep_py = None
                    st.caption("ℹ️ Set up the master/grouping to enable the TB checks.")

                def _books_face(rep, face):   # expense faces -> natural positive
                    return -rep['by_face'].get(face, 0.0) if rep else 0.0

                # ---- A) Cost of Material Consumed ----
                st.markdown("**A · Cost of Material Consumed**")
                mat_df = pd.DataFrame([{
                    "Particulars": r['label'],
                    "Opening (CY)": r['opening_cy'], "Purchases (CY)": r['purchases_cy'],
                    "Closing (CY)": r['closing_cy'],
                    "Opening (PY)": r['opening_py'], "Purchases (PY)": r['purchases_py'],
                    "Closing (PY)": r['closing_py']} for r in inv['materials']])
                if mat_df.empty:
                    mat_df = pd.DataFrame({c: pd.Series(dtype=("object" if c == "Particulars" else "float"))
                                           for c in ["Particulars", "Opening (CY)", "Purchases (CY)",
                                                     "Closing (CY)", "Opening (PY)", "Purchases (PY)",
                                                     "Closing (PY)"]})
                _matc = ["Opening (CY)", "Purchases (CY)", "Closing (CY)",
                         "Opening (PY)", "Purchases (PY)", "Closing (PY)"]
                med = st.data_editor(
                    mat_df, key="fs_inv_mat", num_rows="dynamic", hide_index=True, width="stretch",
                    column_config={**{"Particulars": st.column_config.TextColumn(width="medium")},
                                   **{c: st.column_config.NumberColumn(format="%.2f") for c in _matc}})

                st.markdown("**Other Manufacturing Expenses**")
                mfg_df = pd.DataFrame([{"Particulars": r['label'], "ITR Group": r.get('group', ''),
                                        "CY": r['cy'], "PY": r['py']} for r in inv['mfg_expenses']])
                if mfg_df.empty:
                    mfg_df = pd.DataFrame({"Particulars": pd.Series(dtype="object"),
                                           "ITR Group": pd.Series(dtype="object"),
                                           "CY": pd.Series(dtype="float"),
                                           "PY": pd.Series(dtype="float")})
                mged = st.data_editor(
                    mfg_df, key="fs_inv_mfg", num_rows="dynamic", hide_index=True, width="stretch",
                    column_config={"Particulars": st.column_config.TextColumn(width="medium"),
                                   "ITR Group": st.column_config.TextColumn(width="medium"),
                                   "CY": st.column_config.NumberColumn(format="%.2f"),
                                   "PY": st.column_config.NumberColumn(format="%.2f")})

                def _mat_total(col_o, col_p, col_c):
                    t = 0.0
                    for _, rr in med.iterrows():
                        t += _ivn(rr.get(col_o)) + _ivn(rr.get(col_p)) - _ivn(rr.get(col_c))
                    return t

                def _mfg_total(col):
                    return sum(_ivn(v) for v in mged[col]) if col in mged else 0.0
                cost_cy = _mat_total("Opening (CY)", "Purchases (CY)", "Closing (CY)") + _mfg_total("CY")
                cost_py = _mat_total("Opening (PY)", "Purchases (PY)", "Closing (PY)") + _mfg_total("PY")
                cbk_cy, cbk_py = _books_face(_irep_cy, "Cost of material consumed"), \
                    _books_face(_irep_py, "Cost of material consumed")
                crec = pd.DataFrame([
                    {"Particulars": "Total as per schedule", "Current Year": cost_cy, "Previous Year": cost_py},
                    {"Particulars": "As per Trial Balance", "Current Year": cbk_cy, "Previous Year": cbk_py},
                    {"Particulars": "Difference", "Current Year": cost_cy - cbk_cy,
                     "Previous Year": cost_py - cbk_py}])
                st.caption("Reconciliation (for your check — not printed in the note):")
                st.dataframe(crec, hide_index=True, width="stretch",
                             column_config={"Current Year": st.column_config.NumberColumn(format="%.2f"),
                                            "Previous Year": st.column_config.NumberColumn(format="%.2f")})
                mfg_fn = st.text_area("Foot notes — Cost of material (one per line)",
                                      value="\n".join(inv.get('mfg_footnotes', [])),
                                      key="fs_inv_mfgfn", height=68)

                # ---- B) Change in Inventories of WIP & Finished Goods ----
                st.markdown("**B · Change in Inventories of WIP & Finished Goods**")
                chg_df = pd.DataFrame([{
                    "Particulars": r['label'], "Opening (CY)": r['open_cy'], "Closing (CY)": r['close_cy'],
                    "Opening (PY)": r['open_py'], "Closing (PY)": r['close_py']} for r in inv['change']])
                if chg_df.empty:
                    chg_df = pd.DataFrame({c: pd.Series(dtype=("object" if c == "Particulars" else "float"))
                                           for c in ["Particulars", "Opening (CY)", "Closing (CY)",
                                                     "Opening (PY)", "Closing (PY)"]})
                _chgc = ["Opening (CY)", "Closing (CY)", "Opening (PY)", "Closing (PY)"]
                ched = st.data_editor(
                    chg_df, key="fs_inv_chg", num_rows="dynamic", hide_index=True, width="stretch",
                    column_config={**{"Particulars": st.column_config.TextColumn(width="medium")},
                                   **{c: st.column_config.NumberColumn(format="%.2f") for c in _chgc}})

                def _chg_total(co, cc):
                    t = 0.0
                    for _, rr in ched.iterrows():
                        t += _ivn(rr.get(co)) - _ivn(rr.get(cc))
                    return t
                chg_cy = _chg_total("Opening (CY)", "Closing (CY)")
                chg_py = _chg_total("Opening (PY)", "Closing (PY)")
                hbk_cy, hbk_py = _books_face(_irep_cy, "Change in Inventories of work in progress and "
                                             "finished goods"), \
                    _books_face(_irep_py, "Change in Inventories of work in progress and finished goods")
                hrec = pd.DataFrame([
                    {"Particulars": "Total as per schedule (Opening − Closing)",
                     "Current Year": chg_cy, "Previous Year": chg_py},
                    {"Particulars": "As per Trial Balance", "Current Year": hbk_cy, "Previous Year": hbk_py},
                    {"Particulars": "Difference", "Current Year": chg_cy - hbk_cy,
                     "Previous Year": chg_py - hbk_py}])
                st.caption("Reconciliation (for your check — not printed in the note):")
                st.dataframe(hrec, hide_index=True, width="stretch",
                             column_config={"Current Year": st.column_config.NumberColumn(format="%.2f"),
                                            "Previous Year": st.column_config.NumberColumn(format="%.2f")})
                _trend = "Decrease in stock" if chg_cy > 0.5 else (
                    "Increase in stock" if chg_cy < -0.5 else "—")
                st.caption(f"(Increase)/Decrease in stock (CY): **{_trend}**")
                chg_fn = st.text_area("Foot notes — Change in inventories (one per line)",
                                      value="\n".join(inv.get('change_footnotes', [])),
                                      key="fs_inv_chgfn", height=68)

                if st.button("💾 Save Inventories schedules", type="primary", key="fs_inv_save"):
                    mats = []
                    for _, rr in med.iterrows():
                        lbl = rr.get("Particulars")
                        if pd.isna(lbl) or not str(lbl).strip():
                            continue
                        mats.append({"label": str(lbl).strip(),
                                     "opening_cy": _ivn(rr.get("Opening (CY)")),
                                     "purchases_cy": _ivn(rr.get("Purchases (CY)")),
                                     "closing_cy": _ivn(rr.get("Closing (CY)")),
                                     "opening_py": _ivn(rr.get("Opening (PY)")),
                                     "purchases_py": _ivn(rr.get("Purchases (PY)")),
                                     "closing_py": _ivn(rr.get("Closing (PY)"))})
                    mfgs = []
                    for _, rr in mged.iterrows():
                        lbl = rr.get("Particulars")
                        if pd.isna(lbl) or not str(lbl).strip():
                            continue
                        mfgs.append({"label": str(lbl).strip(),
                                     "group": ("" if pd.isna(rr.get("ITR Group"))
                                               else str(rr.get("ITR Group")).strip()),
                                     "cy": _ivn(rr.get("CY")), "py": _ivn(rr.get("PY"))})
                    chgs = []
                    for _, rr in ched.iterrows():
                        lbl = rr.get("Particulars")
                        if pd.isna(lbl) or not str(lbl).strip():
                            continue
                        chgs.append({"label": str(lbl).strip(),
                                     "open_cy": _ivn(rr.get("Opening (CY)")),
                                     "close_cy": _ivn(rr.get("Closing (CY)")),
                                     "open_py": _ivn(rr.get("Opening (PY)")),
                                     "close_py": _ivn(rr.get("Closing (PY)"))})
                    inv['materials'] = mats
                    inv['mfg_expenses'] = mfgs
                    inv['change'] = chgs
                    inv['mfg_footnotes'] = [ln.strip() for ln in mfg_fn.splitlines() if ln.strip()]
                    inv['change_footnotes'] = [ln.strip() for ln in chg_fn.splitlines() if ln.strip()]
                    fs_engine.save_inventory(company_name, invf, inv)
                    st.toast("Inventories schedules saved — see Statements → Notes", icon="✅")
                    st.rerun(scope="fragment")

            # ── Fixed Assets (Capital WIP + Intangible assets under development) ─
            with st.expander("6 — Fixed Assets (Capital WIP & Intangible under development)",
                             expanded=False):
                faf = fs_engine.get_current_fy(company_name)
                fa = fs_engine.load_fixed_assets(company_name, faf)
                st.caption("Optional. When a block is shown, its **Closing Balance drives the "
                           "Balance-Sheet figure** for that line and the movement schedule folds "
                           "into the PPE note (Note 7). When blank, the regular ledger/face "
                           "presentation is used. Only the closing affects the balance — keep it "
                           "tied to the underlying ledger.")

                _fan = lambda x: 0.0 if pd.isna(x) else float(x)
                _ROWS_FA = [("opening", "Opening Balance"),
                            ("addition", "Add: Addition during the year"),
                            ("capitalised", "Less: Capitalised during the year")]
                # Books face values (no FA override) for the TB reconciliation check.
                try:
                    _faet = fs_engine.grouping_entity_type(company_name)
                    _facyw = (st.session_state.get("fs_work")
                              or fs_engine.build_working_mapping(company_name, _faet))
                    _fapyf = fs_engine.get_previous_fy(company_name)
                    _fapyw = fs_engine.build_py_working_mapping(company_name, _faet)
                    _farep_cy = fs_reports.compute(_facyw, fs_engine.load_aux(company_name, faf), _faet)
                    _farep_py = (fs_reports.compute(_fapyw, fs_engine.load_aux(company_name, _fapyf), _faet)
                                 if _fapyw else None)
                except Exception:
                    _farep_cy = _farep_py = None
                    st.caption("ℹ️ Set up the master/grouping to enable the TB checks.")

                def _fa_books(rep, face):     # asset face -> natural positive
                    return -rep['by_face'].get(face, 0.0) if rep else 0.0

                # One compact Excel-style table PER block (rows = movement lines,
                # columns = CY / PY). Arrow keys / Tab move cell-to-cell like a sheet.
                def _fa_table(key, title, face):
                    blk = fa[key]
                    st.markdown(f"**{title}**")
                    grid = pd.DataFrame([{"Particulars": lbl,
                                          "Current Year": blk[f"{k}_cy"],
                                          "Previous Year": blk[f"{k}_py"]} for k, lbl in _ROWS_FA])
                    ed = st.data_editor(
                        grid, key=f"fs_fa_{key}", hide_index=True, width="stretch", num_rows="fixed",
                        disabled=["Particulars"],
                        column_config={"Particulars": st.column_config.TextColumn(width="large"),
                                       "Current Year": st.column_config.NumberColumn(format="%.2f"),
                                       "Previous Year": st.column_config.NumberColumn(format="%.2f")})
                    cl_cy = _fan(ed.iloc[0]["Current Year"]) + _fan(ed.iloc[1]["Current Year"]) \
                        - _fan(ed.iloc[2]["Current Year"])
                    cl_py = _fan(ed.iloc[0]["Previous Year"]) + _fan(ed.iloc[1]["Previous Year"]) \
                        - _fan(ed.iloc[2]["Previous Year"])
                    tb_cy, tb_py = _fa_books(_farep_cy, face), _fa_books(_farep_py, face)
                    recon = pd.DataFrame([
                        {"Particulars": "Closing as per schedule", "Current Year": cl_cy,
                         "Previous Year": cl_py},
                        {"Particulars": "As per Trial Balance", "Current Year": tb_cy,
                         "Previous Year": tb_py},
                        {"Particulars": "Difference", "Current Year": cl_cy - tb_cy,
                         "Previous Year": cl_py - tb_py}])
                    st.caption("Reconciliation (for your check — not printed in the note):")
                    st.dataframe(recon, hide_index=True, width="stretch",
                                 column_config={
                                     "Current Year": st.column_config.NumberColumn(format="%.2f"),
                                     "Previous Year": st.column_config.NumberColumn(format="%.2f")})
                    return ed

                ed_cwip = _fa_table('cwip', "Capital Work in Progress",
                                    "Capital work in progress")
                st.divider()
                ed_intan = _fa_table('intan_dev', "Intangible assets under development",
                                     "Intangible assets under development")
                fa_fn = st.text_area("Foot Notes for Tangible Assets & CWIP (one per line)",
                                     value="\n".join(fa.get('footnotes', [])),
                                     key="fs_fa_fn", height=68)
                if st.button("💾 Save Fixed Assets schedules", type="primary", key="fs_fa_save"):
                    for ed, key in ((ed_cwip, 'cwip'), (ed_intan, 'intan_dev')):
                        for i, (k, _l) in enumerate(_ROWS_FA):
                            fa[key][f"{k}_cy"] = _fan(ed.iloc[i]["Current Year"])
                            fa[key][f"{k}_py"] = _fan(ed.iloc[i]["Previous Year"])
                        # Filling a block implies disclosing its breakup.
                        fa[key]['disclose'] = fs_engine.fa_block_has_data(fa[key])
                    fa['footnotes'] = [ln.strip() for ln in fa_fn.splitlines() if ln.strip()]
                    fs_engine.save_fixed_assets(company_name, faf, fa)
                    st.toast("Fixed Assets schedules saved — see Statements → Notes", icon="✅")
                    st.rerun(scope="fragment")

        @st.fragment
        def _fs_partners():
            """Partners' capital schedules (Partnership only): current (+ optional fixed
            'Contribution') schedule per partner, PY totals, TB reconciliation.
            Closing = computed; green columns in the reference = editable here."""
            cy_fy = fs_engine.get_current_fy(company_name)
            pdata = fs_engine.load_partners(company_name, cy_fy)
            _ppfy = fs_engine.get_previous_fy(company_name)
            if not pdata.get('rows') and _ppfy:
                _pyp = fs_engine.load_partners(company_name, _ppfy)
                if _pyp.get('rows'):
                    # New year: carry partners + shares; opening = PY closing.
                    pdata['fixed_schedule'] = _pyp.get('fixed_schedule', False)
                    pdata['format'] = _pyp.get('format', 'Vertical')
                    pdata['rows'] = [{'name': r.get('name'), 'share': r.get('share'),
                                      'opening': fs_engine.partners_closing(r)}
                                     for r in _pyp['rows']]
                    pdata['fixed_rows'] = [{'name': r.get('name'), 'share': r.get('share'),
                                            'opening': fs_engine.partners_closing(r, True)}
                                           for r in (_pyp.get('fixed_rows') or [])]
                    fs_engine.save_partners(company_name, cy_fy, pdata)
                    pdata = fs_engine.load_partners(company_name, cy_fy)
                    st.info(f"↪️ Partners carried from {_ppfy}: opening capital = "
                            f"{_ppfy} closing.")
            st.markdown("#### 👥 Partners' capital")
            c1, c2, c3 = st.columns([1.2, 1.2, 2.6])
            fixed = c1.toggle("Fixed capital schedule", value=bool(pdata.get('fixed_schedule')),
                              key="fs_pt_fixed",
                              help="ON = two schedules: Partners' Contribution (fixed) + Current")
            fmt = c2.selectbox("Presentation", ["Vertical", "Horizontal"],
                               index=0 if pdata.get('format', 'Vertical') == 'Vertical' else 1,
                               key="fs_pt_fmt",
                               help="Vertical = partners as columns; Horizontal = partners as rows")

            # live profit (for the distribute button)
            rep = fs_reports.compute(st.session_state.get("fs_work", {}),
                                     fs_engine.load_aux(company_name, cy_fy))
            profit = rep['profit']

            _CUR_COLS = {"name": "Name of Partner", "share": "Share %",
                         "opening": "Opening Capital", "addition": "Addition",
                         "withdrawal": "Withdrawal", "interest": "Interest on Capital",
                         "remuneration": "Remuneration", "profit": "Profit/(loss)"}
            _FIX_COLS = {"name": "Name of Partner", "share": "Share %",
                         "opening": "Opening Capital", "addition": "Addition",
                         "withdrawal": "Withdrawal", "others_add": "Others (Add)",
                         "others_less": "Others (Less)"}

            def _editor(rows, cols, key):
                df = pd.DataFrame([{cols[k]: r.get(k) for k in cols} for r in rows],
                                  columns=list(cols.values()))
                if df.empty:
                    df = pd.DataFrame({v: pd.Series(dtype=('object' if k == 'name' else 'float'))
                                       for k, v in cols.items()})
                cfg = {v: st.column_config.NumberColumn(format="accounting")
                       for k, v in cols.items() if k not in ('name', 'share')}
                cfg[cols['name']] = st.column_config.TextColumn(width="medium")
                cfg[cols['share']] = st.column_config.NumberColumn(format="%.2f",
                                                                   min_value=0, max_value=100)
                ed = st.data_editor(df, num_rows="dynamic", key=key, width="stretch",
                                    hide_index=True, column_config=cfg)
                out = []
                for _, rr in ed.iterrows():
                    nm = rr.get(cols['name'])
                    if pd.isna(nm) or not str(nm).strip():
                        continue
                    row = {'name': str(nm).strip()}
                    for k, v in cols.items():
                        if k == 'name':
                            continue
                        val = rr.get(v)
                        row[k] = None if pd.isna(val) else float(val)
                    out.append(row)
                return out

            if fixed:
                st.markdown("**Partners' Contribution Account (fixed capital)**")
                fx_rows = _editor(pdata.get('fixed_rows') or [], _FIX_COLS, "fs_pt_fx")
                st.markdown("**Partners' Current Account**")
            else:
                fx_rows = []
            cur_rows = _editor(pdata.get('rows') or [], _CUR_COLS, "fs_pt_cur")

            db1, db2 = st.columns([1.4, 3.6])
            if db1.button("⚖️ Distribute profit by share", key="fs_pt_dist",
                          help=f"Fills Profit/(loss) = share% × {fs_reports.fmt_amt(profit)}"):
                for r in cur_rows:
                    r['profit'] = round((r.get('share') or 0) / 100.0 * profit, 2)
                fs_engine.save_partners(company_name, cy_fy, {
                    'fixed_schedule': fixed, 'format': fmt, 'rows': cur_rows,
                    'fixed_rows': fx_rows, 'py': pdata.get('py')})
                st.session_state.pop("fs_pt_cur", None)
                st.toast("Profit distributed & saved", icon="⚖️")
                st.rerun(scope="fragment")

            with st.expander("📅 Previous-year totals (for the Previous Year column)"):
                py = pdata.get('py') or {}
                pyc = dict(py.get('current') or {})
                pcols = st.columns(7)
                _PY_FIELDS = [("opening", "Opening"), ("addition", "Addition"),
                              ("withdrawal", "Withdrawal"), ("interest", "Interest"),
                              ("remuneration", "Remuneration"), ("profit", "Profit"),
                              ("closing", "Closing")]
                for col, (k, lbl) in zip(pcols, _PY_FIELDS):
                    cur = pyc.get(k)
                    pyc[k] = col.number_input(lbl, value=(float(cur) if cur not in (None, '')
                                                          else 0.0),
                                              key=f"fs_pt_py_{k}", step=1000.0)
                py['current'] = pyc

            # ── Reconciliation vs TB ──────────────────────────────────────────
            face = "Partners Capital Account"
            bfn = rep.get('by_face_note', {})
            tb_cur = bfn.get((face, "Partners Current Account"), 0.0)
            tb_fix = bfn.get((face, "Partners Capital Account"), 0.0)
            tb_face = rep['by_face'].get(face, 0.0)
            # profit handling mirrors statements(): add profit_to_add when capital is
            # the profit destination
            ent = fs_engine.load_entity(company_name)
            dest_cap = ent.get('options', {}).get('profit_destination') == "Partners Capital"
            extra = rep.get('profit_to_add', 0.0) if dest_cap else 0.0
            tot_close = sum(fs_engine.partners_closing(r) for r in cur_rows) + \
                sum(fs_engine.partners_closing(r, True) for r in fx_rows)
            tb_all = tb_face + extra          # credit-positive
            diff = tot_close - tb_all
            _ia = lambda v: fs_reports.fmt_amt(v, dash_zero=False)
            m1, m2, m3 = st.columns(3)
            m1.metric("Closing per schedules", _ia(tot_close))
            m2.metric("Closing per TB", _ia(tb_all))
            m3.metric("Difference", _ia(diff),
                      delta=("ties" if abs(diff) < 1 else "review"),
                      delta_color=("normal" if abs(diff) < 1 else "inverse"))
            # interest / remuneration / profit cross-checks (CY)
            int_tb = -bfn.get(("Finance costs", "Interest on Partners' Capital"), 0.0)
            rem_tb = -rep['by_face'].get("Partners remuneration", 0.0)
            int_in = sum((r.get('interest') or 0) for r in cur_rows)
            rem_in = sum((r.get('remuneration') or 0) for r in cur_rows)
            pr_in = sum((r.get('profit') or 0) for r in cur_rows)
            st.caption(f"Cross-checks (CY): interest {_ia(int_in)} vs TB {_ia(int_tb)} · "
                       f"remuneration {_ia(rem_in)} vs TB {_ia(rem_tb)} · "
                       f"profit {_ia(pr_in)} vs computed {_ia(profit)}")

            if st.button("💾 Save partners", type="primary", key="fs_pt_save"):
                fs_engine.save_partners(company_name, cy_fy, {
                    'fixed_schedule': fixed, 'format': fmt, 'rows': cur_rows,
                    'fixed_rows': fx_rows, 'py': py})
                st.toast("Partners saved — Refresh the Statements tab", icon="✅")
                st.rerun(scope="fragment")

        _is_firm = fs_engine.grouping_entity_type(company_name) == "Partnership"
        if _is_firm:
            (_vt_master, _vt_map, _vt_far, _vt_pt, _vt_check, _vt_disc,
             _vt_stmt) = st.tabs(
                ["📇 Master Data", "🗂 Grouping & adjustments", "🏭 Fixed Assets (FAR)",
                 "👥 Partners", "✅ Check", "📝 Disclosures",
                 "📄 Statements (BS / P&L / Notes)"])
            with _vt_pt:
                if _fs_ready:
                    _fs_partners()
                else:
                    st.info("⬆️ Set the **Current year** in the Master Data tab first.")
        else:
            _vt_master, _vt_map, _vt_far, _vt_check, _vt_disc, _vt_stmt = st.tabs(
                ["📇 Master Data", "🗂 Grouping & adjustments", "🏭 Fixed Assets (FAR)",
                 "✅ Check", "📝 Disclosures", "📄 Statements (BS / P&L / Notes)"])
        with _vt_master:
            _fs_master()
        with _vt_map:
            if _fs_ready:
                _fs_editor()
            else:
                st.info("⬆️ Extract a master from Tally and choose a **Current year** in the "
                        "Master Data tab to start mapping.")
        with _vt_check:
            if _fs_ready:
                _fs_check()
            else:
                st.info("⬆️ Set the **Current year** in the Master Data tab to run reconciliation "
                        "checks.")
        with _vt_far:
            if _fs_ready:
                _fs_far()
            else:
                st.info("⬆️ Set the **Current year** in the Master Data tab to maintain the "
                        "Fixed Assets Register.")
        with _vt_disc:
            _fs_disclosures()
        with _vt_stmt:
            if _fs_ready:
                _stmts = _fs_toolbar()          # main-flow: downloads work here
                if _stmts is not None:
                    _fs_viewer(_stmts)           # fragment: just the tables
            else:
                st.info("⬆️ Extract a master and set the Current year in the Master Data tab first.")


