# Ledger Scrutiny Tool — Project Guide for Claude

Standalone desktop app for CAs. Extracts data from **Tally** via ODBC, runs
scrutiny/TDS/GST engines in Python, presents results in a **Streamlit** UI.
Ships to end-users as a folder with **embedded Python 3.12.8** + Inno Setup installer.

> This project is **completely separate** from the Finbridge project. No shared
> code, config, or data.

- **Repo:** https://github.com/Deepakca-IT/Ledger_Scrutiny_Tool (`origin`)
- **Local path:** `D:\Dev\Ledger_Scrutiny_Tool`
- **Maintainer:** CA P Deepak Siddarth
- **Version:** see `version.txt`

---

## Working agreement — who decides what

The maintainer is a Chartered Accountant with deep domain knowledge but limited
coding knowledge. Respect this division:

- **Domain / accounting logic → ALWAYS consult the user first.** This includes how
  Tally data behaves (column meanings, party derivation, voucher types, group
  classification), any ledger-scrutiny rule, TDS/GST treatment, thresholds, and what
  a check should flag. Do NOT invent or assume this logic. Propose your understanding,
  get confirmation, then implement. Keep checking until the user says you've internalized
  their analytical reasoning.
- **Technical / mechanical → proceed without asking.** UI, refactors, compiling,
  file/folder mechanics, the build, debugging tracebacks, dependency issues, git
  mechanics. The user trusts these to you.
- **Exception — shipping to users:** publishing a GitHub release that a future updater
  then distributes to all installed copies is hard to reverse. Do the mechanics, but
  CHECKPOINT with the user before it goes live. Local commits / test builds: just do them.

---

## Architecture & data flow

Tally is only touched at the **extract** step. Everything downstream is
**file-based** — it reads/writes CSVs and Excel under the user's Documents folder.
This is what makes most of the app testable offline (see Testing).

All paths below live under `years/<fy>/` and resolve via `paths.py`; every engine
entry point now takes an `fy` arg (`main(company, fy, …)`).
```
Tally (ODBC, DSN=TallyODBC64_9400, port 9400)
   │  engines/extract_engine.py   (main(company,fy,branch,…), extract_prev_year_master, extract_nce_master, extract_msme_verify)
   ▼
years/<fy>/extracted/   *_MasterData.csv, *_Transactions.csv
   │  engines/consolidate_engine.py   (main(company,fy), consolidate_prev_year(company,fy))
   ▼
years/<fy>/consolidated/   Conso_MasterData.csv, Transactions_*.csv (ALL voucher lines), RP_Ledgers.json, Filter_Options.json
   │  engines/ls_runner.py → engines/ls_engine.py   (run_ls_for_company(company,fy,…) → LSEngine)
   │  tds_engine.py / tds_rules_engine.py           (TDS analysis; fy-scoped)
   │  gst_engine.py, viewer_engine.py               (GST checks, ledger viewer; fy-scoped)
   │  msme_engine.py (43B(h)), clause44_engine.py (GST expenditure break-up)
   ▼
years/<fy>/analysis/   Ledger_Scrutiny_Report.xlsx, TDS_&Expense_Analysis_*.xlsx, PAN_Override.xlsx
```

### Per-company data location — YEAR-SCOPED (2026-06 foundation change, NOT in repo)
Every company now holds **one folder per tax year**. The active company **and**
tax year are chosen in the header; everything (extract → scrutiny → NCE → MSME →
Clause 44) happens **within the selected year**.
```
%USERPROFILE%\Documents\LSTool\data\<CompanyName>\
    entity.json                 # company-level: entity master + current_fy/previous_fy pointers
    layout_migrated.flag        # set once flat→nested migration has run
    years\<fy>\                 # e.g. years\2025-26\
        extracted\   consolidated\   analysis\
        financials\  (+ masters\)    msme\
        config\      gst_selection.json  tds_selection.json  excluded_parties.json
                     related_parties.json  analysis_info.json  tds_rules.json  clause44_*.json
```
- **`paths.py`** is the single source of truth for every path: `year_dir`, `extracted_dir`,
  `consolidated_dir`, `analysis_dir`, `financials_dir`, `masters_dir`, `msme_dir`,
  `config_dir`/`config_path(company, fy, name)`, `list_years`, `ensure_year`,
  `latest_year_before`, `seed_config_from` (carries config forward to a new year). **All
  engines import `paths` and take an `fy` arg.** `entity.json` stays at the company root
  (it indexes years + holds the FY pointers); everything else is per-year.
- **LAN multi-user (Phase A) — configurable data root.** `paths.get_data_root()` reads a
  per-machine `data_location.json` beside the module (install dir, `%LOCALAPPDATA%\LS_Tool`);
  `LSTOOL_ROOT` → `BASE = LSTOOL_ROOT/data`; falls back to `~/Documents/LSTool` when unset (so
  standalone installs are unchanged). `set_data_root()`/`is_data_location_configured()`/
  `data_location_file()` round it out. The hardcoded roots in `fs_engine.BASE_DATA_DIR`,
  `streamlit_app.BASE_DATA_DIR`, `tds_rules_engine.SYSTEM_SECTIONS/WORD_RULES` were rerouted
  through `paths`; `profile_engine` already derives from `paths.BASE.parent`. **Shared** on the
  LAN folder: `data/`, `profile.json`, `system_sections.json`, `word_rules.json`. **Stays local
  per-PC:** `temp_analysis`. UI: sidebar **🗂 Data
  folder** dialog (`_data_location_dialog`) — host enters a local path (`C:\LSTool`) it then
  shares; LAN PCs enter the UNC (`\\HOST\LSTool`); change takes effect on restart.
- **Deployment model (LAN):** ONE installer for every PC (no separate server build); difference is
  config only. Host shares its `LSTool` folder and points its app at the local path; LAN PCs point
  at `\\HOST\LSTool` + extract from their OWN local Tally (`localhost:9400`). Tally Gold is
  supported. **The host share must grant write at
  BOTH layers** (Sharing→**Change** + Security/NTFS→**Modify**) or writes like `entity.json` fail
  with `PermissionError [Errno 13]`; "Run as administrator" on the client does NOT help (network
  access is the host's call, and elevation can drop saved share credentials).
- **Phase B — LAN write safety (built 2026-06).** All app-data JSON saves go through
  `paths.atomic_write_json(path, obj)` (temp file in same dir + `os.fsync` + `os.replace`), so a
  reader/another PC never sees a torn or empty file on the share. Routed: `fs_engine` (entity,
  grouping, py-override, inventory, fixed_assets, far, aux, checks, partners, policies, tr_ageing,
  owners_capital), `company_info` (`_save_list`, analysis_info), `profile_engine`, `msme_engine`
  (config/master/pending), `clause44_engine` (config/suppliers), `tds_rules_engine` (word_rules,
  system_sections, per-company rules). Plus a **soft per-company edit lock** (advisory, never
  blocks): `paths.acquire/release/check_company_lock` write `data/<company>/.edit_lock.json`
  `{user,host,ts}`; `streamlit_app` refreshes it (throttled 60s) on the active company after
  `render_topbar` and shows a yellow warning if another PC holds a FRESH lock. Locks older than
  `paths.LOCK_STALE_SECONDS` (180s) are ignored (crash-safe); same user+host never self-warns.
- **Open-source edition (2026-11):** no licence check, no token, no compiled modules. `dev_mode.txt`
  (git-ignored) only shows in-development features.
- **Updates (`updater.py`):** once a day the app reads the latest public GitHub release, downloads
  `LS_Tool_update_<ver>.zip`, checks its `.sha256`, refuses any file outside `updater.ALLOWED` (never
  launchers or Python), and stages it in `update_staging/` + `update_ready.txt`. `run.bat`/`run_app.bat`
  copy it in at the next launch. If `manifest.json`'s requirements hash differs from the installed
  `requirements.txt`, the app asks for the full installer instead. A git checkout (`.git` present)
  never updates itself. Tests: `tests\updater_test.py` (local fake GitHub).
- **`migrate.py`** — idempotent flat→nested migration, run once per session at startup
  (`migrate_all()`). Infers the scrutiny year from consolidated transaction dates; distributes
  the year-suffixed NCE/MSME files by their own year; moves `entity.json` to root. **Never
  deletes a source until the destination is confirmed** (no data-loss); re-runs while any flat
  leftover remains, so partial moves self-heal. NB: `aux_<fy>.json` → `aux_data.json` (the bare
  name `aux` is a **reserved Windows device name** and fails to write).
- New-year creation seeds config forward from the prior year (TDS rules, ledger selections,
  excluded/related parties, policies) via `paths.seed_config_from`.

Never name client companies in this repository. Test with made-up data only.

### Financials (NCE) feature — in progress (big feature)
"🧾 Financials (NCE)" tab (tab7) prepares ICAI **Non-Corporate-Entity** statements
(Proprietor / Partnership). We build our own layouts.

**Core:** each TB ledger gets a 3-level grouping **Face → Note → Sub-Note**; BS/P&L/Notes aggregate
TB amounts by those. Sign convention: **Debit = negative, Credit = positive**.
**Sub-Note is a real third presentation level** in the notes (not a suffix): in `statements`, each
note-line builds `ln['subs']` — but *only when ≥1 ledger under that note-line carries a sub-note*;
ledgers with a blank sub-note collapse into **"Others"**. When `subs` is present the note-line is a
header (no amount) and the values sit on the indented sub-note rows; otherwise the line stays flat.
`one_note_html` and the Excel Notes sheet render the three levels (note 18px → sub-note 36px → ledger
54px, vs flat note 18px → ledger 36px); the old `— <subnote>` ledger-name suffix is removed.

**⚠️ Fully SEPARATE from Ledger Scrutiny (LS).** LS runs mid-year (part-period), so NCE does its
**own master-only extraction** (balances, no transactions), tagged by FY, and **never** reads
`Conso_MasterData.csv`.

> **⚠️ 2026-06 year-foundation update (supersedes file paths below):** NCE files now live under
> `years/<fy>/financials/` (resolved via `paths.py`), **not** `data/<company>/financials/`.
> Per-year filenames dropped their `_<fy>` suffix: `grouping.json`, `aux_data.json` (NOT `aux.json`
> — reserved name), `far.json`, `checks.json`, `partners.json`, `policies.json`, `masters/master.csv`.
> `entity.json` moved to the **company root**. The roll-over / set-Current-Previous UI is **gone** —
> the **header's tax-year picker** drives `current_fy`; `previous_fy` = year−1; `render_nce(company,
> active_fy)` syncs them and auto-derives the period (CY/PY ended 31-Mar). `_migrate_legacy_groupings`
> is removed (the global `migrate.py` handles old layouts). Master Data expanders default collapsed.
> The descriptions below remain accurate for *logic*; only the paths/year-flow changed.

**Modules:**
- `fs_grouping.py` — vocabulary `FACE_NOTE_VOCAB`/`FACE_LIST`/`ALL_NOTES` (**user-supplied master,
  2026-06**: new face names e.g. "Property Plant and Equipment", Trade payables split into MSME /
  others, new faces HO Branch Account / Direct Expenses / Partners remuneration / Prior Period Item /
  discontinuing-operation items / Intangible assets under development / Capital work in progress);
  `default_grouping(...)` auto-classifies ~99% of ledgers (Tally group + name keywords + balance
  sign; abnormal balances → Advances from Customers / Advances to Creditors). **`SPECIFY_L3`
  ("Specify at Level 3") + `is_specify_l3(note)`**: such notes make the Sub-Note MANDATORY and the
  sub-note text is displayed AT NOTE LEVEL (fold in `fs_reports._fold_l3` inside `build_rows`; UI
  blocks Apply with empty sub-note; `default_grouping` uses the ledger name as the sub-note).
  **`FACE_MIGRATE` + `migrate_face_note(face, note)`**: upgrades saved old-vocab groupings on load
  (applied in `fs_engine.load_grouping/load_grouping_py/load_aux`; Trade Payables split by note
  keyword). `FACE_SECTION`+`face_section()`; statement order `BS_LAYOUT`, `PL_INCOME/PL_EXPENSES/
  PL_EXCEPTIONAL/PL_TAX` (HO Branch Account sits in Current assets — review). Presentation
  registries `THEMES`/`BORDERS`/`FONTS` (+`ROUND_OFF_OPTIONS`,`ENTITY_TYPE_OPTIONS`,
  `DESIGNATION_OPTIONS`). Constants now: `PROFIT_FACE`="Reserves and surplus" (note "Profit & Loss
  Account"), partners face "Partners Capital Account", `CHANGES_FACE`="Change in Inventories of
  work in progress and finished goods", FAR faces "Property Plant and Equipment"/"Intangible assets".
- `fs_ui.py` — **the whole NCE division UI** (`render_nce(company_name)`: all fragments — Master
  Data, Grouping, FAR, Check, Disclosures, Statements viewer). Split out of `streamlit_app.py`
  (which now only does `if _dev: with tab7: fs_ui.render_nce(company_name)`) so the main file stays
  small and this logic stays separate.
- `fs_policies.py` — prefilled **Disclosures** defaults: `DEFAULT_ENTITY_INFO` (Note 1) and
  `DEFAULT_POLICIES` (Note 2 = ordered `(key, head, default_disclose, text)` of standard ICAI
  accounting policies, matching the reference sheet), plus `DEFAULT_TABLES` (Inventories valuation
  sub-table). Phase-1 of the Disclosures subsystem (policies only; other disclosure heads later).
- `engines/extract_engine.py::extract_nce_master(company, fy)` — master-only pull (shared helper
  `_pull_ledger_master`, also used by LS `extract_prev_year_master`) → `financials/masters/master_<fy>.csv`.
- `fs_engine.py` — data layer under `data/<company>/financials/`: `entity.json` (**nested master
  schema** entity/period/signatories/sign/auditor/options/presentation/print **+ `current_fy`/
  `previous_fy` pointers**; `load_entity` normalises old flat keys → nested), `masters/master_<fy>.csv`
  (one per FY, history kept),
  **`grouping_<fy>.json` (FY-tagged, one per year — full history like masters; 2026-06 redesign)**,
  `aux_<fy>.json` ({opening_stock,
  closing_stock, adjustments[]}). Helpers: FY pointers `get/set_current_fy`,`get/set_previous_fy`,
  `available_fy_choices`,`list_master_fys`; `tb_available` (current_fy set AND file exists);
  `load_tb(company, fy=None)` (excludes NIL-closing, pandas-3.0 `fillna('')`); `load_py_closing`;
  `load_aux/save_aux`,`default_opening_stock` (= prev FY closing); `checks_path/load_checks/save_checks`
  (reconciliation comments, per FY); `policies_path/load_policies/save_policies` (**Disclosures**:
  `policies.json` per company, carried forward — resolves `fs_policies` defaults against saved
  overrides so new heads always appear; entity_info + ordered policies with disclose/text/table).
  `build_working_mapping`
  **carry-forward chain**: grouping_<cy> (`saved`) → grouping_<py> same-name (`carry`) →
  `default_grouping` (`default`); +sign-flip for Sundry Debtors/Creditors (`resign`); attaches
  `py_closing`. `build_py_working_mapping` (comparative, reads grouping_<previous_fy>).
  **NO roll-over button (removed 2026-06)** — `load_grouping(company, fy=None)` /
  `save_grouping(company, mapping, fy=None)` are FY-aware. **PY regrouping never mutates the prior
  year's file:** `load_grouping_py` = the previous-FY grouping (read-only base) **merged with a
  current-year override** (`grouping_py_override.json` in THIS year's financials folder, override wins
  per ledger); `save_grouping_py` writes ONLY that override (`save_grouping_py_override`). So "Edit
  previous-year grouping" in the current year changes comparatives only — switching the FY picker back
  to the prior year shows its original, untouched figures. `_migrate_legacy_groupings` renames old
  grouping.json/grouping_py.json →
  FY-tagged on first load. New year = extract new FY + set Current/Previous pointers; everything
  (TB comparative, grouping carry, FAR auto-seed, partners carry + PY column) auto-fetches from the
  previous FY's saved files. `partners_py_totals(company, pfy, fixed)` = auto PY column when manual
  PY totals are blank; the Partners tab auto-seeds a new year (names/shares carried, opening = PY
  closing); the FAR tab auto-seeds opening WDV from PY closing when the year's register is empty.
  Entity helpers: `grouping_entity_type` (rich type → Proprietor/Partnership), `period_header`
  (→ "31 March 2026"), `units` (round-off → divisor+label).
- `fs_reports.py` — `compute(work, aux)` aggregates rows (+injected stock +adjustments) by section →
  `profit`, totals, `difference`. `statements(company, entity_type, work_override=None)` builds
  **BS / P&L / Notes** with **CY+PY** columns, ordered per the layouts, auto-numbered Notes; consumes
  the master for header/period column-dates, **units rounding** (In Rs/'000/Lakhs), notes-start,
  hide-zero faces, and **profit_destination** (Reserves vs Partners'/Owner's Capital). Renderers
  `themed_css`/`statement_html`/`notes_html`/`signature_html` (auditor + signatory block, footers)
  apply theme/border/font/green-CY-column. Exporters: `build_excel` (openpyxl, theme-aware),
  `build_html` (print-ready standalone → browser Save-as-PDF).

**Stock (not in Tally ledgers):** user enters Opening & Closing stock (positive, stored absolute).
Inject **Inventories** asset = `-closing` (BS) and **Changes in inventories** = `closing-opening`
(P&L). Their net (`-opening`) cancels the TB's opening-stock shortfall → books tie when entered
opening = real carried stock. Single figure for MVP (RM/WIP/FG split deferred).

**Profit double-count + depreciation-adjustment fix (auto):** Tally's "Profit & Loss A/c" is a computed
ledger whose closing often already includes current-year profit (which then sits in Reserves/Capital).
`compute()` decides how much profit to **transfer into the surplus face** so the BS ties AND the
brought-forward stays put. Quantities (all signed, debit-negative):
- `base_profit` = P&L of the ORIGINAL books (`kind != 'adjustment'`, i.e. ledgers + stock) = the profit
  Tally already rolled into its extracted capital (a tool-side adjustment was never posted in Tally).
- `bs_signed` = asset + liability + equity across **all** rows.
- Two hypotheses, pick whichever ties (`|diff|` smaller):
  **includes** → `profit_to_add = profit − base_profit`, `difference = bs_signed + that`, `baked = base_profit`, `add_profit=False`;
  **excludes** → `profit_to_add = profit`, `difference = bs_signed + profit`, `baked = 0`, `add_profit=True`.
- `funds = equity + liability + profit_to_add`; surplus face value = `by_face[surplus] + profit_to_add`.

**Why `profit − base_profit` (not full profit):** a Dr-P&L / Cr-asset adjustment (e.g. FAR depreciation
of D via the Adjustments table) makes `profit_to_add` go **negative by exactly −D**, pulling the surplus
down by D to match the asset reduction → BS still ties and **b/f (= surplus − profit) is unchanged**.
Verified: a 2-leg depreciation adjustment lowers surplus and profit by the same amount, while
b/f and the difference stay unchanged. **Bug history (2026-06):** (1) original `base_raw`/`includes`
heuristic excluded adjustments and misclassified an already-tied BS → "out of balance by the profit";
(2) a `bs_signed`-only interim fix balanced the no-adjustment case but couldn't balance includes-case +
tool depreciation (capital held full profit, adjustment couldn't pull it down). The two-hypothesis
`base_profit` test handles all four cases (includes/excludes × with/without dep adjustment). `_bf` and
`_byface_with_profit` add `profit_to_add` (can be negative). Reserves note = movement schedule
(b/f + profit = closing).

**Indian number format everywhere:** `fs_reports.fmt_amt` (Indian comma grouping, parentheses for
negatives, no currency symbol) is the canonical formatter — used by statements, Check tab and the FAR
tab metrics (`dash_zero=False` for metrics so 0 shows "0"). The FAR computed-preview carries a **Total**
row (incl. depreciation-for-the-year sum) and a dedicated "Depreciation for the year" metric.

**Cross-reference hyperlinks (export only):** `build_html` sets `meta['link_xref']=True`; BS/P&L note
numbers become `<a href='#note-N'>` and each note title is a back-link to `#stmt-bs`/`#stmt-pl`
(`_note_title_html`; target by `fg.face_section`). Works in the print/PDF HTML (one page); the on-screen
viewer keeps the `id` anchors but no links because BS/P&L/Notes are separate sub-tabs (anchors can't
cross Streamlit tabs).

**UI (done):** Financials tab = three inner tabs:
- **📇 Master Data** (`_fs_master`): compact, **collapsed sectioned expanders** — Years & roll-over |
  Entity & period | Signatories & sign-off | Auditor | Options/presentation/print — each a tight
  3-col grid. Period / sign / report dates use **`st.date_input`** (stored back as day·month·year).
  One **Save master data** button writes the nested `entity.json`. Widget keys reset on company change.
- **🗂 Grouping & adjustments** (`_fs_editor`, in `st.fragment` for perf): balance-check banner +
  Profit; **Step 2 — Stock & adjustments** (2 number-inputs + small `st.data_editor`, separate from
  the big grid so it stays fast); filters (Primary/Parent/Face/Note) → tick rows → cascading
  Face→Note→Sub-Note → **Apply** (clears selection) → **Save**; Closing + PY Closing columns; PY
  grouping columns read-only with an "Edit previous-year grouping" toggle.
- **📄 Statements** (`_fs_viewer`): renders BS/P&L/Notes (CY+PY) as HTML, warnings, **🔄 Refresh**
  button (separate fragments don't auto-refresh — click after edits), **⬇ Excel** + **⬇ PDF/Print**.
  Reflects live in-memory grouping via `statements(..., work_override=st.session_state['fs_work'])`
  and **saved** stock/adjustments. **Notes sub-tab** has two toggles: **🔍 Show ledger details**
  (annexure — each note's constituent ledgers, via `statements` attaching `note['ledgers']` +
  `notes_html(..., show_ledgers=True)`) and **✏️ Edit grouping** (a selectable annexure `st.dataframe`
  — scales to 1000s — with **Statement (BS/P&L) + Face + search filters** to narrow to the note being
  reviewed; row-click opens an `st.dialog` with cascading Face→Note→Sub-Note → **Apply** writes
  `grouping.json` instantly + updates `fs_work`, reflected in the Grouping tab. Selection clears on
  filter change to avoid opening the wrong ledger). **Auto-jump:** in view mode each note title has a
  ✏️ pencil (`fs_reports.notes_header_html`/`one_note_html` split the renderer so titles are Streamlit
  elements); clicking it sets `fs_notes_edit_req` (applied at the top of the tab *before* widgets are
  created, since a widget key can't be modified after instantiation) → opens Edit mode pre-filtered to
  that note's Face + statement.

**Fixed Assets Register (FAR — Income-tax depreciation):** 4th Financials inner tab **🏭 Fixed Assets
(FAR)** (`_fs_far()` fragment). Depreciation is **never extracted from Tally** — the user maintains a
per-FY asset register (manual first year, rolls forward after). Block-rate master in `fs_grouping.py`
(`FAR_CATEGORIES`, `FAR_RATES`, `FAR_FACE`, `far_blocks/far_rate/far_face`). Store in `fs_engine.py`
(per-FY `far_<fy>.json`: `far_path`, `load_far`, `save_far`, `far_default_row`, `FAR_INPUT_FIELDS`).
Compute in `fs_reports.py` `compute_far(rows)` — IT-Act WDV block method: rate per row or block default;
`opening_net = opening_gross − opening_accum` (accum **optional**, blank → straight depreciation); full
rate on additions used ≥180d, **half** on <180d; `total_dep = dep + manual_adj`; rolls up by
(category→block→face). UI columns: green = user-fill (name/category/block/rate-override/opening
gross/additions/sale/opening accum/manual adj), computed preview is read-only; **reconciliation metric**
FAR closing-net vs fixed-assets-per-TB; **↪️ Seed opening from PY** (`far_seed_rows`). In `statements()`,
when `options.depreciation == "FAR IT"` and FAR rows exist, the PPE / Intangible notes get a `note['far']`
payload rendered by `far_table_html` (wide **Gross Block / Depreciation / Net Block** schedule; Net-Block
PY column = `n_open` = prior closing) — also in `build_excel` (`_write_far_excel`) and `build_html`.
**FAR is presentation-only by design** — it drives the Notes (PPE closing + depreciation for the year);
the Balance Sheet PPE and P&L Depreciation stay from the TB, so gaps are **expected** and reconciled
**manually** (no auto-injection into P&L/BS — deliberately rejected as risky).

**✅ Check tab** (5th Financials inner tab, `_fs_check()` fragment): a reconciliation worksheet.
`fs_reports.reconciliation(company, work_override=)` compares Notes/FAR vs books (TB) for **PPE net**,
**Intangibles net** and **Depreciation**, each with CY + PY + difference (`far_*` − `books_*`, present-
signed). Status ✅/⚠️ per |diff|<1. Editable **Comment** per row + free-form **custom checks**, persisted
per FY in `checks_<fy>.json` (`fs_engine.checks_path/load_checks/save_checks`: `{comments:{key:txt},
custom:[...]}`). Workflow: gap shows here → user books an adjustment row under *Grouping & adjustments*
(the two FAR gaps are equal & opposite = the depreciation) → differences return to zero. The FAR tab's
own reconciliation metric points here.

**📝 Disclosures tab** (6th Financials inner tab, `_fs_disclosures()` fragment) — **Phase 1 = Policies**.
Edits **Note 1 (Entity Information)** + **Note 2 (Significant Accounting Policies)**: a `st.data_editor`
of all heads with a **Disclose** checkbox (quick toggle), plus a selectbox → `text_area` to edit the
chosen head's prefilled text (and the Inventories valuation sub-table). `pol` is held in
`st.session_state['fs_pol']` (reloaded on company change) and mutated in place, so switching heads keeps
edits; **💾 Save policies** → `save_policies`. Rendering: `fs_reports.resolve_policy_notes(company)`
keeps only **disclosed heads that have text/table**, letters them a, b, c… (re-flows automatically);
`policies_html(meta, pol)` renders Notes 1–2 (no section header — caller emits `notes_header_html` once).
Order in the report: **BS → P&L → [Notes: 1 Entity, 2 Policies, 3+ face notes]** (face notes already
start at `notes_start`=3). Wired into the on-screen Notes viewer (sv3, before the face-note loop),
`build_html` (`notes_html(..., policies=)`), and `build_excel` (Notes sheet prepend). Policies are
**carried forward** (per-company `policies.json`). Next phase: other disclosure heads + depreciation
useful-life / contingent-liabilities tables + per-year amounts.

**Disclosures dropdown headers** (entry screens, each an `st.expander`): **1 Entity Information**,
**2 Significant Accounting Policies**, **3 Trade Receivables Ageing** (`tr_ageing.json`, FIFO auto-fetch,
2-bucket), **4 Owner's Capital Account** (Proprietor only, `owners_capital.json`), **5 Inventories**
(all entity types, `inventory.json`). Each carries a TB-reconciliation panel (Total as per schedule / As
per Trial Balance / Difference) shown **only on the entry screen — never printed in the note**; blank
rows suppressed in output.

**Inventories disclosure** (`fs_engine.load_inventory/save_inventory/inventory_default/inventory_totals`,
per-FY `config/inventory.json`). Two user-typed sub-forms with CY+PY columns: **A · Cost of Material
Consumed** (material categories — Opening/Purchases/Closing → O+P−C; + Other Manufacturing Expenses rows
with an ITR-Group label) and **B · Change in Inventories of WIP & FG** (per stock type Opening/Closing).
Optional — when `disclose` is off the legacy single Opening/Closing-stock (Step 2 `aux`) presentation is
used. When on, it **replaces** that injection: `fs_reports.build_rows(work, aux, inv, inv_side)` injects
**only the stock movement** (Inventories asset = −ΣClosing; Cost-of-material line = Cmat−Omat;
Change-in-inv line = Cfg−Ofg), net = −ΣOpening → **balanced by construction**; purchases stay in the TB
(map purchase ledgers to the Cost face and reconcile via the Difference row). `statements()` attaches
`n['inventory']` (Note: Inventories BS breakdown), `n['cost_material']` (Cost of material consumed),
`n['change_inv']` (Change in inventories) and the renderers (`inventory_html/cost_material_html/
change_inv_html`, `inventory_pdf/cost_material_pdf/change_inv_pdf`, `_write_inventory/cost/change_excel`)
replace those three note bodies. PY balance uses the PY year's own `inventory.json` if present, else the
CY form's typed PY columns. **PY carry-forward:** `load_inventory`/`load_fixed_assets` take `carry=True`
and, when a `paths.latest_year_before` FY exists, pre-fill the comparative (PY) cells from that prior
year's saved **CY** figures (`_carry_py_inventory`/`_carry_py_fixed_assets`, matched by label) — **blanks
only, never overwriting a typed PY**, blank when no prior year exists. Source files are read with
`carry=False` to avoid chained recursion.

**Fixed Assets disclosure** (`fs_engine.load_fixed_assets/save_fixed_assets/fixed_assets_default/
fa_closing/fixed_assets_has_data`, per-FY `config/fixed_assets.json`). Two movement blocks — **Capital
WIP** and **Intangible assets under development** — each Opening + Addition − Capitalised = Closing
(CY+PY) + shared footnotes. UI expander **6 — Fixed Assets** uses ONE compact Excel-style `st.data_editor`
grid (rows = movement lines, cols = each block's CY/PY; arrow-key nav) + two Disclose toggles (auto-on
once figures exist) — replaced the bulky number_input form. `CWIP_FACE` / `INTAN_DEV_FACE` **always fold
into the PPE note (Note 7)** — never a separate note number (when PPE present). They show as a single
**(ii)/(iii) net line from the TB face value**; the Opening/Addition/Capitalised/Closing **detail appears
only when that block's disclosure is filled**. When disclosed, the closing **DRIVES** the face:
`fs_reports.build_rows(..., fa, fa_side)` drops the ledger rows for the face and injects the schedule
closing (override). Payload `n['fixed_assets']` carries per block `present`+`net_cy/py` (always) and
`disclose`+movement fields (when filled); renderers `fixed_assets_html/_pdf/_excel` append after the
FAR/normal PPE table. `roman_of_face`/`fa_face_val` captured during the BS loop drive the net rows.
**FAR tab** has a `🔄 Refresh 'Fixed assets per TB'` button that rebuilds `st.session_state['fs_work']`
from the saved grouping so the TB metric reflects the latest Grouping & adjustments edits.

**BS_LAYOUT is now 3-level**: `(group, [(sub_label, lettered, [(subsub_label|None, roman, [faces])])])`.
`lettered`→items get **(a)/(b)/(c)…**; `roman`→faces in a named sub-sub group get **(i)/(ii)/(iii)…**;
both assigned **dynamically to visible (non-zero) faces** so hidden faces leave no gap. Non-current assets
render as **(1) Non-current assets → (a) Property, Plant and Equipment and Intangible Assets [(i) PPE,
(ii) CWIP, (iii) Intangible-under-dev] → (b)/(c)… other faces**. BS face rows now carry `face` (unprefixed,
for the Excel note↔BS back-link via `is_face`) + `label` (display, may be roman/letter-prefixed); levels
0=group,1=sub,2=sub-sub/bare-face,3=roman-face (renderers indent by `level`).

**Round-off tie (presentation only)** — after the BS loop in `statements()`, a block segments `bs_rows`
into top-level groups (header `cy is None` / `is_face` rows / `Total —` row) and **rounds each line to the
display precision** (`_ndp` = 2 if `pres.two_decimals` else 0), then **absorbs the rounding residue into
the largest-abs line** of each side so `Σ round(lines) == round(side total)`. **Cross-side:** when the two
sides differ by ≤ 1.5 display units it snaps both to `max(rounded totals)` (the smaller side's largest line
soaks the ₹1) so **Assets == Equity+Liabilities exactly**; a larger gap is left visible (real imbalance,
not rounding). Imported figures are never touched — only the display-scaled `bs_rows` values are rewritten,
so all three renderers tie. Trade-off: the nudged face line can differ by 1 unit from its own note total.

**👥 Partners tab** (Partnership entities only; `_fs_partners()` fragment, tab shown only when
`grouping_entity_type == "Partnership"`). Per-FY store `partners_<fy>.json`
(`fs_engine.partners_path/load_partners/save_partners`, `PARTNER_FIELDS`/`PARTNER_FIXED_FIELDS`,
`partners_closing(row, fixed)`: current = open+add−wdr+interest+remuneration+profit; fixed =
open+add−wdr+others_add−others_less). UI: fixed-schedule toggle (adds the Partners' Contribution
editor), Vertical/Horizontal presentation pick, per-partner `st.data_editor`s (green columns of the
reference = editable; closing computed), **⚖️ Distribute profit by share** button, PY-totals expander,
recon metrics (schedules' closing vs TB `Partners Capital Account` face ± `profit_to_add` when
profit_destination = Partners Capital) + interest/remuneration/profit cross-check caption. Output:
`statements()` attaches `note['partners']` payload (scaled rows/totals/py) to the "Partners Capital
Account" note → `partners_table_html` renders Vertical (partners as columns) or Horizontal (partners
as rows) with Total + Previous Year; `one_note_html` dispatches like FAR; Excel via
`_write_partners_excel` (always horizontal in Excel); included in `build_html`.

**Year flow (no roll-over):** first year — extract FY → set Current → map → done (saved as
grouping_<fy>.json). Next year — extract new FY → set it Current + old one Previous → same-name
ledgers carry last year's grouping automatically (review only new ones); comparatives, FAR opening,
partners opening + PY columns all auto-fetch from the previous FY's files. Any past year can be
re-opened by re-pointing Current/Previous; PY grouping is also editable in place via the Edit-PY
toggle.

**Still TODO (roadmap):** Notes text (Note 1 entity info, Note 2 significant accounting policies);
FAR Summary-Manual mode + additional depreciation / STCG + roll the Check-tab adjustment into a
one-click "book this gap" button; ITR 3/5 grouping + Annexures; optional Cash Flow,
Branch/unit consolidation, Analytics, Tax Workings; native one-click PDF (needs a bundled lib —
only openpyxl ships now).

### Source files (repo root)
- `streamlit_app.py` — the whole UI (single file, app entry point). **Sidebar + top-bar shell**
  (see UI navigation below) + one `if _page == "<id>":` block per module.
- `paths.py` — **year-scoped path resolver** (single source of truth).
- `migrate.py` — one-time flat→nested migration.
- `tds_engine.py`, `tds_rules_engine.py`, `gst_engine.py`, `viewer_engine.py` — domain engines (fy-scoped).
- `msme_engine.py` — 43B(h) MSME disallowance working paper (fy-scoped, supplier master + FIFO ageing).
- `clause44_engine.py` — Form 3CD Clause 44 GST expenditure break-up.
- `company_info.py` — per-year config getters/setters (now take `fy`).
- `fs_*.py` + `fs_ui.py` — NCE Financials (see that section).
- `version.txt`, `changelog.txt` — release version and notes.
- `engines/` — Tally extraction & consolidation + ledger-scrutiny engine (all take `fy`).

### UI navigation (2026-06 redesign — left sidebar, not top tabs)
`streamlit_app.py` renders a **left sidebar** (`render_sidebar` → `company_name, page`) +
a **main-area top bar** (`render_topbar(company_name)` → `active_fy`), then dispatches each
module with `if _page == "<id>":` (page ids: extract / analysis / tdsrules / scrutiny /
viewer / related / msme / clause44 / nce). The old `st.tabs` layout is gone.
- **Sidebar** = brand wordmark, `COMPANY WORKSPACE` selectbox, **⚙️ Manage companies & years**
  dialog (`_manage_dialog`: create / add-year / delete — uses `_pending_company`/`_pending_fy`
  + `st.rerun` so it never sets a widget key after instantiation), grouped nav buttons
  (`_NAV_GROUPS`: WORKFLOW = Extract/Analysis/TDS Rules · AUDIT MODULES = Scrutiny/TDS
  Compliance/Related Parties/43B(h) MSME/Clause 44 · FINANCIALS = NCE, dev-only), version +
  Update at the bottom. Active page = button `type="primary"`.
- **Top bar** = entity name + type, **Financial Year selectbox** (drives `active_fy`, sets
  `fs_engine.set_current_fy/previous_fy`), **🔄 Sync** (jumps to Extract).
- **Design system** (CSS in the big `<style>`): deep-ink navy sidebar + **amber `#d6a14a`** accent
  (active-nav spine, logo, avatar); flat brand-navy buttons (no gradients); system fonts (NOT Inter);
  monospace + tabular numerals for figures; **compact forms** (labels 11px, input/select boxes ~32px —
  shrink the baseweb wrapper, not just the input). Keep `header` visible (don't `visibility:hidden` it)
  or the sidebar expand arrow disappears; pin sidebar width only when `aria-expanded="true"` so
  collapsing widens the main area.
- Widget-key rule (bit us repeatedly): you **cannot** assign `st.session_state[k]` after the widget
  with key `k` has rendered this run. Use an on-click callback (runs first) or a `_pending_*` key
  applied before the widget + `st.rerun`.

---

## Environment

- **Ship + test interpreter:** the embedded `python\python.exe` (Python 3.12.8).
  Always test with this, not system Python — test env must equal ship env.
- Key deps in the embedded env: **streamlit 1.57.0, pandas 3.0.3, pyodbc 5.3.0, openpyxl**.
- ⚠️ **pandas 3.0** — major version with breaking changes (copy-on-write default,
  pyarrow-backed strings → `dtype: str` / `ArrowStringArray`, removed deprecated APIs).
  Code written before pandas 3 can silently misbehave. Watch for this when debugging.

---

## Running

End-user / normal run (launches Streamlit in browser):
```
run.bat        # = python\python.exe -m streamlit run streamlit_app.py
```

⚠️ DEV GOTCHA: Streamlit only hot-reloads the MAIN script (`streamlit_app.py`). When you
edit an imported module (`engines/ls_engine.py`, `tds_engine.py`, etc.), the running
`run.bat` process keeps the OLD module cached in memory — re-running a feature uses stale
code. After editing any engine, **fully close and reopen `run.bat`** before testing.

---

## Testing (how Claude verifies changes)

The app has ONE external dependency — **live Tally** — and only the extract step
needs it. Split work accordingly:

**Layer 1 — compile/import check (any time, no Tally).** After every edit:
```
cd "D:\Dev\Ledger_Scrutiny_Tool"
python\python.exe -m py_compile streamlit_app.py paths.py migrate.py tds_engine.py tds_rules_engine.py gst_engine.py viewer_engine.py msme_engine.py clause44_engine.py company_info.py fs_engine.py fs_ui.py engines\*.py
```

**Layer 2 — run engines offline against real sample data (no Tally).**
Because the pipeline is file-based and sample CSVs already exist, engines can be
executed directly. NOTE: `python -c` does not add cwd to sys.path — insert it.
```
cd "D:\Dev\Ledger_Scrutiny_Tool"
python\python.exe -c "import sys; sys.path.insert(0,'.'); from engines.ls_runner import run_ls_for_company; print(run_ls_for_company('Demo','2025-26'))"
```
(engines now take `fy`). This regenerates `Demo\years\2025-26\analysis\Ledger_Scrutiny_Report.xlsx` and
is the canonical smoke test. Verify output with openpyxl (sheet count, row counts, values).
Scrutiny checks live in `engines/ls_engine.py` (`LSEngine.run_scrutiny`); each `results[key]=df`
becomes a sheet, with title/remarks/action in the `SCRUTINY_REMARKS` dict. Newest check:
`Recurring_Monthly_Expenses` — keyword-detected monthly expenses (rent/EB/salary/interest…)
shown as a month-wise (Apr→Mar) amount grid with blank/low months flagged.

**OB check, group concern (2026-06):** `LSEngine(..., prev_branch_pairs={branch: (prev_csv,
curr_csv)})` runs `Opening_Balance_Mismatch` **branch-wise** (Branch column added) — each branch's
CY opening vs its OWN previous-year closing, so offsetting errors across branches can't hide (a
consolidated-level check nets them to zero — verified). `ls_runner` auto-builds the pairs from
`extracted/PrevYear_<branch>_MasterData.csv` + `extracted/<branch>_MasterData.csv` when ≥2 pairs
exist; otherwise falls back to the classic consolidated/upload `prev_year_path` check.
Consolidating the PY files is now optional (UI text updated).

**Layer 3 — extract step (needs Tally, USER runs).** `extract_engine` ODBC pulls
can't run without Tally on port 9400. Claude tests the parse/transform functions by
feeding saved samples; the user runs the live extract and shares the resulting CSVs.

**Layer 4 — Streamlit UI.** BEST runtime check: `streamlit.testing.v1.AppTest` actually
executes the whole script (all tabs run) and surfaces exceptions — far stronger than a
curl check, which only confirms the server booted (the script body runs on browser
connect, not on a plain GET). Canonical UI smoke test:
```
python\python.exe -c "import sys; sys.path.insert(0,'.'); from streamlit.testing.v1 import AppTest; at=AppTest.from_file('streamlit_app.py', default_timeout=90); at.run(); print('exceptions:', list(at.exception))"
```
Expect `exceptions: []`. You can also drive widgets, e.g. `at.selectbox(key='selected_company').select('Demo').run()`.
Optionally also launch headless to confirm it serves:
```
python\python.exe -m streamlit run streamlit_app.py --server.headless true --server.port 8599
curl -s -o /dev/null -w "%{http_code}" http://localhost:8599/    # expect 200
```
NOTE: this shell has NO powershell/cmd/netstat on PATH. To find/kill the headless
server, drive Windows tools through the embedded Python via their System32 full paths
(`netstat.exe -ano` to find the PID on :8599, then `taskkill.exe /F /PID <pid>`).
Layout/visual correctness can't be seen headless — the user runs `run.bat` and reports
back (prefer a logfile/traceback over screenshots) for interactive + Tally-connected flows.

---

## Packaging / shipping

- All code ships as plain source; never compile and never commit secrets.
- `installer.iss` includes every module by wildcard and reads the version from `version.txt`.
  Embedded Python goes in `python/` (git-ignored). Upgrading a pre-open-source install renames
  `Documents\LSTool` to `LSTool_old_<date>` (never deletes) and drops `data_location.json`.
- **Test the installer only as a separately named build:** `ISCC /DTestBuild installer.iss` gives
  `LS Tool TEST`, whose data reset touches only `{app}\TestDocuments`. Install it with
  `/DIR=<test folder> /NOICONS /TASKS=""`. A normal build would replace the maintainer's own install.
- **Release steps (only after the maintainer says "release it"):** bump `version.txt` + `changelog.txt`,
  run both tests, commit and push, run `python\python.exe tools\make_release.py` (needs a clean tree),
  build `ISCC installer.iss` (only when launchers, Python or packages changed, or for a new PC), then
  create GitHub release `v<version>` with the update ZIP, its `.sha256` and the installer.

---

## Conventions / guardrails

- Do **not** commit user data, outputs, or logs (they live under Documents, not the repo).
- Keep engines independent of the UI; `streamlit_app.py` calls engines, not vice-versa.
- One logical change = one commit, with a clear "what + why" message.
- Only commit/push when the user asks.
- README's "Folder Structure" section is **stale** (mentions `dashboard.py`,
  `exporters/`, `requirements.txt` that don't exist) — trust this file instead.
