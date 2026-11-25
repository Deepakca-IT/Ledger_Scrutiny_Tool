import os
import sys
import io
import re
import html
import json
import pandas as pd
import streamlit as st
from engines import extract_engine
from engines import consolidate_engine
from engines import ls_runner
import viewer_engine
import tds_engine
import company_info
import tds_rules_engine
import fs_engine
import fs_grouping
import fs_reports
import msme_engine
import clause44_engine
import contra_engine
import paths
import profile_engine
from pathlib import Path

# ── Compact tables app-wide ───────────────────────────────────────────────────
# Streamlit grids are canvas-rendered, so row height can't be set via CSS — only
# the row_height param. Default every dataframe/editor to a shorter row unless a
# call sets its own. Patching the shared streamlit module also covers fs_ui etc.
_COMPACT_ROW_H = 30
if not getattr(st, "_compact_tables_patched", False):
    def _compact(_fn):
        def _wrap(*a, **k):
            k.setdefault("row_height", _COMPACT_ROW_H)
            return _fn(*a, **k)
        return _wrap
    st.dataframe = _compact(st.dataframe)
    st.data_editor = _compact(st.data_editor)
    st._compact_tables_patched = True


def _fy_prev(fy):
    """'2025-26' -> '2024-25'."""
    try:
        a = int(str(fy).strip()[:4])
        return f"{a - 1}-{str(a)[-2:]}"
    except Exception:
        return ""


# ── One-time flat -> per-year layout migration (idempotent) ───────────────────
if not st.session_state.get("_layout_migrated"):
    st.session_state["_layout_migrated"] = True
    try:
        import migrate
        migrate.migrate_all()
    except Exception:
        pass

# ── Developer flag ────────────────────────────────────────────────────────────
# dev_mode.txt beside the app shows features that are still in development
# (Financials NCE). It is never committed or shipped.
_IS_DEV = (Path(__file__).resolve().parent / "dev_mode.txt").exists()


def _app_version():
    try:
        return (Path(__file__).resolve().parent / "version.txt").read_text(
            encoding="utf-8-sig").strip()
    except OSError:
        return "—"


def indian_format(num):
    """Format number in Indian currency format."""
    num = float(num)
    is_negative = num < 0
    num = abs(num)
    s = f"{num:,.2f}"
    parts = s.split(".")
    integer = parts[0].replace(",", "")
    decimal = parts[1]
    if len(integer) <= 3:
        result = integer
    else:
        last3 = integer[-3:]
        rest = integer[:-3]
        groups = []
        while len(rest) > 2:
            groups.append(rest[-2:])
            rest = rest[:-2]
        if rest:
            groups.append(rest)
        groups.reverse()
        result = ",".join(groups) + "," + last3
    return f"₹ {'-' if is_negative else ''}{result}.{decimal}"


def summary_card(col, label, value, color="#1f4e79"):
    """Module-level metric card (also shadowed by a local copy inside tab4)."""
    col.markdown(f"""
    <div style="background:white; padding:10px 14px; border-radius:10px;
                box-shadow:0 2px 8px rgba(0,0,0,0.06);
                border-left:4px solid {color}; margin-bottom:10px;">
        <div style="font-size:11px; color:#555; font-weight:600;">{label}</div>
        <div style="font-size:16px; font-weight:800; color:{color};
                    margin-top:4px;">{value}</div>
    </div>
    """, unsafe_allow_html=True)


def dynamic_height(df):
    return min(max(len(df) * 35 + 38, 70), 600)


def _arrow_safe(df):
    """Return a copy whose object/text columns are pure strings so Streamlit's
    Arrow serialization never trips on a mixed-type column (e.g. a text column
    that picked up a stray int 0 from an older report)."""
    out = df.copy()
    for c in out.columns:
        if out[c].dtype == object:
            out[c] = out[c].apply(lambda v: '' if pd.isna(v) else str(v))
    return out


# pandas refuses to render a Styler past 262,144 cells, and well before that it
# is painfully slow — it builds a dict per cell. A group company's scrutiny
# sheet runs to lakhs of cells, so anything transaction-level goes through
# safe_styled_df() instead of st.dataframe(df.style).
_STYLER_CELL_LIMIT = 200_000


def _too_big_to_style(df):
    return int(df.shape[0]) * max(int(df.shape[1]), 1) > _STYLER_CELL_LIMIT


def _plain_inr(df, skip=()):
    """Indian-format every numeric column into text, for frames too big to style.

    Keeps all rows on screen and keeps the amounts readable; the cost is that
    those columns then sort as text, and row colouring is not available."""
    out = df.copy()
    for c in out.select_dtypes(include='number').columns:
        if c in skip:
            continue
        out[c] = [indian_format(v) if pd.notna(v) else '' for v in out[c]]
    return out


def safe_styled_df(df, style_fn=None, *, skip_fmt=(), **kw):
    """st.dataframe with Indian number formatting that degrades instead of
    raising when the frame is larger than pandas' Styler will render."""
    if _too_big_to_style(df):
        st.caption(
            f"⚠️ {len(df):,} rows × {df.shape[1]} columns is past the styling "
            "limit — amounts below are formatted text (so these columns sort "
            "alphabetically) and row colours are off. The download button has "
            "the full sheet with normal numbers.")
        st.dataframe(_plain_inr(df, skip_fmt), **kw)
    else:
        st.dataframe(style_fn(df.style) if style_fn else df.style, **kw)


def show_company_info(company_name, fy):
    """Shows company last extract and consolidate info inside each tab."""
    if not company_name or not fy:
        return

    info = company_info.get_company_info(company_name, fy)

    if not info["has_data"]:
        return

    # Build branch rows using st elements — no raw HTML
    st.markdown(f"""
    <div style="background:#f0f4f8; border-radius:8px;
                padding:10px 14px; margin-bottom:10px;
                border-left:4px solid #1f4e79;">
        <div style="font-size:12px; font-weight:700;
                    color:#1f4e79; margin-bottom:6px;">
            🏢 {company_name}
        </div>
        {"".join([
            f'<div style="display:flex;justify-content:space-between;'
            f'padding:2px 0;font-size:12px;">'
            f'<span>📁 <b>{b["branch"]}</b></span>'
            f'<span style="color:#555;">{b["date"]}</span></div>'
            for b in info["branches"]
        ])}
        {f'<div style="border-top:1px solid #e0e0e0;margin-top:6px;'
         f'padding-top:6px;font-size:12px;display:flex;'
         f'justify-content:space-between;">'
         f'<span>🧩 <b>Last Consolidated</b></span>'
         f'<span style="color:#555;">{info["last_consolidate"]}</span></div>'
         if info["last_consolidate"] else ""}
    </div>
    """, unsafe_allow_html=True)

# ── Page Config ───────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Audit Lite",
    page_icon="🧮",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ── Custom CSS ────────────────────────────────────────────────────────────────
st.markdown("""
<style>
    /* Global */
    html, body, [class*="css"] {
        font-family: 'Segoe UI', sans-serif;
        background-color: #f0f4f8;
    }

    /* Header */
    .header-box {
        background: linear-gradient(135deg, #1f4e79, #2e75b6);
        padding: 32px 36px;
        border-radius: 16px;
        margin-bottom: 24px;
        box-shadow: 0 4px 20px rgba(31,78,121,0.3);
    }
    .header-logo {
        font-size: 36px;
        font-weight: 900;
        color: white;
        letter-spacing: 2px;
    }
    .header-logo span {
        color: #90caf9;
    }
    .header-title {
        font-size: 22px;
        font-weight: 700;
        color: white;
        margin-top: 6px;
    }
    .header-sub {
        font-size: 13px;
        color: #dbe6f1;
        margin-top: 4px;
    }

    /* Cards */
    .card {
        background: white;
        border-radius: 10px;
        padding: 8px 12px;
        box-shadow: 0 2px 8px rgba(0,0,0,0.06);
        margin-bottom: 8px;
    }
    .card-title {
        font-size: 14px;
        font-weight: 700;
        color: #1f4e79;
        margin-bottom: 4px;
    }
    .card-desc {
        font-size: 13px;
        color: #555;
        margin-bottom: 16px;
    }

    /* Status boxes (compact) */
    .status-success {
        background: #e8f5e9;
        border-left: 4px solid #43a047;
        padding: 7px 12px;
        border-radius: 8px;
        color: #2e7d32;
        font-weight: 600;
        font-size: 12.5px;
    }
    .status-error {
        background: #ffebee;
        border-left: 4px solid #e53935;
        padding: 7px 12px;
        border-radius: 8px;
        color: #c62828;
        font-weight: 600;
        font-size: 12.5px;
    }
    .status-running {
        background: #fff8e1;
        border-left: 4px solid #ffa000;
        padding: 7px 12px;
        border-radius: 8px;
        color: #e65100;
        font-weight: 600;
        font-size: 12.5px;
    }

    /* Tab styling (compact) */
    .stTabs [data-baseweb="tab-list"] {
        gap: 4px;
        background: white;
        padding: 4px 8px;
        border-radius: 10px;
        box-shadow: 0 1px 4px rgba(0,0,0,0.05);
        margin-bottom: 8px;
    }
    .stTabs [data-baseweb="tab"] {
        background: #f0f4f8;
        border-radius: 7px;
        padding: 4px 12px;
        font-weight: 600;
        font-size: 12.5px;
        color: #1f4e79;
        border: none;
        min-height: 0;
    }
    .stTabs [aria-selected="true"] {
        background: #1f4e79 !important;
        color: white !important;
        border-radius: 8px;
    }

    /* ── Design tokens ─────────────────────────────────────────────── */
    :root{
        --ink:#1c2027; --ink-2:#2a3038; --ink-line:rgba(255,255,255,.07);
        --txt:#eef1f4; --txt-dim:#9aa3ad;
        --brand:#1f4e79; --brand-700:#163a5f;
        --accent:#D97757;             /* Claude clay accent */
        --nav-sel:rgba(217,119,87,.20); /* active nav fill */
        --paper:#f6f8fb; --card:#ffffff; --hair:#e7ecf2; --ink-soft:#1f2a37;
        --mono:"Cascadia Code","Consolas",ui-monospace,monospace;
    }
    body{ font-variant-numeric: tabular-nums; }

    /* ── Main-area buttons: flat brand, no gradient ────────────────── */
    .stButton > button {
        background: var(--brand); color:#fff; border:1px solid var(--brand);
        border-radius: 8px; padding: 5px 12px; font-size: 12.5px; font-weight: 600;
        letter-spacing: .2px; box-shadow:none; transition: background .14s ease;
    }
    .stButton > button:hover {
        background: var(--brand-700); border-color: var(--brand-700);
        box-shadow:none; transform:none;
    }
    .stButton > button:active { transform:none; }
    .stButton > button[kind="secondary"],
    .stButton > button[data-testid="stBaseButton-secondary"]{
        background:#fff; color:var(--brand); border:1px solid #cdd8e4;
    }
    .stButton > button[data-testid="stBaseButton-secondary"]:hover{
        background:#f1f5fa; border-color:var(--brand); color:var(--brand);
    }

    /* ── Sidebar: deep ink, compact nav (75% of default width) ─────── */
    section[data-testid="stSidebar"]{
        background:var(--ink); border-right:1px solid var(--ink-line);
    }
    /* Fix width ONLY when expanded, so collapsing fully frees the space
       and the main screen widens. */
    section[data-testid="stSidebar"][aria-expanded="true"]{
        width:212px !important; min-width:212px !important;
    }
    section[data-testid="stSidebar"][aria-expanded="true"] > div{
        width:212px !important; min-width:212px !important;
    }
    section[data-testid="stSidebar"] [data-testid="stSidebarUserContent"]{ padding-top:.6rem; }
    section[data-testid="stSidebar"] *{ color:var(--txt); }
    /* nav + utility rows: small, flat, left-aligned, single-line */
    section[data-testid="stSidebar"] .stButton > button{
        background:transparent; color:var(--txt-dim); border:none;
        border-radius:8px; padding:5px 9px; min-height:30px;
        font-size:12px; font-weight:500; line-height:1.1;
        justify-content:flex-start; text-align:left; width:100%; box-shadow:none;
        white-space:nowrap; overflow:hidden; text-overflow:ellipsis;
    }
    section[data-testid="stSidebar"] .stButton > button > div,
    section[data-testid="stSidebar"] .stButton > button [data-testid="stMarkdownContainer"]{
        display:flex !important; justify-content:flex-start !important; width:100% !important;
    }
    section[data-testid="stSidebar"] .stButton > button p,
    section[data-testid="stSidebar"] .stButton > button div{
        white-space:nowrap; overflow:hidden; text-overflow:ellipsis;
        width:100%; text-align:left !important; font-size:12px;
    }
    section[data-testid="stSidebar"] .stButton > button:hover{
        background:rgba(255,255,255,.055); color:var(--txt);
    }
    /* active nav = clearly visible amber-tinted fill + amber spine */
    section[data-testid="stSidebar"] button[data-testid="stBaseButton-primary"]{
        background:var(--nav-sel) !important; color:#fff !important; font-weight:700;
        border:none !important; box-shadow:inset 3px 0 0 var(--accent) !important;
        justify-content:flex-start !important; text-align:left !important;
    }
    section[data-testid="stSidebar"] button[data-testid="stBaseButton-primary"] p{
        color:#ffffff !important; font-weight:700 !important; text-align:left !important;
    }
    /* nav dropdowns (expanders) — flat + dark, never a white box over the title */
    section[data-testid="stSidebar"] [data-testid="stExpander"],
    section[data-testid="stSidebar"] [data-testid="stExpander"] details,
    section[data-testid="stSidebar"] [data-testid="stExpander"] summary,
    section[data-testid="stSidebar"] [data-testid="stExpanderDetails"],
    section[data-testid="stSidebar"] .streamlit-expanderHeader,
    section[data-testid="stSidebar"] .streamlit-expanderContent{
        background:transparent !important; border:none !important; box-shadow:none !important;
    }
    section[data-testid="stSidebar"] [data-testid="stExpander"] summary{
        padding:8px 4px 4px 4px !important;
    }
    section[data-testid="stSidebar"] [data-testid="stExpander"] summary:hover{
        background:transparent !important;
    }
    section[data-testid="stSidebar"] [data-testid="stExpander"] summary p{
        font-size:10px !important; font-weight:800 !important; letter-spacing:.7px !important;
        color:#aeb8c2 !important; text-transform:uppercase;
    }
    section[data-testid="stSidebar"] [data-testid="stExpander"] summary:hover p,
    section[data-testid="stSidebar"] [data-testid="stExpander"] summary svg{
        color:#e8edf2 !important; fill:#aeb8c2 !important;
    }
    section[data-testid="stSidebar"] [data-testid="stExpanderDetails"]{ padding:0 0 4px 0 !important; }
    /* company switcher field on dark */
    section[data-testid="stSidebar"] [data-baseweb="select"] > div{
        background:#0a1623; border:1.5px solid var(--accent); border-radius:8px;
        color:#f3dccf; font-size:13px; min-height:36px;
    }
    section[data-testid="stSidebar"] hr{ border-color:var(--ink-line); }

    /* ── Dropdown panels: size to the longest option, not to the box ──
       BaseWeb renders the open list in a portal at <body> level, so it can
       float wider than its anchor (the 212px sidebar clips long company names
       otherwise). Adaptive, not a fixed width: short
       dropdowns stay short, long ones grow up to the cap. */
    div[data-baseweb="popover"] > div{
        width:auto !important; min-width:max-content !important; max-width:460px !important;
    }
    div[data-baseweb="popover"] ul[role="listbox"]{
        min-width:max-content !important; max-width:460px !important;
    }
    div[data-baseweb="popover"] li[role="option"]{
        overflow:visible !important; text-overflow:clip !important;
    }

    /* ── Inputs ────────────────────────────────────────────────────── */
    .stTextInput input, .stNumberInput input{
        border-radius:8px !important; border:1px solid #cdd8e4 !important; font-size:13px !important;
    }

    /* ── Compact forms (smaller labels, shorter inputs, tighter gaps) ─ */
    [data-testid="stWidgetLabel"]{ margin-bottom:1px !important; }
    [data-testid="stWidgetLabel"] p{
        font-size:11px !important; font-weight:600 !important; color:#5b6b7a !important;
        line-height:1.1 !important;
    }
    /* shrink the bordered BOX itself (the wrapper height is what looks tall) */
    section[data-testid="stMain"] .stTextInput > div,
    section[data-testid="stMain"] .stNumberInput > div,
    section[data-testid="stMain"] .stDateInput > div{ min-height:0 !important; }
    section[data-testid="stMain"] [data-baseweb="input"],
    section[data-testid="stMain"] [data-baseweb="base-input"]{
        min-height:0 !important; height:32px !important;
    }
    /* Textareas share the base-input class — never clamp them to one line. */
    section[data-testid="stMain"] [data-baseweb="textarea"],
    section[data-testid="stMain"] [data-baseweb="textarea"] [data-baseweb="base-input"]{
        height:auto !important; min-height:0 !important;
    }
    section[data-testid="stMain"] [data-baseweb="textarea"] textarea{
        height:auto !important; min-height:0 !important; line-height:1.45 !important;
        padding:6px 10px !important; font-size:13px !important;
    }
    section[data-testid="stMain"] .stTextInput input,
    section[data-testid="stMain"] .stNumberInput input,
    section[data-testid="stMain"] .stDateInput input{
        height:30px !important; min-height:0 !important; line-height:30px !important;
        padding:0 10px !important; font-size:13px !important;
    }
    /* selectbox control box */
    section[data-testid="stMain"] [data-baseweb="select"] > div{
        min-height:32px !important; height:32px !important; font-size:13px !important;
    }
    section[data-testid="stMain"] [data-baseweb="select"] > div > div{
        padding-top:0 !important; padding-bottom:0 !important; line-height:30px !important;
    }
    section[data-testid="stMain"] div[data-testid="stVerticalBlock"]{ gap:0.4rem !important; }
    [data-testid="stExpander"] summary{ padding:.35rem .7rem !important; }
    [data-testid="stExpander"] summary p{ font-size:12.5px !important; font-weight:700 !important; }
    [data-testid="stExpanderDetails"]{ padding-top:.3rem !important; }
    [data-testid="stCheckbox"] label p{ font-size:12px !important; }
    section[data-testid="stMain"] [data-testid="stHorizontalBlock"]{ gap:.5rem !important; }

    /* Input fields */
    .stTextInput > div > div > input,
    .stSelectbox > div > div {
        border-radius: 8px;
        border: 1.5px solid #c5d8ec;
        font-size: 14px;
    }

    /* Footer */
    .footer {
        text-align: center;
        color: #888;
        font-size: 12px;
        padding: 20px 0 8px 0;
        border-top: 1px solid #e0e0e0;
        margin-top: 32px;
    }
    .footer span {
        color: #1f4e79;
        font-weight: 700;
    }

    /* Hide streamlit default elements (keep the header so the sidebar
       expand/collapse control stays reachable) */
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    [data-testid="stToolbarActions"] {visibility: hidden;}
    /* Always keep the sidebar collapse/expand controls clickable */
    [data-testid="stSidebarCollapseButton"],
    [data-testid="stSidebarCollapsedControl"],
    [data-testid="stExpandSidebarButton"] {visibility: visible !important;}

    /* Clear the fixed Streamlit header so the top bar isn't tucked under it */
    .block-container {
        padding-top: 3rem !important;
        padding-bottom: 8px !important;
    }
    [data-testid="stHeader"]{ background: transparent; }

</style>
""", unsafe_allow_html=True)


# ── Helper: Load company list ─────────────────────────────────────────────────
BASE_DATA_DIR = str(paths.BASE)   # shared/local data root (see paths.get_data_root)
os.makedirs(BASE_DATA_DIR, exist_ok=True)

def load_company_list():
    if os.path.exists(BASE_DATA_DIR):
        return sorted(
            d for d in os.listdir(BASE_DATA_DIR)
            if os.path.isdir(os.path.join(BASE_DATA_DIR, d))
        )
    return []


# ── Slim Header with Company Selector ────────────────────────────────────────
company_list = load_company_list()

@st.cache_data
def _logo_data_uri():
    """Load app.ico, return a PNG data-URI for embedding in the header (cached)."""
    try:
        import base64, io
        from PIL import Image
        p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "app.ico")
        im = Image.open(p).convert("RGBA")
        buf = io.BytesIO()
        im.save(buf, format="PNG")
        return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()
    except Exception:
        return ""


# ── Left-sidebar navigation (grouped, WeAudit-style) ─────────────────────────
_NAV_GROUPS = [
    ("WORKFLOW", [("extract", "📋 Extract & Consolidate"),
                  ("analysis", "📊 Analysis"),
                  ("tdsrules", "📐 TDS Rules")]),
    ("AUDIT MODULES", [("scrutiny", "📘 Ledger Scrutiny"),
                       ("viewer", "📈 TDS Compliance"),
                       ("related", "🔗 Related Parties"),
                       ("contra", "🔁 Contra Balances"),
                       ("msme", "📑 43B(h) MSME"),
                       ("clause44", "📄 Clause 44 (GST)")]),
]
_NAV_NCE = ("FINANCIALS (Beta)", [("nce", "🧾 Financials (NCE)")])
_NAV_IDS = [pid for _, items in _NAV_GROUPS for pid, _ in items] + ["nce"]


def _render_nav(is_dev):
    """Grouped nav in the sidebar — each group is a collapsible dropdown; the one
    holding the active page opens by default. Returns the active page id."""
    if st.session_state.get("nav_page") not in _NAV_IDS:
        st.session_state["nav_page"] = "extract"
    active_page = st.session_state["nav_page"]
    groups = list(_NAV_GROUPS) + ([_NAV_NCE] if is_dev else [])
    for title, items in groups:
        _has_active = any(pid == active_page for pid, _ in items)
        with st.expander(title, expanded=_has_active):
            for pid, label in items:
                if st.button(label, key=f"nav_{pid}", width="stretch",
                             type="primary" if active_page == pid else "secondary"):
                    st.session_state["nav_page"] = pid
                    st.rerun()
    return st.session_state["nav_page"]


@st.dialog("⚙️ Manage companies & years")
def _manage_dialog(company_name):
    """Create / delete a company and add tax years — kept out of the main chrome.
    Uses _pending_* keys + rerun so we never assign a widget key after the
    sidebar/top-bar widgets have already rendered this run."""
    t_new, t_year, t_del = st.tabs(["➕ New company", "📅 Add tax year", "🗑️ Delete"])

    with t_new:
        nm = st.text_input("Company name", key="mng_new_name", placeholder="e.g. ABC Pvt Ltd")
        fy = st.selectbox("First tax year", options=fs_engine.available_fy_choices(),
                          key="mng_new_fy")
        _grp = st.radio("Company type", options=["Single Company", "Group Concern"],
                        horizontal=True, key="mng_new_group",
                        help="Group Concern = multiple branches/companies extracted "
                             "branch-wise and consolidated. You can change this later "
                             "from the Manage dialog.")
        if st.button("Create company", key="mng_new_btn", type="primary", width="stretch"):
            nm = (nm or "").strip()
            if not nm:
                st.warning("Enter a company name.")
            else:
                existed = os.path.isdir(os.path.join(BASE_DATA_DIR, nm))
                paths.ensure_year(nm, fy)
                fs_engine.set_current_fy(nm, fy)
                fs_engine.set_previous_fy(nm, _fy_prev(fy))
                fs_engine.set_is_group(nm, _grp == "Group Concern")
                st.session_state["_pending_company"] = nm
                st.session_state["_pending_fy"] = fy
                st.session_state["flash"] = (
                    "warning" if existed else "success",
                    (f"⚠️ '{nm}' already existed — added FY {fy}." if existed
                     else f"✅ '{nm}' created with FY {fy}."))
                st.rerun()

    with t_year:
        if not company_name:
            st.info("Select a company first.")
        else:
            _cur_grp = fs_engine.get_is_group(company_name)
            _g = st.radio("Company type", ["Single Company", "Group Concern"],
                          index=1 if _cur_grp else 0, horizontal=True,
                          key="mng_edit_group")
            if st.button("💾 Save company type", key="mng_edit_group_btn", width="stretch"):
                fs_engine.set_is_group(company_name, _g == "Group Concern")
                st.session_state["concern_type"] = _g
                st.session_state["flash"] = ("success", f"✅ {company_name} set as {_g}.")
                st.rerun()
            st.markdown("<hr style='margin:8px 0;'>", unsafe_allow_html=True)
            existing = paths.list_years(company_name)
            avail = [fy for fy in fs_engine.available_fy_choices() if fy not in existing]
            st.caption(f"Existing years: {', '.join(existing) or '—'}")
            if not avail:
                st.info("All available years already added.")
            else:
                nfy = st.selectbox("Add tax year", options=avail, key="mng_add_fy")
                if st.button("Add year", key="mng_add_btn", type="primary", width="stretch"):
                    paths.ensure_year(company_name, nfy)
                    _src = paths.latest_year_before(company_name, nfy)
                    if _src:
                        paths.seed_config_from(company_name, _src, nfy)
                    fs_engine.set_current_fy(company_name, nfy)
                    fs_engine.set_previous_fy(company_name, _fy_prev(nfy))
                    st.session_state["_pending_fy"] = nfy
                    st.session_state["flash"] = ("success", f"✅ Tax Year {nfy} added.")
                    st.rerun()

    with t_del:
        if not company_name:
            st.info("Select a company first.")
        else:
            st.warning(f"Permanently delete **{company_name}** and ALL its data "
                       "(every year — extracted, consolidated, analysis). Cannot be undone.")
            if st.button(f"🗑️ Delete '{company_name}'", key="mng_del_btn",
                         type="primary", width="stretch"):
                import shutil
                try:
                    shutil.rmtree(os.path.join(BASE_DATA_DIR, company_name))
                    st.session_state["_pending_company"] = ""
                    st.session_state["flash"] = ("success", f"🗑️ '{company_name}' deleted.")
                except Exception as e:
                    st.session_state["flash"] = ("error", f"Could not delete: {e}")
                st.rerun()


@st.dialog("👤 Firm profile")
def _profile_dialog():
    """Firm + CA-partner details, stored once and shared across all companies.
    The NCE auditor block picks the signing CA from here and auto-fills the rest."""
    prof = profile_engine.load_profile()
    st.caption("Stored once and shared by every company. In NCE ▸ Master Data ▸ Auditor "
               "you pick the signing CA from this list.")
    c = st.columns(2)
    firm = c[0].text_input("Firm name", prof.get("firm_name", ""), key="prof_firm")
    frn = c[1].text_input("Firm Reg. No. (FRN)", prof.get("frn", ""), key="prof_frn")
    place = st.text_input("Place", prof.get("place", ""), key="prof_place")
    st.markdown("**CA partners** — one row per partner")
    pdf = pd.DataFrame(prof.get("partners") or [],
                       columns=["name", "membership_no", "designation"])
    ped = st.data_editor(
        pdf, num_rows="dynamic", hide_index=True, width="stretch", key="prof_partners",
        column_config={
            "name": st.column_config.TextColumn("Name of CA", width="small"),
            "membership_no": st.column_config.TextColumn("Membership No."),
            "designation": st.column_config.SelectboxColumn(
                "Designation", options=["Partner", "Proprietor", "Designated Partner"],
                default="Partner"),
        })
    if st.button("💾 Save profile", type="primary", width="stretch", key="prof_save"):
        partners = []
        for _, r in ped.iterrows():
            nm = r.get("name")
            if pd.isna(nm) or not str(nm).strip():
                continue
            partners.append({
                "name": str(nm).strip(),
                "membership_no": ("" if pd.isna(r.get("membership_no"))
                                  else str(r.get("membership_no")).strip()),
                "designation": ("Partner" if pd.isna(r.get("designation"))
                                else str(r.get("designation")).strip() or "Partner")})
        profile_engine.save_profile({"firm_name": firm.strip(), "frn": frn.strip(),
                                     "place": place.strip(), "partners": partners})
        st.session_state["flash"] = ("success", "✅ Firm profile saved.")
        st.rerun()


# ── Busy overlay: full-screen click-blocker for long operations ──────────────
# While a Streamlit script is computing, any click triggers a rerun that can
# interrupt the work mid-way. This overlay covers the whole window so stray
# clicks land on IT instead of widgets, and shows a live elapsed timer (pure
# CSS @property animation — it keeps ticking even while Python is blocked).
_BUSY_HTML = """
<style>
@property --lsbt { syntax: "<integer>"; inherits: false; initial-value: 0; }
.ls-busy-wrap{position:fixed;inset:0;z-index:999999;background:rgba(15,23,42,.55);
  backdrop-filter:blur(2px);display:flex;align-items:center;justify-content:center;}
.ls-busy-card{background:#fff;border-radius:14px;padding:26px 44px;
  box-shadow:0 12px 40px rgba(0,0,0,.3);text-align:center;}
.ls-busy-ring{width:44px;height:44px;margin:0 auto 14px;border:4px solid #e2e8f0;
  border-top-color:#2563eb;border-radius:50%;animation:lsbspin .9s linear infinite;}
@keyframes lsbspin{to{transform:rotate(360deg)}}
.ls-busy-msg{font-size:15px;font-weight:600;color:#0f172a;}
.ls-busy-sub{font-size:12px;color:#64748b;margin-top:6px;}
.ls-busy-timer{font-size:13px;color:#2563eb;margin-top:10px;
  font-variant-numeric:tabular-nums;counter-reset:lsbt var(--lsbt);
  animation:lsbt 3600s linear forwards;}
@keyframes lsbt{from{--lsbt:0}to{--lsbt:3600}}
.ls-busy-timer::after{content:counter(lsbt) "s elapsed";}
</style>
<div class="ls-busy-wrap"><div class="ls-busy-card">
  <div class="ls-busy-ring"></div>
  <div class="ls-busy-msg">__MSG__</div>
  <div class="ls-busy-sub">Loading… chill 😎 &nbsp;Clicks are paused so the process isn't disturbed.</div>
  <div class="ls-busy-timer"></div>
</div></div>
"""


class busy_overlay:
    """with busy_overlay("Running ledger scrutiny…"): <long work>"""
    def __init__(self, message="Processing…"):
        self.message = message

    def __enter__(self):
        self.ph = st.empty()
        self.ph.markdown(_BUSY_HTML.replace("__MSG__", self.message),
                         unsafe_allow_html=True)
        return self

    def __exit__(self, *exc):
        self.ph.empty()
        return False


@st.dialog("🗂 Data folder (LAN sharing)")
def _data_location_dialog():
    """Per-PC setting: point this install at a shared LAN folder so every office
    PC reads/writes the same companies & financials. Blank = single-user."""
    st.info(r"**Host/Server PC** — enter a LOCAL path you then share, e.g. `C:\LSTool`."
            "\n\n"
            r"**Other LAN PCs** — enter the host's shared folder, e.g. `\\HOSTPC\LSTool`."
            "\n\n"
            "All PCs that point at the same folder share companies & financials. "
            "Leave single-user for a standalone PC. Takes effect after you restart the app.")
    cur = str(paths.get_data_root())
    st.text_input("Currently using", value=cur, disabled=True, key="dl_cur")
    new = st.text_input("Shared LSTool folder", value=(cur if paths.is_data_location_configured() else ""),
                        placeholder=r"\\HOSTPC\LSTool", key="dl_new")
    c1, c2 = st.columns(2)
    if c1.button("💾 Save & use shared folder", type="primary", width="stretch", key="dl_save"):
        p = (new or "").strip()
        if not p:
            st.error("Enter the shared folder path, or use ‘Reset to single-user’.")
        else:
            try:
                Path(p).mkdir(parents=True, exist_ok=True)
                paths.set_data_root(p)
                st.session_state["flash"] = ("success", f"✅ Data folder set to {p}. Restart the app to apply.")
                st.rerun()
            except Exception as e:
                st.error(f"Could not use that path: {e}")
    if c2.button("↩️ Reset to single-user", width="stretch", key="dl_reset"):
        try:
            f = paths.data_location_file()
            if f.exists():
                f.unlink()
            st.session_state["flash"] = ("success", "✅ Reverted to single-user. Restart the app to apply.")
            st.rerun()
        except Exception as e:
            st.error(f"Could not reset: {e}")


def render_sidebar():
    """Left sidebar: brand + company switcher + Manage + nav + version.
    Returns (company_name, page). Year + entity + Sync live in the top bar."""
    is_dev = _IS_DEV
    # Apply a pending company selection (from the Manage dialog) BEFORE the widget.
    if "_pending_company" in st.session_state:
        st.session_state["selected_company"] = st.session_state.pop("_pending_company")
    h1 = st.sidebar.container()    # branding
    h2 = st.sidebar.container()    # company switcher + manage
    navc = st.sidebar.container()  # navigation
    h3 = st.sidebar.container()    # version + utilities (bottom)

    with h1:
        _logo = _logo_data_uri()
        _logo_html = (f'<img src="{_logo}" style="height:30px;width:30px;border-radius:7px;"/>'
                      if _logo else
                      '<div style="height:30px;width:30px;border-radius:7px;background:#17283b;'
                      'display:flex;align-items:center;justify-content:center;'
                      'font-weight:800;color:#D97757;font-size:14px;">CA</div>')
        st.markdown(f"""
        <div style="display:flex; align-items:center; gap:10px; padding:2px 2px 4px 2px;">
            {_logo_html}
            <div style="line-height:1.05;">
                <div style="font-size:18px; font-weight:800; letter-spacing:.02em; color:#D97757;">Audit&nbsp;Lite</div>
                <div style="font-size:8.5px; font-weight:700; letter-spacing:.18em;
                            white-space:nowrap; color:#9aa3ad; margin-top:4px;">BY&nbsp;CA&nbsp;DSP</div>
            </div>
        </div>
        """, unsafe_allow_html=True)

    with h2:
        # If the previously selected company was deleted, reset the dropdown safely.
        if st.session_state.get("selected_company") and \
           st.session_state["selected_company"] not in company_list:
            st.session_state["selected_company"] = ""
        prev_company = st.session_state.get("selected_company", "")
        st.markdown("<div style='font-size:11px; color:#aeb8c2; font-weight:800; "
                    "letter-spacing:.7px; margin:10px 0 8px 2px; padding-top:2px;'>COMPANY</div>",
                    unsafe_allow_html=True)
        if company_list:
            company_name = st.selectbox(
                "Company", options=[""] + company_list,
                key="selected_company", label_visibility="collapsed")
            # The closed box still clips at 212px — echo the full name below it,
            # wrapped, so the selected company is always readable in full.
            if company_name:
                st.markdown(
                    "<div style='font-size:10.5px; line-height:1.3; color:#8696a6; "
                    "margin:-2px 0 2px 3px; word-break:break-word;'>"
                    f"{html.escape(company_name)}</div>",
                    unsafe_allow_html=True)
        else:
            company_name = ""
            st.caption("No companies yet — use Manage to create one.")
        if st.button("⚙️ Manage companies & years", key="btn_manage", width="stretch"):
            _manage_dialog(company_name)
        # Company type is a saved company attribute (set at creation / Manage) — make
        # it the single source of truth for extraction + consolidation + 43B(h), so
        # there's no per-session radio to second-guess.
        if company_name:
            st.session_state["concern_type"] = (
                "Group Concern" if fs_engine.get_is_group(company_name)
                else "Single Company")
        # Reset transient state + year selection when the company changes.
        if company_name != prev_company:
            for _k in ("tally_connected", "tally_status_msg", "viewer_df",
                       "company_refreshed", "active_fy_select", "_fy_company"):
                st.session_state.pop(_k, None)

    with h3:
        st.markdown("<hr style='margin:10px 0 8px 0; border:none; "
                    "border-top:1px solid rgba(255,255,255,.07);'>", unsafe_allow_html=True)
        st.markdown(f"<div style='font-size:9.5px; color:#8696a6; padding:2px;'>"
                    f"LS Tool &nbsp;·&nbsp; v{html.escape(_app_version())}</div>",
                    unsafe_allow_html=True)

        st.markdown("<div style='height:6px'></div>", unsafe_allow_html=True)
        if st.button("👤 Firm profile", key="btn_firm_profile", width="stretch"):
            _profile_dialog()
        if st.button("🗂 Data folder (LAN sharing)", key="btn_data_folder",
                     width="stretch"):
            _data_location_dialog()
        # Open the current data folder in Explorer (opens on this PC).
        if st.button("📂 Open data folder", key="btn_open_data_folder", width="stretch"):
            try:
                os.startfile(str(paths.get_data_root()))
            except Exception as _e:
                st.toast(f"Couldn't open folder: {_e}", icon="⚠️")

        # Rarely needed: the app caches only the logo and generated NCE
        # Excel/PDF (keyed by a data signature, so they refresh on their own).
        # Kept here for the odd case where a report looks stale.
        if st.button("🧹 Clear cache", key="btn_clear_cache", width="stretch",
                     help="Rebuilds cached reports. Your saved data is untouched."):
            st.cache_data.clear()
            st.toast("Cache cleared — reports will rebuild.", icon="🧹")

    with navc:
        page = _render_nav(is_dev)

    # One-shot flash message (survives the rerun triggered by actions like company creation)
    _flash = st.session_state.pop("flash", None)
    if _flash:
        getattr(st.sidebar, _flash[0])(_flash[1])

    return company_name, page


def render_topbar(company_name):
    """Main-area top strip: entity name + Financial Year selector + Sync.
    Returns the active FY (drives every page)."""
    # Apply a pending FY (from the Manage dialog) BEFORE the FY widget renders.
    if "_pending_fy" in st.session_state:
        st.session_state["active_fy_select"] = st.session_state.pop("_pending_fy")
    if not company_name:
        st.info("👈 Select or create a company in the sidebar to begin.")
        return ""
    # Reset the FY selection when the company changes.
    if st.session_state.get("_fy_company") != company_name:
        st.session_state["_fy_company"] = company_name
        st.session_state.pop("active_fy_select", None)

    existing_years = paths.list_years(company_name)
    active_fy = ""
    c1, c2, c3 = st.columns([6, 2, 1], vertical_alignment="bottom")
    with c1:
        _etype = fs_engine.load_entity(company_name).get("entity", {}).get("type", "")
        st.markdown(
            f"<div style='font-size:18px; font-weight:800; color:#1f2a37;'>{company_name}"
            f"<span style='font-size:11.5px; font-weight:600; color:#6b7280; "
            f"margin-left:8px;'>{_etype}</span></div>", unsafe_allow_html=True)
    with c2:
        if existing_years:
            if st.session_state.get("active_fy_select") not in existing_years:
                _cur = fs_engine.get_current_fy(company_name)
                st.session_state["active_fy_select"] = (
                    _cur if _cur in existing_years else existing_years[0])
            active_fy = st.selectbox("Financial Year", options=existing_years,
                                     key="active_fy_select")
            fs_engine.set_current_fy(company_name, active_fy)
            fs_engine.set_previous_fy(company_name, _fy_prev(active_fy))
        else:
            st.caption("No tax year — use ⚙️ Manage to add one.")
    with c3:
        _on_nce = st.session_state.get("nav_page") == "nce"
        if st.button("🔄 Sync", key="btn_sync", width="stretch",
                     help=("Re-pull the year-end ledger master "
                           "(Master Data → Year & master extraction)"
                           if _on_nce else
                           "Go to Extract & Consolidate to re-pull data from Tally")):
            if _on_nce:
                # NCE has its own year-end master extraction — surface it instead of
                # sending the user to the ledger-scrutiny Extract page.
                st.session_state["fs_open_master_extract"] = True
            else:
                st.session_state["nav_page"] = "extract"
            st.rerun()
    st.session_state["active_fy"] = active_fy
    st.markdown("<hr style='margin:2px 0 10px 0; border:none; "
                "border-top:1px solid #e6e9ee;'>", unsafe_allow_html=True)
    return active_fy


# ── Compact styling (applied before sidebar/top-bar render) ──────────────────
st.markdown("""
<style>
div[data-testid="stVerticalBlock"]{ gap:0.45rem; }
div[data-testid="stMainBlockContainer"]{ padding-top:1.0rem; padding-bottom:1.2rem; }
details[data-testid="stExpander"] summary{ padding:0.3rem 0.7rem; }
div[data-testid="stCaptionContainer"]{ margin:-0.25rem 0 0 0; font-size:11.5px; }
h3{ font-size:1.05rem; }
h4{ margin:0.15rem 0 0.3rem 0; font-size:0.9rem; color:#0e1b2a; }
h5,h6{ font-size:0.82rem; }
/* Compact data tables app-wide */
[data-testid="stDataFrame"], [data-testid="stDataEditor"]{ font-size:12.5px; }
/* Status banners are raw markdown (no margin) — give them room so the next
   widget's label doesn't overlap them. */
.status-success,.status-error,.status-running{ margin:2px 0 10px 0; }
[data-testid="stFileUploader"] label{ margin-top:2px; }
</style>
""", unsafe_allow_html=True)

# ── Sidebar (company + nav) + main-area top bar (entity + FY + Sync) ──────────
company_name, _page = render_sidebar()
active_fy = render_topbar(company_name)
_dev = _IS_DEV

# ── Soft per-company edit lock (LAN multi-user) ───────────────────────────────
# Advisory only — refresh this PC's lock on the active company (throttled to once
# a minute so we don't hammer the network share) and warn if another PC is also
# in this company. Never blocks; saves still go through.
if company_name:
    import time as _t
    _switched = st.session_state.get("_lock_company") != company_name
    if _t.time() - st.session_state.get("_lock_hb_at", 0) > 60 or _switched:
        if _switched and st.session_state.get("_lock_company"):
            paths.release_company_lock(st.session_state["_lock_company"])
        _ok, _other = paths.acquire_company_lock(company_name)
        st.session_state["_lock_hb_at"] = _t.time()
        st.session_state["_lock_company"] = company_name
        st.session_state["_lock_other"] = _other
    _other = st.session_state.get("_lock_other")
    if _other:
        st.warning(
            f"⚠️ **{_other.get('user')}** (PC: {_other.get('host')}) may also be "
            f"working on **{company_name}** — last active {_other.get('age_s')}s ago. "
            "Your saves could overwrite each other; coordinate before editing the "
            "same year.")


# ── Page: Extract & Consolidate ──────────────────────────────────────────────
if _page == "extract":
    show_company_info(company_name, active_fy)
    if company_name and not active_fy:
        st.warning("⚠️ Select or create a **Tax Year** in the header to begin.")
    st.markdown("""
    <div class="card">
        <div class="card-title">📋 Step 1 — Extract & Consolidate</div>
        <div class="card-desc">
            Connect to Tally, extract branch-wise data and consolidate.
        </div>
    </div>
    """, unsafe_allow_html=True)

    left_col, divider_col, right_col = st.columns([10, 1, 10])

    # ── LEFT: Extract ─────────────────────────────────────────────────────────
    with left_col:
        st.markdown("#### 1️⃣ Connect & Extract")

        # Connect button
        if st.button("🔌 Connect to Tally", key="btn_connect",
                     width="stretch"):
            with busy_overlay("Connecting to Tally…"):
                success, message = extract_engine.test_connection()
                st.session_state["tally_connected"] = success
                st.session_state["tally_status_msg"] = message
                # Second check: what is Tally ACTUALLY holding right now? The
                # extraction has no date filter, so the open company + current
                # period decide what comes out.
                st.session_state["tally_info"] = (
                    extract_engine.get_tally_status() if success else None)

        # Connection status
        if st.session_state.get("tally_connected"):
            st.markdown(
                '<div class="status-success">✅ Connected to Tally on port 9400</div>',
                unsafe_allow_html=True
            )

            _ti = st.session_state.get("tally_info") or {}
            _cos = _ti.get("companies") or []
            _pf, _pt = _ti.get("period_from", ""), _ti.get("period_to", "")
            _act, _multi = _ti.get("active_guess", ""), _ti.get("multi", False)

            # Cross-check the loaded period against the FY selected in the app.
            # Compare the FROM year and TO year separately — searching the whole
            # string is too loose (a 2024-25 period also contains "2025").
            def _year_of(s):
                for g in re.findall(r"\d{4}", str(s)):
                    if 1990 <= int(g) <= 2100:
                        return int(g)
                return None

            _fy_warn = ""
            _y_from, _y_to = _year_of(_pf), _year_of(_pt)
            _m = re.match(r"(\d{4})\D+(\d{2,4})", str(active_fy).strip()) if active_fy else None
            if _m and _y_from:
                _exp_from = int(_m.group(1))
                _e = _m.group(2)
                _exp_to = int(_e) if len(_e) == 4 else _exp_from + 1
                _bad = []
                if _y_from != _exp_from:
                    _bad.append(f"starts in <b>{_y_from}</b> (expected {_exp_from})")
                if _y_to and _y_to != _exp_to:
                    _bad.append(f"ends in <b>{_y_to}</b> (expected {_exp_to})")
                if _bad:
                    _fy_warn = f"⚠️ Does not match the selected FY <b>{active_fy}</b>."

            _period = f"{_pf} → {_pt}" if _pf and _pt else (_pf or "—")
            # Tally can't say which loaded company is active, so name it only
            # when there's exactly one; otherwise list them rather than guess.
            if _act:
                _co_line = f"📂 Company: <b>{_act}</b>"
            elif _cos:
                _co_line = ("📂 Companies loaded: <b>" + "</b>, <b>".join(_cos)
                            + "</b><br><span style='font-size:12px;'>Keep only one open "
                              "so this can confirm which is being extracted.</span>")
            else:
                _co_line = "📂 Company: <b>—</b>"

            _bg, _br, _fg = ("#ffebee", "#c62828", "#b71c1c") if _fy_warn \
                else ("#e8f5e9", "#2e7d32", "#1b5e20") if _act \
                else ("#fff8e1", "#ffa000", "#e65100")
            st.markdown(f"""
            <div style="background:{_bg}; border-left:4px solid {_br};
                        padding:10px 12px; border-radius:8px;
                        color:{_fg}; font-size:13px; margin:8px 0; line-height:1.8;">
                {_co_line}<br>
                📅 Period: <b>{_period}</b>
                {('<br>' + _fy_warn) if _fy_warn else ''}
            </div>
            """, unsafe_allow_html=True)

        elif "tally_connected" in st.session_state and \
                not st.session_state["tally_connected"]:
            st.markdown(
                '<div class="status-error">❌ Failed — Change Tally ODBC port to 9400</div>',
                unsafe_allow_html=True
            )

        st.markdown("<hr style='margin:8px 0;'>", unsafe_allow_html=True)

        # Company type is set on the company (creation / Manage) — shown here, not re-asked.
        concern_type = st.session_state.get("concern_type", "Single Company")
        if concern_type == "Group Concern":
            st.markdown(
                "<div style='background:#eef4fb;border-left:4px solid #1f4e79;"
                "padding:6px 10px;border-radius:6px;font-size:12px;'>🏢 <b>Group Concern</b>"
                " — extract each branch separately (one branch per run), then Consolidate.</div>",
                unsafe_allow_html=True)
            branch_name = st.text_input(
                "Branch Name",
                placeholder="e.g. Bangalore, Mumbai, HO...",
                key="branch_extract")
        else:
            st.caption("🏢 Single Company. Change to *Group Concern* in **Manage companies** "
                       "if this client has multiple branches.")
            branch_name = (company_name or "Main").strip().replace(" ", "_")

        if st.button("▶ Run Extraction", key="btn_extract",
                     width="stretch"):
            if not company_name:
                st.markdown(
                    '<div class="status-error">⚠️ Please select a company first.</div>',
                    unsafe_allow_html=True
                )
            elif not active_fy:
                st.markdown(
                    '<div class="status-error">⚠️ Please select a tax year first.</div>',
                    unsafe_allow_html=True
                )
            elif not st.session_state.get("tally_connected"):
                st.markdown(
                    '<div class="status-error">⚠️ Please connect to Tally first.</div>',
                    unsafe_allow_html=True
                )
            elif not branch_name:
                st.markdown(
                    '<div class="status-error">⚠️ Branch name is required.</div>',
                    unsafe_allow_html=True
                )
            else:
                base_dir = str(paths.extracted_dir(company_name, active_fy))
                txn_file = os.path.join(
                    base_dir,
                    f"{branch_name.strip().replace(' ', '_')}_Transactions.csv"
                )
                if os.path.exists(txn_file):
                    st.warning(
                        f"⚠️ Data for '{branch_name}' exists. Will be overwritten."
                    )
                with busy_overlay("Extracting data from Tally…"):
                    try:
                        time_taken = extract_engine.main(
                            company_name, active_fy, branch_name,
                            concern_type=st.session_state.get("concern_type", "Single Company")
                        )
                        st.session_state["extract_status"] = \
                            f"✅ Extracted in {time_taken} seconds"
                        st.session_state["extract_branch"] = branch_name
                    except Exception as e:
                        st.session_state["extract_status"] = f"❌ Error: {e}"

        # Persistent extract status
        if "extract_status" in st.session_state:
            color = "status-success" if "✅" in st.session_state["extract_status"] \
                else "status-error"
            st.markdown(
                f'<div class="{color}">{st.session_state["extract_status"]}</div>',
                unsafe_allow_html=True
            )

    # ── DIVIDER ───────────────────────────────────────────────────────────────
    with divider_col:
        st.markdown("""
        <div style="border-left: 2px solid #c5d8ec; 
                    height: 100%; 
                    min-height: 400px;
                    margin: 0 auto;">
        </div>
        """, unsafe_allow_html=True)

    # ── RIGHT: Consolidate ────────────────────────────────────────────────────
    with right_col:
        st.markdown("#### 2️⃣ Consolidate")

        if st.session_state.get("concern_type", "Single Company") == "Single Company":
            st.info("ℹ️ Not required for Single Company. Data is ready for Analysis.")
        elif st.button("▶ Run Consolidation", key="btn_consolidate",
                     width="stretch"):
            if not company_name:
                st.markdown(
                    '<div class="status-error">⚠️ Please select a company first.</div>',
                    unsafe_allow_html=True
                )
            elif not active_fy:
                st.markdown(
                    '<div class="status-error">⚠️ Please select a tax year first.</div>',
                    unsafe_allow_html=True
                )
            else:
                with busy_overlay("Consolidating…"):
                    try:
                        consolidate_engine.main(company_name, active_fy)

                        # Get branch info
                        extracted_dir = str(paths.extracted_dir(company_name, active_fy))
                        branch_files = [
                            f.replace("_Transactions.csv", "")
                            for f in os.listdir(extracted_dir)
                            if f.endswith("_Transactions.csv")
                        ] if os.path.exists(extracted_dir) else []

                        from datetime import datetime
                        conso_time = datetime.now().strftime("%d-%b-%Y %I:%M %p")

                        st.session_state["conso_status"] = "✅ Consolidation completed"
                        st.session_state["conso_branches"] = branch_files
                        st.session_state["conso_time"] = conso_time

                    except Exception as e:
                        st.session_state["conso_status"] = f"❌ Error: {e}"
                        st.session_state["conso_branches"] = []
                        st.session_state["conso_time"] = ""

        # Persistent consolidation status
        if "conso_status" in st.session_state:
            color = "status-success" if "✅" in st.session_state["conso_status"] \
                else "status-error"
            st.markdown(
                f'<div class="{color}">{st.session_state["conso_status"]}</div>',
                unsafe_allow_html=True
            )

            if st.session_state.get("conso_branches"):
                branches = st.session_state["conso_branches"]
                branch_list = " | ".join(branches)
                st.markdown(f"""
                <div style="background:#f0f4f8; border-radius:8px;
                            padding:10px 14px; margin-top:8px;
                            font-size:13px;">
                    <b>Branches ({len(branches)}):</b><br>
                    {branch_list}<br><br>
                    <b>Last Consolidated:</b> 
                    {st.session_state.get('conso_time', '')}
                </div>
                """, unsafe_allow_html=True)


# ── Page: Analysis ────────────────────────────────────────────────────────────
if _page == "analysis":
    if company_name and not active_fy:
        st.warning("⚠️ Select or create a **Tax Year** in the header to begin.")
    analysis_info = company_info.get_analysis_info(company_name, active_fy) if active_fy else {}
    if analysis_info:
        st.markdown(f"""
        <div style="background:#f0f4f8; border-radius:8px;
                    padding:10px 14px; margin-bottom:10px;
                    border-left:4px solid #1f4e79; font-size:12px;">
            🕒 <b>Last Analysis Run:</b> {analysis_info.get('last_run','')} &nbsp;|&nbsp;
            📋 <b>Reports:</b> {', '.join(analysis_info.get('reports', []))}
        </div>
        """, unsafe_allow_html=True)
    st.markdown("""
    <div class="card">
        <div class="card-title">3️⃣ Analysis</div>
        <div class="card-desc">
            Run TDS and expense analysis reports on consolidated data.
            Output saved to <code>data/{company}/analysis/</code>
        </div>
    </div>
    """, unsafe_allow_html=True)

    a_left, a_div, a_right = st.columns([10, 1, 10])

    # ── LEFT: Inputs ──────────────────────────────────────────────────────────
    with a_left:
        st.markdown("#### 📂 Inputs")

        # Select Reports — the three core reports are bundled under one UI option.
        # Picking a group expands to its real backend report names, so downstream
        # logic and the engine are unchanged.
        REPORT_GROUPS = {
            "Basic reports for TDS analysis": [
                "Final_Merged_Report",
                "Purchase_Analysis",
                "Sales_Analysis",
            ],
            "GST_Analysis": ["GST_Analysis"],
        }
        selected_groups = st.multiselect(
            "Select Reports to Generate",
            options=list(REPORT_GROUPS.keys()),
            key="selected_report_groups"
        )
        selected_reports = []
        for _grp in selected_groups:
            selected_reports.extend(REPORT_GROUPS[_grp])

        st.markdown("<hr style='margin:8px 0;'>", unsafe_allow_html=True)

        # Upload CSVs
        # Auto-load from consolidated folder
        consolidated_dir = str(paths.consolidated_dir(company_name, active_fy)) if active_fy else ""
        auto_csv_paths = []
        if company_name and os.path.exists(consolidated_dir):
            auto_csv_paths = sorted([
                os.path.join(consolidated_dir, f)
                for f in os.listdir(consolidated_dir)
                if f.startswith("Transactions_") and f.endswith(".csv")
            ])

        if auto_csv_paths:
            st.markdown(
                f'<div class="status-success">✅ {len(auto_csv_paths)} consolidated file(s) auto-loaded.</div>',
                unsafe_allow_html=True
            )
        else:
            st.markdown(
                '<div class="status-error">⚠️ No consolidated files found. Run consolidation first.</div>',
                unsafe_allow_html=True
            )

        # Winman holds the TDS actually deposited — needed only for the TDS
        # comparison. A GST-only run doesn't use it, so don't ask for it.
        _needs_winman = "Final_Merged_Report" in selected_reports
        uploaded_winman = None
        if _needs_winman:
            uploaded_winman = st.file_uploader(
                "Upload Winman TDS Register (Excel)",
                type=["xlsx"],
                key="winman_file"
            )
            winman_template = tds_engine.create_winman_template()
            st.download_button(
                "📥 Download Manual Entry Template",
                data=winman_template,
                file_name="Winman_Manual_Template.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                key="btn_winman_template"
            )
        elif selected_reports:
            st.caption("ℹ️ Winman TDS register not needed for the selected report(s).")

    # ── DIVIDER ───────────────────────────────────────────────────────────────
    with a_div:
        st.markdown("""
        <div style="border-left: 2px solid #c5d8ec;
                    height: 100%;
                    min-height: 400px;
                    margin: 0 auto;">
        </div>
        """, unsafe_allow_html=True)

    # ── RIGHT: Filters + Run ──────────────────────────────────────────────────
    with a_right:
        st.markdown("#### 🔧 Filters & Run")

        # TDS Ledgers & Party Exclusion
        selected_tds_ledgers = None
        excluded_parties = None
        selected_expenses = None

        filter_json_path = str(paths.consolidated_dir(company_name, active_fy) / "Filter_Options.json") \
            if active_fy else ""
        filter_options = {}
        if filter_json_path and os.path.exists(filter_json_path):
            import json
            with open(filter_json_path) as f:
                filter_options = json.load(f)

        if filter_options:
            try:
                preview_data = pd.DataFrame({
                    '$Particulars'  : filter_options.get('tds_ledgers', []),
                    '$Led_BaseGroup': ['Duties & Taxes'] * len(
                        filter_options.get('tds_ledgers', [])),
                    '$Party_LedName': filter_options.get('party_names', [])[:len(
                        filter_options.get('tds_ledgers', []))],
                    '$Led_Group'    : [''] * len(
                        filter_options.get('tds_ledgers', []))
                })

                # TDS Ledger multiselect
                if filter_options:
                    tds_ledger_options = filter_options.get('tds_ledgers', [])
                    select_all_tds = st.checkbox(
                        "Select All TDS Ledgers",
                        key="select_all_tds"
                    )
                    saved_tds = company_info.get_tds_selection(company_name, active_fy)
                    default_tds = [x for x in saved_tds if x in tds_ledger_options] or tds_ledger_options
                    if select_all_tds:
                        st.session_state["selected_tds_ledgers"] = tds_ledger_options
                    selected_tds_ledgers = st.multiselect(
                        "Select TDS Ledgers to Include",
                        options=tds_ledger_options,
                        default=st.session_state.get("selected_tds_ledgers", default_tds),
                        key="selected_tds_ledgers"
                    )

                # Party exclusion
                if filter_options:
                    party_options = filter_options.get('party_names', [])
                    saved_excluded = company_info.get_excluded_parties(company_name, active_fy)
                    default_excluded = [x for x in saved_excluded if x in party_options]
                    excluded_parties = st.multiselect(
                        "Exclude Party Ledger Names (optional)",
                        options=party_options,
                        default=default_excluded,
                        key="excluded_parties"
                    )

            except Exception as e:
                st.markdown(
                    f'<div class="status-error">⚠️ Could not load filters: {e}</div>',
                    unsafe_allow_html=True
                )
                
        # Final Merged Report uses ALL expenses by default — no selection UI shown.
        if "Final_Merged_Report" in selected_reports and filter_options:
            try:
                selected_expenses = filter_options.get('expenses', [])
            except Exception as e:
                st.markdown(
                    f'<div class="status-error">⚠️ Could not load expenses: {e}</div>',
                    unsafe_allow_html=True
                )

        st.markdown("<hr style='margin:8px 0;'>", unsafe_allow_html=True)
        # GST Ledger selection — only when GST_Analysis selected
        if "GST_Analysis" in selected_reports and filter_options:
            gst_ledger_options = filter_options.get('gst_ledgers', [])
            saved_gst = company_info.get_gst_selection(company_name, active_fy)
            default_gst = [x for x in saved_gst if x in gst_ledger_options] or gst_ledger_options
            select_all_gst = st.checkbox("Select All GST Ledgers", key="select_all_gst")
            selected_gst_ledgers = st.multiselect(
                "Select GST Ledgers",
                options=gst_ledger_options,
                default=gst_ledger_options if select_all_gst else default_gst,
                key="selected_gst_ledgers"
            )
        
       
        st.markdown("<hr style='margin:8px 0;'>", unsafe_allow_html=True)

        # Run button
        if st.button("▶ Run Analysis", key="btn_analysis",
                     width="stretch"):
            if not company_name:
                st.markdown(
                    '<div class="status-error">⚠️ Please select a company first.</div>',
                    unsafe_allow_html=True
                )
            elif not active_fy:
                st.markdown(
                    '<div class="status-error">⚠️ Please select a tax year first.</div>',
                    unsafe_allow_html=True
                )
            elif not selected_reports:
                st.markdown(
                    '<div class="status-error">⚠️ Please select at least one report.</div>',
                    unsafe_allow_html=True
                )
            elif not auto_csv_paths:
                st.markdown(
                    '<div class="status-error">⚠️ No consolidated files found. Run consolidation first.</div>',
                    unsafe_allow_html=True
                )
            elif _needs_winman and not uploaded_winman:
                st.markdown(
                    '<div class="status-error">⚠️ Please upload Winman Excel file.</div>',
                    unsafe_allow_html=True
                )
            elif "Final_Merged_Report" in selected_reports and not selected_expenses:
                st.markdown(
                    '<div class="status-error">⚠️ Please select at least one expense.</div>',
                    unsafe_allow_html=True
                )
            else:
                # Save temp files
                temp_dir = os.path.join(os.path.expanduser('~'), "Documents", "LSTool", "temp_analysis")
                os.makedirs(temp_dir, exist_ok=True)

                temp_csv_paths = auto_csv_paths  # use directly, no temp copy needed

                temp_winman = None
                if uploaded_winman is not None:
                    temp_winman = os.path.join(temp_dir, uploaded_winman.name)
                    with open(temp_winman, "wb") as out:
                        out.write(uploaded_winman.getbuffer())

                with busy_overlay("Running analysis…"):
                    try:
                        company_info.save_tds_selection(
                            company_name, active_fy,
                            st.session_state.get("selected_tds_ledgers", [])
                        )
                        if "GST_Analysis" in selected_reports:
                            company_info.save_gst_selection(
                                company_name, active_fy,
                                st.session_state.get("selected_gst_ledgers", [])
                            )
                        tds_engine.main(
                            selected_reports=selected_reports,
                            input_files=temp_csv_paths,
                            winman_file=temp_winman,
                            company_name=company_name,
                            fy=active_fy,
                            selected_expenses=selected_expenses,
                            selected_tds_ledgers=selected_tds_ledgers,
                            excluded_parties=excluded_parties,
                            selected_gst_ledgers=st.session_state.get("selected_gst_ledgers", [])
                        )
                        # Cleanup temp files
                        if temp_winman and os.path.exists(temp_winman):
                            os.remove(temp_winman)

                        st.session_state["analysis_status"] = \
                            "✅ Analysis completed successfully!"

                        # Open analysis folder
                        analysis_folder = str(paths.analysis_dir(company_name, active_fy))
                        if os.path.exists(analysis_folder):
                            try:
                                os.startfile(analysis_folder)
                            except Exception:
                                pass

                        # Check PAN Override
                        pan_override_path = str(paths.analysis_dir(company_name, active_fy) / "PAN_Override.xlsx")
                        if os.path.exists(pan_override_path):
                            st.session_state["pan_warning"] = True
                        else:
                            st.session_state["pan_warning"] = False

                    except Exception as e:
                        st.session_state["analysis_status"] = f"❌ Error: {e}"
                        st.session_state["pan_warning"] = False

        # Persistent status
        if "analysis_status" in st.session_state:
            color = "status-success" \
                if "✅" in st.session_state["analysis_status"] \
                else "status-error"
            st.markdown(
                f'<div class="{color}">{st.session_state["analysis_status"]}</div>',
                unsafe_allow_html=True
            )

        if st.session_state.get("pan_warning"):
            st.warning(
                "⚠️ Missing PANs found!\n\n"
                "1. Open `PAN_Override.xlsx` from analysis folder\n"
                "2. Fill the yellow PAN column\n"
                "3. Save in same analysis folder\n"
                "4. Run Analysis again\n\n"
                "💡 Also update PAN in Tally permanently."
            )

# ── Page: TDS Rules ───────────────────────────────────────────────────────────
if _page == "tdsrules":
    st.markdown("""
    <div class="card">
        <div class="card-title">📐 TDS Section Mapping Rules</div>
        <div class="card-desc">Map expense ledgers to TDS sections. Search, select and apply.</div>
    </div>
    """, unsafe_allow_html=True)

    if not company_name:
        st.markdown('<div class="status-error">⚠️ Select a company first.</div>',
                    unsafe_allow_html=True)
    elif not active_fy:
        st.markdown('<div class="status-error">⚠️ Select a tax year first.</div>',
                    unsafe_allow_html=True)
    else:
        is_saved = tds_rules_engine.rules_exist(company_name, active_fy)
        sys_sections = tds_rules_engine.get_system_sections()

        # ── Status + Action bar ───────────────────────────────────────────────
        sb1, sb2, sb3 = st.columns([4, 1, 1])
        with sb1:
            st.markdown(
                f'<div class="{"status-success" if is_saved else "status-running"}" style="padding:8px 12px;">'
                f'{"✅ Saved rules loaded" if is_saved else "⚠️ Auto-mapped — not saved yet"}'
                f'</div>', unsafe_allow_html=True)

        # ── Manage Sections expander ──────────────────────────────────────────
        with st.expander("⚙️ Manage Word Rules & Sections"):
            merged_df = tds_rules_engine.get_merged_rules_df()

            edited_df = st.data_editor(
                merged_df,
                width="stretch",
                num_rows="dynamic",
                column_config={
                    "Keywords"  : st.column_config.TextColumn("Keywords (comma separated)", width="large"),
                    "Section"   : st.column_config.TextColumn("Section", width="small"),
                    "Rate_%"    : st.column_config.NumberColumn("Rate %", min_value=0, max_value=100, step=0.1),
                    "Threshold" : st.column_config.NumberColumn("Threshold ₹", min_value=0, step=1000),
                    "Type"      : st.column_config.SelectboxColumn("Type", options=["TDS","NON-TDS","slab","skip"])
                },
                hide_index=True,
                key="word_rules_editor"
            )

            if st.button("💾 Save Master Rules", key="btn_save_word_rules"):
                tds_rules_engine.save_merged_rules_df(edited_df)
                st.session_state["word_rules_saved"] = True
                st.rerun()

            if st.session_state.get("word_rules_saved"):
                st.success("✅ Word rules saved!")
                st.warning(
                    "⚠️ Do you want to update rates in current mapping? "
                    "Section assignments will be kept — only rates will be refreshed.")
                ra1, ra2 = st.columns(2)
                with ra1:
                    if st.button("✅ Yes, Update Rates", key="btn_reapply_rates"):
                        tds_rules_engine.reapply_rates_from_word_rules(company_name, active_fy)
                        st.session_state.pop("word_rules_saved", None)
                        st.success("✅ Rates updated!")
                        st.rerun()
                with ra2:
                    if st.button("❌ Keep Existing", key="btn_keep_rates"):
                        st.session_state.pop("word_rules_saved", None)
                        st.rerun()

        # ── Load rules ────────────────────────────────────────────────────────
        filter_json = str(paths.consolidated_dir(company_name, active_fy) / "Filter_Options.json")
        expense_ledgers = []
        if os.path.exists(filter_json):
            with open(filter_json) as f:
                fo = json.load(f)
            expense_ledgers = fo.get('expenses', [])

        if not expense_ledgers:
            st.info("Run consolidation first to load expense ledgers.")
        else:
            if "edited_rules" in st.session_state:
                rules = st.session_state["edited_rules"]
            else:
                rules = tds_rules_engine.get_effective_rules(company_name, active_fy, expense_ledgers)

            st.markdown("<hr style='margin:8px 0;'>", unsafe_allow_html=True)

            # ── Apply section to selected ledgers ─────────────────────────────
            st.markdown("#### 🎯 Check the current mapping update if required")
            
            # Pre-build mapping data before columns
            mapped_rows, unmapped_rows = [], []
            for ledger in expense_ledgers:
                rule   = rules.get(ledger, {})
                typ    = rule.get('type', 'Unmapped')
                status = "✅" if typ == 'TDS' else ("🔴" if typ == 'NON-TDS' else "⚠️")
                row = {
                    'Select' : False,
                    'Ledger' : ledger,
                    'Section': rule.get('section') or '—',
                    'Status' : status
                }
                if typ == 'Unmapped':
                    unmapped_rows.append(row)
                else:
                    mapped_rows.append(row)
            mapping_display_df = pd.DataFrame(mapped_rows + unmapped_rows)

            tds_left, tds_right = st.columns([1, 2])

            with tds_left:
                st.markdown("#### 🎯 Filter & Apply")
                filter_status = st.selectbox(
                    "Show",
                    ["All", "Unmapped", "Mapped", "NON-TDS"],
                    key="rule_filter_status"
                )

                # Filter the ledger list by the "Show" choice.
                _view_rows = mapping_display_df.to_dict('records')
                if filter_status == "Unmapped":
                    _view_rows = [r for r in _view_rows if r['Status'] == '⚠️']
                elif filter_status == "Mapped":
                    _view_rows = [r for r in _view_rows if r['Status'] == '✅']
                elif filter_status == "NON-TDS":
                    _view_rows = [r for r in _view_rows if r['Status'] == '🔴']
                view_df = pd.DataFrame(_view_rows)

                # Select ledgers by NAME (robust — no row-index/filter mismatch).
                ledger_choices = view_df['Ledger'].tolist() if not view_df.empty else []
                # Drop any stale selections the current filter no longer shows,
                # so the multiselect never errors on values outside its options.
                if "map_ledger_select" in st.session_state:
                    st.session_state["map_ledger_select"] = [
                        l for l in st.session_state["map_ledger_select"] if l in ledger_choices
                    ]
                selected_ledgers = st.multiselect(
                    "Select ledgers to map",
                    options=ledger_choices,
                    key="map_ledger_select",
                    placeholder="Pick one or more ledgers..."
                )

                apply_section = st.selectbox(
                    "TDS Section",
                    [""] + list(sys_sections.keys()),
                    key="apply_section"
                )

                if st.button("✅ Apply to Selected", key="btn_apply_section",
                             width="stretch"):
                    if selected_ledgers and apply_section:
                        for ledger in selected_ledgers:
                            sec_info = sys_sections.get(apply_section, {})
                            rate_val = sec_info.get('default_rate')
                            rules[ledger] = {
                                "section": apply_section,
                                "rate"   : rate_val,
                                "type"   : "NON-TDS" if apply_section == "NON-TDS" else "TDS"
                            }
                        st.session_state["edited_rules"] = rules
                        st.success(f"✅ Applied {apply_section} to {len(selected_ledgers)} ledgers")
                        st.rerun()
                    else:
                        st.warning("Select ledgers and a TDS section first.")

                st.markdown("<hr style='margin:4px 0;'>", unsafe_allow_html=True)

                if st.button("💾 Save Ledger Mapping", key="btn_save_rules",
                             width="stretch"):
                    tds_rules_engine.save_rules(company_name, active_fy, rules)
                    if "edited_rules" in st.session_state:
                        del st.session_state["edited_rules"]
                    st.success("✅ Saved!")
                    st.rerun()

                if st.button("🔄 Reset to Auto-rules", key="btn_reset_rules",
                             width="stretch"):
                    st.session_state["confirm_reset"] = True

                if st.session_state.get("confirm_reset"):
                    st.warning("⚠️ All changes lost!")
                    r1, r2 = st.columns(2)
                    with r1:
                        if st.button("✅ Yes", key="btn_confirm_reset"):
                            tds_rules_engine.reset_rules(company_name, active_fy)
                            st.session_state.pop("confirm_reset", None)
                            st.session_state.pop("edited_rules", None)
                            st.rerun()
                    with r2:
                        if st.button("❌ No", key="btn_cancel_reset"):
                            st.session_state.pop("confirm_reset", None)
                            st.rerun()

            with tds_right:
                st.markdown("#### 📋 Current Mapping")

                if not view_df.empty:
                    import html as _html
                    _trs = ""
                    for _r in view_df.to_dict('records'):
                        _trs += (
                            "<tr>"
                            f"<td class='lg'>{_html.escape(str(_r['Ledger']))}</td>"
                            f"<td class='sec'>{_html.escape(str(_r['Section']))}</td>"
                            f"<td class='stt'>{_r['Status']}</td>"
                            "</tr>"
                        )
                    st.markdown(
                        """
                        <style>
                        .lsmap-wrap { max-height:480px; overflow-y:auto; border:1px solid #e0e0e0; border-radius:6px; }
                        .lsmap { width:100%; border-collapse:collapse; font-size:13px; }
                        .lsmap th, .lsmap td { border-bottom:1px solid #ececec; padding:6px 8px; text-align:left; vertical-align:top; }
                        .lsmap th { background:#1f4e79; color:#fff; position:sticky; top:0; z-index:1; }
                        .lsmap td.lg  { white-space:normal; word-break:break-word; }
                        .lsmap td.sec { width:90px; white-space:normal; word-break:break-word; }
                        .lsmap td.stt { width:36px; text-align:center; }
                        </style>
                        """
                        + f"<div class='lsmap-wrap'><table class='lsmap'>"
                        + "<thead><tr><th>Ledger</th><th>Section</th><th>S</th></tr></thead>"
                        + f"<tbody>{_trs}</tbody></table></div>",
                        unsafe_allow_html=True
                    )
                    st.markdown(
                        f"**{len(mapped_rows)} mapped | {len(unmapped_rows)} unmapped**")
                else:
                    st.info("No ledgers match this filter.")
            
# ── Tab 5: Ledger Scrutiny ────────────────────────────────────────────────────
from engines.ls_engine import SCRUTINY_REMARKS
if _page == "scrutiny":
    st.markdown("""
    <div class="card">
        <div class="card-title">📘 Step 4 — Ledger Scrutiny</div>
        <div class="card-desc">
            Run ledger scrutiny checks on consolidated master data.
            Output saved to <code>data/{company}/analysis/</code>
        </div>
    </div>
    """, unsafe_allow_html=True)

    # ── Opening Balance Check ─────────────────────────────────────────────────
    st.markdown("#### 📂 Opening Balance Check (Optional)")
    ob_mode = st.radio(
        "Previous Year Data",
        options=["Skip", "Upload File", "Extract from Tally"],
        horizontal=True,
        key="ob_mode"
    )

    prev_year_path = None

    if ob_mode == "Upload File":
        # Template download
        template_df = pd.DataFrame(columns=['Ledger Name', 'Closing Balance'])
        template_note = pd.DataFrame([['Note: Debit balance = Negative, Credit balance = Positive', '']],
                                      columns=['Ledger Name', 'Closing Balance'])
        template_out = io.BytesIO()
        with pd.ExcelWriter(template_out, engine='openpyxl') as tw:
            pd.concat([template_note, template_df]).to_excel(tw, index=False, sheet_name='PrevYear')
        template_out.seek(0)
        st.download_button(
            "📥 Download Template",
            data=template_out,
            file_name="PrevYear_Template.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            key="btn_prevyr_template"
        )
        uploaded_prev = st.file_uploader(
            "Upload Previous Year Closing Balances",
            type=["xlsx", "csv"],
            key="prev_year_upload"
        )
        if uploaded_prev:
            save_path = str(paths.consolidated_dir(company_name, active_fy) / "PrevYear_Conso_MasterData.csv")
            if uploaded_prev.name.endswith('.csv'):
                prev_df = pd.read_csv(uploaded_prev)
            else:
                prev_df = pd.read_excel(uploaded_prev)
            prev_df.columns = ['$Name', '$ClosingBalance']
            prev_df['$Nature_Led'] = 'BS'
            os.makedirs(os.path.dirname(save_path), exist_ok=True)
            prev_df.to_csv(save_path, index=False)
            prev_year_path = save_path
            st.success("✅ File uploaded and saved.")

    elif ob_mode == "Extract from Tally":
        ob_branch = st.text_input(
            "Branch Name",
            placeholder="e.g. HO, Bangalore...",
            key="ob_branch"
        )
        if st.button("▶ Extract Previous Year Master", key="btn_extract_prev",
                     width="content"):
            if not company_name:
                st.error("⚠️ Select company first.")
            elif not ob_branch:
                st.error("⚠️ Enter branch name.")
            else:
                with busy_overlay("Extracting previous year master…"):
                    try:
                        from engines import extract_engine as ee
                        out = ee.extract_prev_year_master(
                            company_name, active_fy, ob_branch,
                            concern_type=st.session_state.get("concern_type", "Single Company")
                        )
                        st.session_state["prev_extract_status"] = f"✅ Saved: {out}"
                    except Exception as e:
                        st.session_state["prev_extract_status"] = f"❌ {e}"

        if "prev_extract_status" in st.session_state:
            color = "status-success" if "✅" in st.session_state["prev_extract_status"] else "status-error"
            st.markdown(f'<div class="{color}">{st.session_state["prev_extract_status"]}</div>',
                        unsafe_allow_html=True)

        # Group Concern — show consolidate button
        extracted_dir = str(paths.extracted_dir(company_name, active_fy))
        prev_files = [f for f in os.listdir(extracted_dir)
                      if f.startswith("PrevYear_") and f.endswith("_MasterData.csv")] \
                      if os.path.exists(extracted_dir) else []

        if prev_files:
            _pb = [f[len("PrevYear_"):-len("_MasterData.csv")] for f in prev_files]
            st.info(f"ℹ️ Previous-year extracts found for: **{', '.join(sorted(_pb))}** — the OB "
                    "check runs **branch-wise** (each branch's opening vs its OWN previous-year "
                    "closing). Branches without a PY extract are skipped — extract them too for "
                    "full coverage.")
            if st.button("▶ Consolidate Previous Year", key="btn_conso_prev",
                         width="content"):
                with busy_overlay("Consolidating…"):
                    try:
                        from engines import consolidate_engine as ce
                        out = ce.consolidate_prev_year(company_name, active_fy)
                        st.session_state["prev_conso_status"] = f"✅ Consolidated: {out}"
                    except Exception as e:
                        st.session_state["prev_conso_status"] = f"❌ {e}"
            if "prev_conso_status" in st.session_state:
                color = "status-success" if "✅" in st.session_state["prev_conso_status"] else "status-error"
                st.markdown(f'<div class="{color}">{st.session_state["prev_conso_status"]}</div>',
                            unsafe_allow_html=True)

        # Set prev_year_path if file exists
        prev_conso = str(paths.consolidated_dir(company_name, active_fy) / "PrevYear_Conso_MasterData.csv")
        if len(prev_files) == 1:
            prev_year_path = os.path.join(extracted_dir, prev_files[0])
        elif os.path.exists(prev_conso):
            prev_year_path = prev_conso

    if prev_year_path:
        st.session_state["prev_year_path"] = prev_year_path
    elif ob_mode == "Skip":
        st.session_state.pop("prev_year_path", None)

    st.markdown("<hr style='margin:8px 0;'>", unsafe_allow_html=True)

    sc_top1, sc_top2, sc_top3 = st.columns([3, 3, 3])
    with sc_top1:
        if st.button("▶ Run Ledger Scrutiny", key="btn_scrutiny",
                     width="stretch"):
            if not company_name:
                st.markdown('<div class="status-error">⚠️ Please select a company first.</div>',
                            unsafe_allow_html=True)
            elif not active_fy:
                st.markdown('<div class="status-error">⚠️ Please select a tax year first.</div>',
                            unsafe_allow_html=True)
            else:
                with busy_overlay("Running ledger scrutiny…"):
                    try:
                        result = ls_runner.run_ls_for_company(
                            company_name, active_fy,
                            prev_year_path=st.session_state.get("prev_year_path")
                        )
                        if result["status"] == "warning":
                            st.session_state["scrutiny_status"] = f"⚠️ {result['message']}"
                        else:
                            st.session_state["scrutiny_status"] = f"✅ {result['message']}"
                            st.balloons()
                    except Exception as e:
                        st.session_state["scrutiny_status"] = f"❌ Error: {e}"

    if "scrutiny_status" in st.session_state:
        color = "status-success" if "✅" in st.session_state["scrutiny_status"] \
            else "status-running" if "⚠️" in st.session_state["scrutiny_status"] \
            else "status-error"
        st.markdown(
            f'<div class="{color}">{st.session_state["scrutiny_status"]}</div>',
            unsafe_allow_html=True)

    st.markdown("<hr style='margin:8px 0;'>", unsafe_allow_html=True)
    st.markdown("#### 📋 Scrutiny Viewer")

    scrutiny_files = viewer_engine.get_scrutiny_files(company_name, active_fy) if (company_name and active_fy) else []

    if not scrutiny_files:
        st.markdown('<div class="status-running">ℹ️ No scrutiny reports found. Run scrutiny first.</div>',
                    unsafe_allow_html=True)
    else:
        sf_col1, sf_col2 = st.columns([4, 1])
        with sf_col1:
            selected_sc_file = st.selectbox(
                "Scrutiny File",
                options=scrutiny_files,
                key="scrutiny_file",
                label_visibility="collapsed"
            )
        with sf_col2:
            load_sc = st.button("📂 Load", key="btn_load_scrutiny",
                                width="stretch")

        if load_sc or st.session_state.get("scrutiny_loaded_file") != selected_sc_file:
            try:
                sc_data = viewer_engine.load_scrutiny_report(company_name, active_fy, selected_sc_file)
                st.session_state["scrutiny_data"] = sc_data
                st.session_state["scrutiny_loaded_file"] = selected_sc_file
            except Exception as e:
                st.error(f"❌ {e}")

        if "scrutiny_data" in st.session_state:
            sc_data = st.session_state["scrutiny_data"]

            # Collapse all open expanders: bump a counter that changes every
            # expander label (invisible zero-width suffix) -> fresh widgets,
            # which default to collapsed.
            if st.button("➖ Minimise all", key="btn_sc_minimise"):
                st.session_state["sc_min_ver"] = st.session_state.get("sc_min_ver", 0) + 1
                st.rerun()
            _zw = "​" * st.session_state.get("sc_min_ver", 0)

            for idx, (sheet_name, df) in enumerate(
                {k: v for k, v in sc_data.items() if k != 'Index'}.items(), start=1):
                row_count = len(df)
                if row_count == 0:
                    badge_color = "#e8f5e9"
                    badge_text  = "#2e7d32"
                    badge_label = "0 rows"
                elif row_count <= 5:
                    badge_color = "#fff8e1"
                    badge_text  = "#e65100"
                    badge_label = f"{row_count} rows"
                else:
                    badge_color = "#ffebee"
                    badge_text  = "#c62828"
                    badge_label = f"{row_count} rows"
                
                from engines.ls_engine import SCRUTINY_REMARKS
                info         = SCRUTINY_REMARKS.get(sheet_name, {})
                display_name = info.get('title', sheet_name.replace("_", " "))
                label = (
                    f"{idx}. {display_name} &nbsp;"
                    f'<span style="background:{badge_color}; color:{badge_text}; '
                    f'font-size:11px; padding:2px 10px; border-radius:6px;">'
                    f'{badge_label}</span>'
                )

                with st.expander(f"{idx}. {display_name} — {badge_label}{_zw}"):
                        info = SCRUTINY_REMARKS.get(sheet_name, {})
                        if info.get('remarks') or info.get('action'):
                            st.markdown(f"""
                            <div style="background:#f0f4f8; border-left:4px solid #2e75b6;
                                        padding:8px 12px; border-radius:6px;
                                        font-size:12px; margin-bottom:8px;">
                                {"<b>📌 Remarks:</b> " + info['remarks'] + "<br>" if info.get('remarks') else ""}
                                {"<b>✅ Action:</b> " + info['action'] if info.get('action') else ""}
                            </div>
                            """, unsafe_allow_html=True)
                        dfx = _arrow_safe(df)
                        if df.empty:
                            st.success("✅ No issues found.")
                        else:
                            # counts stay plain numbers, not rupee-formatted
                            _skip_sc = ['$VoucherNumber', 'VoucherNumber',
                                        'No_of_Invoices', 'Months Present',
                                        'Months Missing']

                            def fmt_sc(styler):
                                num_cols = [c for c in dfx.select_dtypes(include='number').columns
                                            if c not in _skip_sc]
                                return styler.format({c: lambda x: indian_format(x) if pd.notna(x) else '' for c in num_cols})
                            safe_styled_df(
                                dfx, fmt_sc, skip_fmt=_skip_sc,
                                hide_index=True,
                                width="stretch",
                                height=min(len(df) * 30 + 36, 400)
                            )
                        out_sc = io.BytesIO()
                        with pd.ExcelWriter(out_sc, engine='openpyxl') as writer:
                            df.to_excel(writer, sheet_name=sheet_name[:31], index=False)
                        out_sc.seek(0)
                        st.download_button(
                            "📥 Download",
                            data=out_sc,
                            file_name=f"{sheet_name}_{company_name}.xlsx",
                            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                            key=f"btn_dl_sc_{idx}"
                        )

# ── Tab 4: Viewer ─────────────────────────────────────────────────────────────
if _page == "viewer":
    if not tds_rules_engine.rules_exist(company_name, active_fy):
        st.warning("⚠️ Please save TDS Rules first before using TDS Compliance Reports.")
        st.stop()
if _page == "viewer":
    if not company_name:
        st.markdown('<div class="status-error">⚠️ Please select a company first.</div>',
                    unsafe_allow_html=True)
    else:
        analysis_files = viewer_engine.get_analysis_files(company_name, active_fy)

        if not analysis_files:
            st.markdown('<div class="status-running">ℹ️ No analysis files found. Please run Analysis first.</div>',
                        unsafe_allow_html=True)
        else:
            # ── File selector row ─────────────────────────────────────────────
            # Compact font so long run-file names are readable in the dropdown.
            st.markdown(
                "<style>div[data-baseweb='select']>div{font-size:11px;min-height:30px;}"
                "ul[role='listbox'] li,div[data-baseweb='popover'] li{font-size:11px;}</style>",
                unsafe_allow_html=True)
            fa, fb, fc, fd = st.columns([5, 1, 1, 3])
            with fa:
                selected_file = st.selectbox(
                    "Analysis File",
                    options=analysis_files,
                    key="viewer_file",
                    label_visibility="collapsed"
                )
            with fb:
                load_clicked = st.button("📂 Load", key="btn_load_viewer",
                                         width="stretch")
            with fc:
                with st.popover("🗑", use_container_width=True):
                    st.caption(f"Delete this run file?\n\n**{selected_file}**\n\nThis cannot be undone.")
                    if st.button("Yes, delete", key="btn_del_viewer", type="primary"):
                        try:
                            if viewer_engine.delete_analysis_file(company_name, active_fy, selected_file):
                                if st.session_state.get("viewer_loaded_file") == selected_file:
                                    for _k in ("viewer_all", "viewer_loaded_file", "viewer_file"):
                                        st.session_state.pop(_k, None)
                                st.toast("Run file deleted", icon="🗑️")
                            st.rerun()
                        except Exception as e:
                            st.error(f"Could not delete: {e}")
            if load_clicked or st.session_state.get("viewer_loaded_file") != selected_file:
                try:
                    all_data = viewer_engine.load_all(company_name, active_fy, selected_file)
                    st.session_state["viewer_all"] = all_data
                    st.session_state["viewer_loaded_file"] = selected_file
                    st.markdown('<div class="status-success">✅ Analysis loaded!</div>',
                                unsafe_allow_html=True)
                except Exception as e:
                    st.markdown(f'<div class="status-error">❌ {e}</div>',
                                unsafe_allow_html=True)

            # ── Main viewer ───────────────────────────────────────────────────
            if "viewer_all" in st.session_state:
                all_data = st.session_state["viewer_all"]
                df = all_data.get('expense', pd.DataFrame())
                pur_df = all_data.get('purchase', pd.DataFrame())
                sal_df = all_data.get('sales', pd.DataFrame())

                # ── Mode switch: Explorer (existing) vs Report Builder (new) ───
                _vmode = st.radio(
                    "TDS Compliance view", ["🔎 Explorer", "📤 Report Builder"],
                    horizontal=True, key="viewer_view_mode",
                    label_visibility="collapsed")

                if _vmode == "📤 Report Builder":
                    st.markdown("#### 📤 Report Builder — bucketed party-view export")
                    _heads = viewer_engine.list_expense_heads(all_data)
                    if not _heads:
                        st.info("No expense heads in this analysis file to report on.")
                        st.stop()
                    # Working copy lives in session so a CSV upload can rewrite it
                    # between runs; disk is only touched by "Save buckets".
                    _ctx = f"{company_name}|{active_fy}"
                    if st.session_state.get("rb_ctx") != _ctx:
                        st.session_state["rb_ctx"] = _ctx
                        st.session_state["rb_buckets"] = \
                            viewer_engine.load_report_buckets(company_name, active_fy)
                        for _k in ("rb_editor", "rb_groups_ed", "rb_up_stats", "rb_up_id"):
                            st.session_state.pop(_k, None)
                    _saved = st.session_state["rb_buckets"]

                    # ── Groups ────────────────────────────────────────────────
                    # A group's name IS its Excel sheet name, so name it for the
                    # report you want ("Professional Fees"), not "Group 1".
                    _gnames = viewer_engine.groups_of(_saved)
                    with st.expander(f"🏷️ Groups ({len(_gnames)})", expanded=not _gnames):
                        st.caption("Add a row per group. The name becomes the sheet tab "
                                   "and the Index entry in the generated report. "
                                   "Renaming a group sends its heads back to Standalone.")
                        _ged = st.data_editor(
                            pd.DataFrame({"Group Name": _gnames or [""]}),
                            hide_index=True, width="stretch", num_rows="dynamic",
                            key="rb_groups_ed",
                            column_config={"Group Name": st.column_config.TextColumn(
                                "Group Name", required=False)})
                        _gnames = viewer_engine.groups_of(
                            {"groups": list(_ged["Group Name"])})
                        _long = [g for g in _gnames if len(g) > 31]
                        if _long:
                            st.warning("Excel caps sheet names at 31 characters — these "
                                       "will be shortened in the workbook: "
                                       + ", ".join(_long))

                    _opts = viewer_engine.bucket_options(_gnames)
                    # Rebuild the grid whenever the dropdown options change, so no
                    # cell is left holding a bucket that no longer exists.
                    if st.session_state.get("rb_last_opts") != _opts:
                        st.session_state.pop("rb_editor", None)
                        st.session_state["rb_last_opts"] = list(_opts)
                    _assign = dict(_saved.get("assignments", {}))
                    _sug = viewer_engine.suggest_groups(_heads)
                    _rows = [{"Expense Head": h,
                              "Bucket": (_assign.get(h) if _assign.get(h) in _opts
                                         else viewer_engine.STANDALONE),
                              "Suggested": _sug.get(h, "")}
                             for h in _heads]
                    st.caption("Set each head's bucket: **Standalone** (its own sheet), "
                               "**Not for report** (excluded), or a **Group** (merged into "
                               "one sheet). Everything defaults to Standalone. "
                               "**Suggested** is read-only — heads whose names look "
                               "alike, e.g. every `R & M - …` ledger.")
                    _edited = st.data_editor(
                        pd.DataFrame(_rows), hide_index=True, width="stretch",
                        height=min(max(len(_rows) * 35 + 40, 200), 520), key="rb_editor",
                        column_config={
                            "Expense Head": st.column_config.TextColumn(
                                "Expense Head", disabled=True),
                            "Bucket": st.column_config.SelectboxColumn(
                                "Bucket", options=_opts, required=True),
                            "Suggested": st.column_config.TextColumn(
                                "Suggested", disabled=True,
                                help="Auto-grouped from the ledger name. Press "
                                     "'Apply suggestions' to fill these in."),
                        })
                    _new_assign = {r["Expense Head"]: r["Bucket"]
                                   for r in _edited.to_dict("records")}
                    _buckets = {"assignments": _new_assign, "groups": _gnames}
                    st.session_state["rb_buckets"] = _buckets

                    # ── Bulk edit (suggestions + CSV round-trip) ──────────────
                    st.markdown("###### 🔁 Bulk edit")
                    _n_sug = len({g for h, g in _sug.items()
                                  if _new_assign.get(h) == viewer_engine.STANDALONE})
                    ub1, uc1, uc2 = st.columns([1, 1, 2])
                    if ub1.button(f"✨ Apply suggestions ({_n_sug})", key="rb_apply_sug",
                                  width="stretch", disabled=not _n_sug,
                                  help="Fills only heads still on Standalone — your own "
                                       "choices and Not-for-report stay as they are."):
                        _nb, _nfill = viewer_engine.apply_suggestions(_heads, _buckets)
                        st.session_state["rb_buckets"] = _nb
                        st.session_state["rb_up_stats"] = None
                        st.session_state.pop("rb_editor", None)
                        st.session_state.pop("rb_groups_ed", None)
                        st.toast(f"{_nfill} head(s) grouped from suggestions", icon="✨")
                        st.rerun()
                    uc1.download_button(
                        "⬇️ Download bucket list (.csv)",
                        data=viewer_engine.bucket_list_csv_bytes(_heads, _buckets),
                        file_name=f"Bucket_List_{company_name}_{active_fy}.csv",
                        mime="text/csv", key="rb_dl_list", width="stretch",
                        help="Exports exactly what is in the grid above, including "
                             "edits you have not saved yet.")
                    _up = uc2.file_uploader(
                        "Upload filled bucket list (.csv)", type=["csv"],
                        key="rb_upload", label_visibility="collapsed")
                    st.caption("Type any name in the **Bucket** column to create a group "
                               "— put the same name against several heads and they merge "
                               "into one sheet. **Standalone** and **Not for report** are "
                               "reserved. Heads left out of the CSV keep their bucket.")
                    if _up is not None:
                        _uid = getattr(_up, "file_id", None) or (_up.name, _up.size)
                        if st.session_state.get("rb_up_id") != _uid:
                            st.session_state["rb_up_id"] = _uid
                            try:
                                _nb, _ustats = viewer_engine.parse_bucket_list_csv(
                                    _up, _heads, _buckets)
                                st.session_state["rb_buckets"] = _nb
                                st.session_state["rb_up_stats"] = _ustats
                                st.session_state.pop("rb_editor", None)
                                st.session_state.pop("rb_groups_ed", None)
                                st.rerun()
                            except Exception as _e:
                                st.error(f"❌ {_e}")
                    _ustats = st.session_state.get("rb_up_stats")
                    if _ustats:
                        _bits = [f"{_ustats['matched']} heads matched",
                                 f"{_ustats['updated']} changed"]
                        if _ustats["new_groups"]:
                            _bits.append(f"{len(_ustats['new_groups'])} new group(s): "
                                         + ", ".join(_ustats["new_groups"]))
                        st.success("✅ Bucket list imported — " + " · ".join(_bits))
                        if _ustats["unknown"]:
                            with st.expander(f"⚠️ {len(_ustats['unknown'])} head(s) in the "
                                             "CSV are not in this analysis — ignored"):
                                st.write("\n".join(f"- {u}" for u in _ustats["unknown"]))

                    _units = viewer_engine.compute_report_units(_heads, _buckets)
                    _nfr = sum(1 for b in _new_assign.values()
                               if b == viewer_engine.NOT_FOR_REPORT)
                    mc1, mc2, mc3 = st.columns(3)
                    mc1.metric("Report sheets", len(_units))
                    mc2.metric("Not for report", _nfr)
                    mc3.metric("Groups used",
                               sum(1 for u in _units if u["type"] == "Group"))
                    bc1, bc2 = st.columns(2)
                    if bc1.button("💾 Save buckets", key="rb_save", width="stretch"):
                        viewer_engine.save_report_buckets(company_name, active_fy, _buckets)
                        st.toast("Bucket allocation saved", icon="✅")
                    if bc2.button("📥 Generate report", key="rb_gen", width="stretch",
                                  type="primary"):
                        try:
                            _bytes = viewer_engine.build_bucket_report_excel(
                                company_name, active_fy, all_data, _buckets)
                            viewer_engine.save_report_buckets(company_name, active_fy, _buckets)
                            st.session_state["rb_report_bytes"] = _bytes
                            st.toast("Report generated", icon="✅")
                        except Exception as _e:
                            st.error(f"❌ {_e}")
                    if st.session_state.get("rb_report_bytes"):
                        st.download_button(
                            "⬇️ Download report (.xlsx)",
                            data=st.session_state["rb_report_bytes"],
                            file_name=f"TDS_Report_{company_name}_{active_fy}.xlsx",
                            mime=("application/vnd.openxmlformats-officedocument."
                                  "spreadsheetml.sheet"),
                            key="rb_dl", width="stretch")
                    st.stop()

                # ── Two column layout: sidebar + content ──────────────────────
                left, right = st.columns([1, 4])

                with left:
                    st.markdown("""
                    <div style="background:white; border-radius:10px;
                                padding:12px; box-shadow:0 2px 8px rgba(0,0,0,0.06);">
                        <div style="font-size:13px; font-weight:700;
                                    color:#1f4e79; margin-bottom:10px;">
                            🔍 Filters
                        </div>
                    </div>
                    """, unsafe_allow_html=True)

                    # Order: Base Group, Ledger Group, Ledger Parent, Expense Head, Party Name
                    base_group_options = sorted(
                        df['Base Group'].dropna().unique()
                    ) if not df.empty and 'Base Group' in df.columns else []
                    selected_base_groups = st.multiselect(
                        "Base Group", options=base_group_options, key="v_base_group")

                    led_group_options = sorted(
                        df['Ledger Group'].dropna().unique()) if not df.empty else []
                    selected_led_groups = st.multiselect(
                        "Ledger Group", options=led_group_options, key="v_led_group")

                    led_parent_options = sorted(
                        df['Ledger Parent'].dropna().unique()) if not df.empty else []
                    selected_led_parents = st.multiselect(
                        "Ledger Parent", options=led_parent_options, key="v_led_parent")

                    expense_options = sorted(
                        df['Expense Head'].dropna().unique()) if not df.empty else []
                    selected_expenses_v = st.multiselect(
                        "Expense Head", options=expense_options, key="v_expense")

                    all_parties = sorted(set(
                        list(df['Party Name'].dropna().unique() if not df.empty else []) +
                        list(pur_df['PartyLedgerName'].dropna().unique() if not pur_df.empty else []) +
                        list(sal_df['PartyLedgerName'].dropna().unique() if not sal_df.empty else [])
                    ))
                    selected_parties_v = st.multiselect(
                        "Party Name", options=all_parties, key="v_party")

                    st.markdown("<hr style='margin:8px 0;'>", unsafe_allow_html=True)

                    if st.button("🔄 Clear Filters", width="stretch",
                                 key="btn_clear_v"):
                        for k in ["v_base_group", "v_led_group", "v_led_parent",
                                  "v_expense", "v_party"]:
                            st.session_state.pop(k, None)
                        st.rerun()

                # Default to BLANK until a filter is chosen — loading every expense
                # up front was slow. Pick any filter on the left to populate.
                _any_v_filter = bool(selected_base_groups or selected_led_groups or
                                     selected_led_parents or selected_expenses_v or
                                     selected_parties_v)
                if not _any_v_filter:
                    with right:
                        st.info("⬅️ Pick a filter (Expense Head, Party, Base Group …) to load "
                                "data. Kept blank by default for faster loading.")
                    st.stop()

                # ── Apply filters ─────────────────────────────────────────────
                filtered_df = df.copy()
                if selected_expenses_v:
                    filtered_df = filtered_df[
                        filtered_df['Expense Head'].isin(selected_expenses_v)]
                if selected_parties_v:
                    filtered_df = filtered_df[
                        filtered_df['Party Name'].isin(selected_parties_v)]
                
                if selected_led_groups:
                    filtered_df = filtered_df[
                        filtered_df['Ledger Group'].isin(selected_led_groups)]
                if selected_led_parents:
                    filtered_df = filtered_df[
                        filtered_df['Ledger Parent'].isin(selected_led_parents)]
                
                with right:
                    def summary_card(col, label, value, color="#1f4e79"):
                        col.markdown(f"""
                        <div style="background:white; padding:10px 14px;
                                    border-radius:10px;
                                    box-shadow:0 2px 8px rgba(0,0,0,0.06);
                                    border-left:4px solid {color};
                                    margin-bottom:10px;">
                            <div style="font-size:11px; color:#555;
                                        font-weight:600;">{label}</div>
                            <div style="font-size:16px; font-weight:800;
                                        color:{color}; margin-top:4px;">
                                {value}
                            </div>
                        </div>
                        """, unsafe_allow_html=True)

                    def dynamic_height(df):
                        return min(max(len(df) * 30 + 36, 66), 600)

                    def highlight_rows(row):
                        try:
                            tds_books  = float(row.get('TDS Books', 0) or 0)
                            tds_winman = float(row.get('TDS Winman', 0) or 0)
                            difference = float(row.get('Difference', 0) or 0)
                            exp_tds    = row.get('Expected TDS', '')
                            pan_status = row.get('PAN Status', '')

                            # Yellow — PAN missing
                            if pan_status == 'Missing':
                                return ['background-color:#fff8e1'] * len(row)

                            # Red — TDS not deducted but expected
                            if tds_books == 0 and exp_tds not in ('', None, 'Below Threshold', 'Unmapped'):
                                try:
                                    if float(exp_tds) > 0:
                                        return ['background-color:#ffebee'] * len(row)
                                except Exception:
                                    pass

                            # Orange — TDS deducted but difference ≠ 0
                            if tds_books > 0 and difference != 0:
                                return ['background-color:#fff3e0'] * len(row)

                            # Green — all OK
                            if tds_books > 0 and difference == 0:
                                return ['background-color:#e8f5e9'] * len(row)

                            # Default — white
                            return [''] * len(row)
                        except Exception:
                            return [''] * len(row)

                    def fmt(styler):
                        def ind_no_dec(x):
                            try:
                                num = float(x)
                                is_neg = num < 0
                                num = abs(num)
                                integer = str(int(num))
                                if len(integer) <= 3:
                                    result = integer
                                else:
                                    last3 = integer[-3:]
                                    rest  = integer[:-3]
                                    groups = []
                                    while len(rest) > 2:
                                        groups.append(rest[-2:])
                                        rest = rest[:-2]
                                    if rest:
                                        groups.append(rest)
                                    groups.reverse()
                                    result = ",".join(groups) + "," + last3
                                return f"₹ {'-' if is_neg else ''}{result}"
                            except Exception:
                                return x
                        return styler.format({
                            'Expense Amount': ind_no_dec,
                            'TDS Books'     : ind_no_dec,
                            'TDS Winman'    : ind_no_dec,
                            'Difference'    : ind_no_dec,
                            'Expected TDS'  : ind_no_dec,
                        })

                                            
                    v_tab1, v_tab2, v_tab3 = st.tabs([
                        "📊 Expense & TDS",
                        "🛒 Purchase",
                        "💰 Sales"
                    ])

                    # ── Apply filters ─────────────────────────────────────────
                    filtered_df = df.copy() if not df.empty else df
                    if selected_parties_v and not filtered_df.empty:
                        filtered_df = filtered_df[
                            filtered_df['Party Name'].isin(selected_parties_v)]
                    if selected_expenses_v and not filtered_df.empty:
                        filtered_df = filtered_df[
                            filtered_df['Expense Head'].isin(selected_expenses_v)]
                    if selected_base_groups and not filtered_df.empty:
                        filtered_df = filtered_df[
                            filtered_df['Base Group'].isin(selected_base_groups)]
                    if selected_led_groups and not filtered_df.empty:
                        filtered_df = filtered_df[
                            filtered_df['Ledger Group'].isin(selected_led_groups)]
                    if selected_led_parents and not filtered_df.empty:
                        filtered_df = filtered_df[
                            filtered_df['Ledger Parent'].isin(selected_led_parents)]

                    # Purchase filter
                    filtered_pur = pur_df.copy() if not pur_df.empty else pur_df
                    if selected_parties_v and not filtered_pur.empty:
                        filtered_pur = filtered_pur[
                            filtered_pur['PartyLedgerName'].isin(selected_parties_v)]

                    # Sales filter
                    filtered_sal = sal_df.copy() if not sal_df.empty else sal_df
                    if selected_parties_v and not filtered_sal.empty:
                        filtered_sal = filtered_sal[
                            filtered_sal['PartyLedgerName'].isin(selected_parties_v)]

                    # ── Expense & TDS Tab ─────────────────────────────────────
                    with v_tab1:
                        if filtered_df.empty:
                            st.info("No Expense & TDS data available.")
                        else:
                            total_expense    = filtered_df['Expense Amount'].sum()
                            total_tds_books  = filtered_df['TDS Books'].sum()
                            total_tds_winman = filtered_df['TDS Winman'].sum()
                            total_diff       = filtered_df['Difference'].sum()

                            s1, s2, s3, s4 = st.columns(4)
                            summary_card(s1, "Total Expense",
                                        indian_format(total_expense), "#1f4e79")
                            summary_card(s2, "TDS as per Books",
                                        indian_format(total_tds_books), "#2e7d32")
                            summary_card(s3, "TDS as per Winman",
                                        indian_format(total_tds_winman), "#1565c0")
                            summary_card(s4, "Difference",
                                        indian_format(total_diff),
                                        "#c62828" if total_diff != 0 else "#2e7d32")

                            # Toggle
                            view_mode = st.radio(
                                "View By",
                                options=["📁 Expense Head", "👤 Party"],
                                horizontal=True,
                                key="v_view_mode"
                            )
                            
                            # ── Live TDS Rules ────────────────────────────────
                            tds_rules = {}
                            rules_path = str(paths.config_path(company_name, active_fy, "tds_rules.json"))
                            if os.path.exists(rules_path):
                                with open(rules_path) as f:
                                    tds_rules = json.load(f)

                            if tds_rules and not filtered_df.empty:
                                # thresholds loaded from system_sections.json

                                # Party-wise total for threshold check
                                party_totals = filtered_df.groupby(
                                    'Party Name')['Expense Amount'].sum().to_dict()

                                tds_sections, deduct_rates, exp_tds_vals = [], [], []

                                for _, row in filtered_df.iterrows():
                                    exp_head = row.get('Expense Head', '')
                                    party    = row.get('Party Name', '')
                                    pan      = str(row.get('PAN', '')).strip().upper()
                                    exp_amt  = abs(float(row.get('Expense Amount', 0) or 0))
                                    party_total = abs(float(party_totals.get(party, 0)))

                                    rule = tds_rules.get(exp_head)
                                    if not rule:
                                        tds_sections.append('Unmapped')
                                        deduct_rates.append('')
                                        exp_tds_vals.append('')
                                        continue

                                    section = rule.get('section') or ''
                                    typ     = rule.get('type', 'Unmapped')
                                    rate    = rule.get('rate')

                                    if typ == 'NON-TDS':
                                        tds_sections.append('NON-TDS')
                                        deduct_rates.append('0%')
                                        exp_tds_vals.append(0.0)
                                        continue

                                    if section == '192':
                                        tds_sections.append('192')
                                        deduct_rates.append('Slab')
                                        exp_tds_vals.append('')
                                        continue

                                    if section == '194C':
                                        rate = 0.01 if (len(pan) >= 4 and pan[3] == 'P') else 0.02

                                    threshold = tds_rules_engine.get_flat_threshold(section)
                                    if threshold and party_total <= threshold:
                                        tds_sections.append(section)
                                        deduct_rates.append(f"{rate*100:.1f}%" if rate else '')
                                        exp_tds_vals.append('Below Threshold')
                                        continue

                                    expected = round(exp_amt * rate, 2) if rate else 0.0
                                    tds_sections.append(section)
                                    deduct_rates.append(f"{rate*100:.1f}%" if rate else '')
                                    exp_tds_vals.append(str(expected) if expected else '')

                                filtered_df = filtered_df.copy()
                                filtered_df['TDS Section']    = tds_sections
                                filtered_df['Deduction Rate'] = deduct_rates
                                filtered_df['Expected TDS']   = exp_tds_vals

                            
                            extra_cols = ['TDS Section', 'Deduction Rate', 'Expected TDS'] \
                                if tds_rules else []
                            display_cols = [
                                'Party Name', 'PAN', 'Expense Amount',
                            ] + extra_cols + [
                                'TDS Books', 'TDS Winman', 'Difference',
                                'PAN Status'
                            ]

                            if view_mode == "📁 Expense Head":
                                for expense in sorted(
                                        filtered_df['Expense Head'].dropna().unique()):
                                    exp_rows = filtered_df[
                                        filtered_df['Expense Head'] == expense].copy()

                                    # PAN grouping
                                    df_pan_e    = exp_rows[
                                        exp_rows['PAN'].notna() &
                                        (exp_rows['PAN'].astype(str).str.strip() != '') &
                                        (exp_rows['PAN'].astype(str).str.strip() != 'Missing')
                                    ]
                                    df_no_pan_e = exp_rows[
                                        exp_rows['PAN'].isna() |
                                        (exp_rows['PAN'].astype(str).str.strip() == '') |
                                        (exp_rows['PAN'].astype(str).str.strip() == 'Missing')
                                    ]

                                    pan_grp_e = df_pan_e.groupby(
                                        ['PAN','PAN Status'], as_index=False
                                    ).agg(
                                        **{'Party Name'   : ('Party Name',
                                                             lambda x: ' | '.join(sorted(set(x.dropna())))),
                                           'Expense Amount': ('Expense Amount', 'sum'),
                                           'TDS Books'     : ('TDS Books',     'mean'),
                                           'TDS Winman'    : ('TDS Winman',    'mean'),
                                           'Difference'    : ('Difference',    'sum')}
                                    )
                                    no_pan_grp_e = df_no_pan_e.groupby(
                                        ['Party Name','PAN','PAN Status'], as_index=False
                                    ).agg(
                                        **{'Expense Amount': ('Expense Amount', 'sum'),
                                           'TDS Books'     : ('TDS Books',     'mean'),
                                           'TDS Winman'    : ('TDS Winman',    'mean'),
                                           'Difference'    : ('Difference',    'sum')}
                                    )
                                    group_df = pd.concat(
                                        [pan_grp_e, no_pan_grp_e],
                                        ignore_index=True
                                    )
                                    group_df = group_df[[
                                        c for c in display_cols if c in group_df.columns
                                    ]].copy()

                                    # Re-apply TDS rules to grouped df
                                    if tds_rules:
                                        exp_head = expense
                                        rule = tds_rules.get(exp_head, {})
                                        section = rule.get('section') or ''
                                        typ     = rule.get('type', 'Unmapped')
                                        rate    = rule.get('rate')

                                        g_sections, g_rates, g_exp_tds = [], [], []
                                        for _, row in group_df.iterrows():
                                            pan     = str(row.get('PAN', '')).strip().upper()
                                            exp_amt = abs(float(row.get('Expense Amount', 0) or 0))

                                            if not section or typ == 'Unmapped':
                                                g_sections.append('Unmapped')
                                                g_rates.append('')
                                                g_exp_tds.append('')
                                                continue
                                            if typ == 'NON-TDS':
                                                g_sections.append('NON-TDS')
                                                g_rates.append('0%')
                                                g_exp_tds.append(0.0)
                                                continue
                                            if section == '192':
                                                g_sections.append('192')
                                                g_rates.append('Slab')
                                                g_exp_tds.append('')
                                                continue
                                            if section == '194C':
                                                rate = 0.01 if (len(pan) >= 4 and pan[3] == 'P') else 0.02
                                            threshold = tds_rules_engine.get_flat_threshold(section)
                                            if threshold and exp_amt <= threshold:
                                                g_sections.append(section)
                                                g_rates.append(f"{rate*100:.1f}%" if rate else '')
                                                g_exp_tds.append('Below Threshold')
                                            else:
                                                if section == '194Q':
                                                    excess = max(exp_amt - 5000000, 0)
                                                    expected = round(excess * rate, 2) if rate else 0.0
                                                else:
                                                    expected = round(exp_amt * rate, 2) if rate else 0.0
                                                g_sections.append(section)
                                                g_rates.append(f"{rate*100:.1f}%" if rate else '')
                                                g_exp_tds.append(str(expected) if expected else '')

                                        group_df['TDS Section']    = g_sections
                                        group_df['Deduction Rate'] = g_rates
                                        group_df['Expected TDS']   = g_exp_tds
                                        for c in ['TDS Section','Deduction Rate','Expected TDS']:
                                            if c not in display_cols:
                                                display_cols.append(c)
                                        group_df = group_df[[
                                            c for c in display_cols if c in group_df.columns]]

                                    g_exp  = group_df['Expense Amount'].sum()
                                    g_tds  = group_df['TDS Books'].sum()
                                    g_win  = group_df['TDS Winman'].sum()
                                    g_diff = group_df['Difference'].sum()
                                    label = (
                                        f"📁 {expense} — "
                                        f"Exp: {indian_format(g_exp)} | "
                                        f"TDS: {indian_format(g_tds)} | "
                                        f"Diff: {indian_format(g_diff)}"
                                    )
                                    with st.expander(label):
                                        safe_styled_df(
                                            group_df,
                                            lambda s: fmt(s.apply(highlight_rows, axis=1)),
                                            width="stretch",
                                            hide_index=True,
                                            height=dynamic_height(group_df)
                                        )
                                        st.markdown(
                                            f"**Subtotal — "
                                            f"Exp: {indian_format(g_exp)} | "
                                            f"TDS: {indian_format(g_tds)} | "
                                            f"Winman: {indian_format(g_win)} | "
                                            f"Diff: {indian_format(g_diff)}**"
                                        )
                            else:
                                # PAN grouping — group non-blank PANs, keep blank as party
                                df_pan     = filtered_df[
                                    filtered_df['PAN'].notna() &
                                    (filtered_df['PAN'].astype(str).str.strip() != '') &
                                    (filtered_df['PAN'].astype(str).str.strip() != 'Missing')
                                ].copy()
                                df_no_pan  = filtered_df[
                                    filtered_df['PAN'].isna() |
                                    (filtered_df['PAN'].astype(str).str.strip() == '') |
                                    (filtered_df['PAN'].astype(str).str.strip() == 'Missing')
                                ].copy()

                                pan_grp = df_pan.groupby(
                                    ['PAN', 'PAN Status'], as_index=False
                                ).agg(
                                    **{'Party Name'   : ('Party Name',
                                                         lambda x: ' | '.join(sorted(set(x.dropna())))),
                                       'Expense Head' : ('Expense Head',
                                                         lambda x: ' | '.join(sorted(set(x.dropna())))),
                                       'Expense Amount': ('Expense Amount', 'sum'),
                                       'TDS Books'     : ('TDS Books',     'mean'),
                                       'TDS Winman'    : ('TDS Winman',    'mean'),
                                       'Difference'    : ('Difference',    'sum')}
                                )

                                no_pan_grp = df_no_pan.groupby(
                                    ['Party Name', 'PAN', 'PAN Status'], as_index=False
                                ).agg(
                                    **{'Expense Head' : ('Expense Head',
                                                         lambda x: ' | '.join(sorted(set(x.dropna())))),
                                       'Expense Amount': ('Expense Amount', 'sum'),
                                       'TDS Books'     : ('TDS Books',     'mean'),
                                       'TDS Winman'    : ('TDS Winman',    'mean'),
                                       'Difference'    : ('Difference',    'sum')}
                                )

                                party_df = pd.concat(
                                    [pan_grp, no_pan_grp], ignore_index=True)
                                # Apply TDS rules to party view
                                if tds_rules:
                                    pt_sections, pt_rates, pt_exp_tds = [], [], []
                                    for _, row in party_df.iterrows():
                                        pan      = str(row.get('PAN', '')).strip().upper()
                                        exp_amt  = abs(float(row.get('Expense Amount', 0) or 0))
                                        exp_heads = str(row.get('Expense Head', '')).split(' | ')

                                        section, rate, typ = None, None, 'Unmapped'
                                        for head in exp_heads:
                                            rule = tds_rules.get(head.strip())
                                            if rule and rule.get('section'):
                                                section = rule.get('section')
                                                rate    = rule.get('rate')
                                                typ     = rule.get('type', 'TDS')
                                                break

                                        if not section or typ == 'Unmapped':
                                            pt_sections.append('Unmapped')
                                            pt_rates.append('')
                                            pt_exp_tds.append('')
                                            continue

                                        if typ == 'NON-TDS':
                                            pt_sections.append('NON-TDS')
                                            pt_rates.append('0%')
                                            pt_exp_tds.append(0.0)
                                            continue

                                        if section == '192':
                                            pt_sections.append('192')
                                            pt_rates.append('Slab')
                                            pt_exp_tds.append('')
                                            continue

                                        if section == '194C':
                                            rate = 0.01 if (len(pan) >= 4 and pan[3] == 'P') else 0.02

                                        threshold = tds_rules_engine.get_flat_threshold(section)

                                        if threshold and exp_amt <= threshold:
                                            pt_sections.append(section)
                                            pt_rates.append(f"{rate*100:.1f}%" if rate else '')
                                            pt_exp_tds.append('Below Threshold')
                                        else:
                                            if section == '194Q':
                                                excess = max(exp_amt - 5000000, 0)
                                                expected = round(excess * rate, 2) if rate else 0.0
                                            else:
                                                expected = round(exp_amt * rate, 2) if rate else 0.0
                                            pt_sections.append(section)
                                            pt_rates.append(f"{rate*100:.1f}%" if rate else '')
                                            pt_exp_tds.append(str(expected) if expected else '')

                                    party_df['TDS Section']    = pt_sections
                                    party_df['Deduction Rate'] = pt_rates
                                    party_df['Expected TDS']   = pt_exp_tds
                                tds_extra = ['TDS Section','Deduction Rate','Expected TDS']
                                base_cols = ['Party Name','Expense Heads','PAN','Expense Amount']
                                rest_cols = ['TDS Books','TDS Winman','Difference','PAN Status']
                                final_order = base_cols + tds_extra + rest_cols
                                party_df = party_df[[c for c in final_order if c in party_df.columns]]
                                party_df = party_df.sort_values(
                                    'Expense Amount', ascending=False
                                ).reset_index(drop=True)
                                safe_styled_df(
                                    party_df,
                                    lambda s: fmt(s.apply(highlight_rows, axis=1)),
                                    width="stretch",
                                    hide_index=True,
                                    height=dynamic_height(party_df)
                                )
                                st.markdown(
                                    f"**Total — "
                                    f"Exp: {indian_format(total_expense)} | "
                                    f"TDS: {indian_format(total_tds_books)} | "
                                    f"Winman: {indian_format(total_tds_winman)} | "
                                    f"Diff: {indian_format(total_diff)}**"
                                )
                                
                                
                            # Download
                            if not filtered_df.empty:
                                out = io.BytesIO()
                                with pd.ExcelWriter(out, engine='openpyxl') as writer:
                                    download_cols = [c for c in [
                                        'Expense Head', 'Base Group', 'Ledger Group',
                                        'Ledger Parent', 'Party Name', 'PAN',
                                        'Expense Amount', 'TDS Books', 'TDS Winman',
                                        'Difference', 'PAN Status'
                                    ] if c in filtered_df.columns]
                                    filtered_df[download_cols].to_excel(
                                        writer, index=False, sheet_name='Expense_TDS')
                                out.seek(0)
                                st.download_button(
                                    "📥 Download",
                                    data=out,
                                    file_name=f"Expense_TDS_{company_name}.xlsx",
                                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                                    key="btn_dl_expense"
                                )

# ── Purchase Tab ──────────────────────────────────────────
                    with v_tab2:
                        if filtered_pur.empty:
                            st.info("No Purchase data available.")
                        else:
                            pur_view = st.radio(
                                "View By",
                                options=["👤 Party View", "🔎 PAN View"],
                                horizontal=True,
                                key="pur_view_mode"
                            )
                            if pur_view == "🔎 PAN View":
                                try:
                                    pur_grouped = viewer_engine.load_purchase_grouped(
                                        company_name, active_fy,
                                        st.session_state.get("viewer_loaded_file", "")
                                    )
                                    blank_pan = pur_grouped['$Led_PAN'].astype(str).str.strip().isin(['', 'nan', 'None', 'null', 'Missing', 'NaN'])
                                    pan_df = pur_grouped[blank_pan].copy()
                                    grp_df = pur_grouped[~blank_pan].groupby('$Led_PAN', as_index=False).agg(
                                        PartyNames=('PartyLedgerName', lambda x: ' | '.join(sorted(set(x.dropna())))),
                                        PurchaseAmount=('PurchaseAmount', 'sum'),
                                        TDSAmount=('TDSAmount', 'sum'),
                                        TDS_Deposited=('TDS_Deposited', 'sum'),
                                        TDS_Ledger=('TDS_Ledger', lambda x: ' | '.join(sorted(set(
                                            v for v in x if v not in ['', 'nan']
                                        ))))
                                    )
                                    pan_df = pan_df.rename(columns={'PartyLedgerName': 'PartyNames'})
                                    display_pur = pd.concat([grp_df, pan_df], ignore_index=True)

                                    # 194Q columns
                                    display_pur['194Q_Applicable'] = display_pur['PurchaseAmount'].apply(
                                        lambda x: 'Yes' if x > 5000000 else 'No')
                                    display_pur['Taxable_Amount'] = display_pur['PurchaseAmount'].apply(
                                        lambda x: round(x - 5000000, 2) if x > 5000000 else 0)
                                    display_pur['Expected_TDS'] = display_pur['Taxable_Amount'].apply(
                                        lambda x: round(x * 0.001, 2))
                                    # TDS booked is a credit (negative in Tally) — flip to positive so the
                                    # Variance (TDS_Books − Expected_TDS) reads correctly.
                                    display_pur['TDSAmount'] = display_pur['TDSAmount'] * -1
                                    display_pur['Variance'] = display_pur.apply(
                                        lambda r: round(r['TDSAmount'] - r['Expected_TDS'], 2), axis=1)
                                    # Rename TDSAmount → TDS_Books and Variance → its full label; show
                                    # Expected_TDS right after PurchaseAmount.
                                    display_pur = display_pur.rename(columns={
                                        'TDSAmount': 'TDS_Books',
                                        'Variance': 'Variance-Expec vs Books'})
                                    _pan_order = ['$Led_PAN', 'PartyNames', 'PurchaseAmount', 'Expected_TDS',
                                                  'TDS_Books', 'TDS_Deposited', 'TDS_Ledger',
                                                  '194Q_Applicable', 'Taxable_Amount',
                                                  'Variance-Expec vs Books']
                                    display_pur = display_pur[
                                        [c for c in _pan_order if c in display_pur.columns]
                                        + [c for c in display_pur.columns if c not in _pan_order]]
                                except Exception as e:
                                    st.error(f"Error: {e}")
                                    display_pur = filtered_pur
                            else:
                                display_pur = filtered_pur
                            def highlight_ambiguous(row):
                                party_col = 'PartyLedgerName' if 'PartyLedgerName' in row.index else '$Party_LedName'
                                if '|' in str(row.get(party_col, '')):
                                    return ['background-color:#ffebee'] * len(row)
                                return [''] * len(row)

                            # Expected_TDS / TDS_Books / TDS_Deposited should agree. Colour the three
                            # cells green when all (almost) equal, orange when any one differs — so a
                            # short deduction or non-deposit stands out at a glance.
                            _tri = ['Expected_TDS', 'TDS_Books', 'TDS_Deposited']

                            def color_three_tds(row):
                                styles = pd.Series('', index=row.index)
                                if not all(c in row.index for c in _tri):
                                    return styles
                                vals = [pd.to_numeric(row[c], errors='coerce') for c in _tri]
                                if any(pd.isna(v) for v in vals):
                                    return styles
                                tol = max(2.0, 0.01 * max(abs(v) for v in vals))   # ₹2 or 1%
                                all_eq = all(abs(a - b) <= tol
                                             for a, b in ((vals[0], vals[1]),
                                                          (vals[1], vals[2]),
                                                          (vals[0], vals[2])))
                                color = '#e7f6ec' if all_eq else '#fff3e0'   # green / orange
                                for c in _tri:
                                    styles[c] = f'background-color:{color}'
                                return styles

                            def fmt_pur(styler):
                                num_cols = display_pur.select_dtypes(include='number').columns
                                return styler.format({c: lambda x: indian_format(x) for c in num_cols})

                            total_pur = display_pur['PurchaseAmount'].sum() if 'PurchaseAmount' in display_pur.columns else 0
                            _tds_col = next((c for c in ('TDS_Books', 'TDSAmount')
                                             if c in display_pur.columns), None)
                            total_tds_pur = display_pur[_tds_col].sum() if _tds_col else 0
                            s1, s2 = st.columns(2)
                            summary_card(s1, "Total Purchase", indian_format(total_pur), "#1f4e79")
                            summary_card(s2, "TDS on Purchase", indian_format(total_tds_pur), "#2e7d32")
                            def _sty_pur(s):
                                s = s.apply(highlight_ambiguous, axis=1)
                                if all(c in display_pur.columns for c in _tri):
                                    s = s.apply(color_three_tds, axis=1)
                                return fmt_pur(s)
                            safe_styled_df(
                                display_pur, _sty_pur,
                                width="stretch",
                                hide_index=True,
                                height=dynamic_height(display_pur)
                            )

                            if not filtered_pur.empty:
                                out_p = io.BytesIO()
                                with pd.ExcelWriter(out_p, engine='openpyxl') as writer:
                                    filtered_pur.to_excel(
                                        writer, index=False, sheet_name='Purchase')
                                out_p.seek(0)
                                st.download_button(
                                    "📥 Download",
                                    data=out_p,
                                    file_name=f"Purchase_{company_name}.xlsx",
                                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                                    key="btn_dl_purchase"
                                )

                    # ── Sales Tab ─────────────────────────────────────────────
                    with v_tab3:
                        if filtered_sal.empty:
                            st.info("No Sales data available.")
                        else:
                            s1, s2 = st.columns(2)
                            amt_cols = [c for c in filtered_sal.columns
                                       if c not in ['PartyLedgerName', '$Led_PAN']]
                            total_sales = filtered_sal[amt_cols].sum().sum() \
                                if amt_cols else 0
                            summary_card(s1, "Total Sales",
                                        indian_format(total_sales), "#1f4e79")

                            def fmt_sal(styler):
                                num_cols = filtered_sal.select_dtypes(include='number').columns
                                return styler.format({c: lambda x: indian_format(x) for c in num_cols})

                            safe_styled_df(
                                filtered_sal, fmt_sal,
                                width="stretch",
                                hide_index=True,
                                height=dynamic_height(filtered_sal)
                            )

                            if not filtered_sal.empty:
                                out_s = io.BytesIO()
                                with pd.ExcelWriter(out_s, engine='openpyxl') as writer:
                                    filtered_sal.to_excel(
                                        writer, index=False, sheet_name='Sales')
                                out_s.seek(0)
                                st.download_button(
                                    "📥 Download",
                                    data=out_s,
                                    file_name=f"Sales_{company_name}.xlsx",
                                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                                    key="btn_dl_sales"
                                )
                                


                
# ── Page: Related Parties ─────────────────────────────────────────────────────
if _page == "related":
    st.markdown("""
    <div class="card">
        <div class="card-title">🔗 Related Party Transactions & Balances</div>
        <div class="card-desc">
            Select related party ledgers to view consolidated transactions and balances.
        </div>
    </div>
    """, unsafe_allow_html=True)

    if not company_name:
        st.markdown('<div class="status-error">⚠️ Please select a company first.</div>',
                    unsafe_allow_html=True)
    else:
        # ── Load master ledgers ───────────────────────────────────────────────
        cache_key_ml = f"master_ledgers_{company_name}"
        if cache_key_ml not in st.session_state:
            st.session_state[cache_key_ml] = viewer_engine.get_master_ledgers(company_name, active_fy)
        master_ledgers = st.session_state[cache_key_ml]

        saved_rp   = company_info.get_related_parties(company_name, active_fy)
        default_rp = [x for x in saved_rp if x in master_ledgers]

        if not master_ledgers:
            st.markdown('<div class="status-running">ℹ️ Run consolidation first to load ledgers.</div>',
                        unsafe_allow_html=True)
        else:
            rp_left, rp_right = st.columns([1, 3])

            with rp_left:
                st.markdown("#### 🏷️ Select Related Parties")
                selected_rp = st.multiselect(
                    "Ledger Names",
                    options=master_ledgers,
                    default=default_rp,
                    key="selected_rp"
                )
                if st.button("💾 Save Selection", key="btn_save_rp",
                             width="stretch"):
                    company_info.save_related_parties(company_name, active_fy, selected_rp)
                    st.session_state[f"rp_saved_msg"] = True
                if st.session_state.get("rp_saved_msg"):
                    st.success("✅ Saved!")

                st.markdown("<hr style='margin:8px 0;'>", unsafe_allow_html=True)

                # Analysis file selector
                rp_files = viewer_engine.get_analysis_files(company_name, active_fy)
                if rp_files:
                    selected_rp_file = st.selectbox(
                        "Analysis File",
                        options=rp_files,
                        key="rp_file"
                    )
                else:
                    st.markdown('<div class="status-error">⚠️ No analysis files found.</div>',
                                unsafe_allow_html=True)
                    selected_rp_file = None

                if st.button("▶ Run Report", key="btn_run_rp",
                             width="stretch"):
                    if not selected_rp:
                        st.error("⚠️ Select at least one party.")
                    elif not selected_rp_file:
                        st.error("⚠️ No analysis file found.")
                    else:
                        with busy_overlay("Building report…"):
                            try:
                                cache_key = f"rp_{company_name}_{selected_rp_file}_{sorted(selected_rp)}"
                                if cache_key not in st.session_state:
                                    st.session_state[cache_key] = viewer_engine.load_related_party_report(
                                        company_name, active_fy, selected_rp_file, tuple(sorted(selected_rp)))
                                rp_df = st.session_state[cache_key]
                                st.session_state["rp_report"] = rp_df
                            except Exception as e:
                                st.error(f"❌ Error: {e}")

            with rp_right:
                st.markdown("#### 📊 Report")
                st.markdown("""
                <div style="background:#fff8e1; border-left:4px solid #ffa000;
                            padding:6px 12px; border-radius:6px;
                            font-size:12px; color:#e65100; margin-bottom:8px;">
                    💡 <b>Balance convention:</b> Debit = Negative, Credit = Positive
                </div>
                """, unsafe_allow_html=True)

                if "rp_report" in st.session_state:
                    rp_df = st.session_state["rp_report"]

                    if rp_df.empty:
                        st.info("No data found for selected parties.")
                    else:
                        # Summary cards
                        s1, s2, s3, s4 = st.columns(4)
                        summary_card(s1, "Total Opening",
                            indian_format(rp_df['$OpeningBalance'].sum()), "#1f4e79")
                        summary_card(s2, "Total Closing",
                            indian_format(rp_df['$ClosingBalance'].sum()), "#1f4e79")
                        summary_card(s3, "Total Sales",
                            indian_format(rp_df['Total_Sales'].sum()), "#2e7d32")
                        summary_card(s4, "Total Purchases",
                            indian_format(rp_df['Total_Purchases'].sum()), "#c62828")

                        # Format numbers
                        def fmt_rp(styler):
                            num_cols = rp_df.select_dtypes(include='number').columns
                            return styler.format(
                                {c: lambda x: indian_format(x) for c in num_cols})

                        safe_styled_df(
                            rp_df, fmt_rp,
                            width="stretch",
                            hide_index=True,
                            height=min(len(rp_df) * 30 + 36, 500)
                        )

                        # Download
                        out_rp = io.BytesIO()
                        with pd.ExcelWriter(out_rp, engine='openpyxl') as writer:
                            rp_df.to_excel(writer, sheet_name='Related_Parties', index=False)
                        out_rp.seek(0)
                        st.download_button(
                            "📥 Download Report",
                            data=out_rp,
                            file_name=f"Related_Party_{company_name}.xlsx",
                            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                            key="btn_dl_rp"
                        )

# ── Tab: 43B(h) MSME Disallowance ─────────────────────────────────────────────
@st.cache_data(show_spinner=False)
def _contra_ledgers(entity, fy):
    return contra_engine.load_ledgers(entity, fy)


@st.cache_data(show_spinner=False)
def _contra_source_cands(source, others, fy):
    return contra_engine.source_candidates(source, list(others), fy)


@st.cache_data(show_spinner=False)
def _contra_all_src(entity, fy):
    return contra_engine.all_source_ledgers(entity, fy)


@st.cache_data(show_spinner=False)
def _contra_concern_opts(target, source, fy, show_all):
    return contra_engine.concern_ledger_options(target, source, fy, show_all)


if _page == "contra":
    st.markdown("""
    <div class="card">
        <div class="card-title">🔁 Contra Balances — group inter-se reconciliation</div>
        <div class="card-desc">
            Pick all concerns in a group (companies, directors, firms). Auto-detect
            finds reciprocal party ledgers (each concern's ledger for another),
            you map/fix them in the table, then reconcile — reciprocal balances
            should be equal &amp; opposite. Extract each concern first, like any company.
        </div>
    </div>
    """, unsafe_allow_html=True)

    if not active_fy:
        st.markdown('<div class="status-error">⚠️ Select a tax year in the top bar first.</div>',
                    unsafe_allow_html=True)
    else:
        _entities = contra_engine.list_master_entities(active_fy)
        if len(_entities) < 2:
            st.markdown(
                f'<div class="status-running">ℹ️ Need at least two extracted books for '
                f'FY <b>{active_fy}</b>. Extract the concerns first.</div>',
                unsafe_allow_html=True)
        else:
            _groups = contra_engine.list_groups()
            # A just-saved group selects itself — but the widget key can't be set
            # after the selectbox exists, so apply the pending choice here first.
            if "contra_pending_group" in st.session_state:
                _pg = st.session_state.pop("contra_pending_group")
                if _pg in _groups:
                    st.session_state["contra_group_sel"] = _pg
            # Smaller, full-name, wrapping chips so all concerns fit in the box.
            # This <style> only loads while the contra page renders, so it safely
            # affects just this page's multiselect.
            # BaseWeb sets heights via INLINE styles, so !important is required
            # to override them. Grow the box to ~3 rows of chips (≈15 names) and
            # stop it clipping/scrolling.
            st.markdown("""
            <style>
            [data-testid="stMultiSelect"] [data-baseweb="tag"]{
                font-size:11px !important; height:auto !important;
                max-width:none !important; white-space:normal !important;}
            [data-testid="stMultiSelect"] [data-baseweb="tag"] span{
                white-space:normal !important; overflow:visible !important;
                text-overflow:clip !important; max-width:none !important;}
            [data-testid="stMultiSelect"] [data-baseweb="select"]{
                min-height:150px !important;}
            [data-testid="stMultiSelect"] [data-baseweb="select"] > div{
                min-height:150px !important; max-height:none !important; height:auto !important;
                align-items:flex-start !important; overflow:visible !important;
                padding-bottom:8px !important;}
            [data-testid="stMultiSelect"] [data-baseweb="select"] > div > div{
                max-height:none !important; height:auto !important;
                overflow:visible !important; flex-wrap:wrap !important;}
            </style>
            """, unsafe_allow_html=True)
            gc1, gc2, gc3 = st.columns([2, 2, 6])
            with gc1:
                _grp_choice = st.selectbox("Group", ["➕ New group…"] + _groups,
                                           key="contra_group_sel")
            _loaded = contra_engine.load_group(_grp_choice) if _grp_choice != "➕ New group…" else None
            _def_ent = [e for e in (_loaded["entities"] if _loaded else []) if e in _entities]

            # When the chosen group changes, load ITS concerns / name / pairs into
            # the widgets. A keyed widget ignores `default` after first use, so the
            # selection must be seeded through session_state to actually reflect.
            if st.session_state.get("contra_last_group") != _grp_choice:
                st.session_state["contra_last_group"] = _grp_choice
                st.session_state["contra_entities"] = _def_ent
                st.session_state["contra_group_name"] = _loaded["name"] if _loaded else ""
                st.session_state["contra_rows"] = list(_loaded.get("pairs", [])) if _loaded else []
                # Restore per-concern deletions (🗑) and manual adds from the group.
                _ld = _loaded or {}
                for _e in _entities:
                    st.session_state[f"contra_dismiss_{_e}"] = set(_ld.get("dismissed", {}).get(_e, []))
                    st.session_state[f"contra_extra_{_e}"] = list(_ld.get("extra", {}).get(_e, []))
                # stale per-row widget picks from a previous group must not linger
                for _k in [k for k in st.session_state
                           if k.startswith(("cc_", "cl_"))]:
                    del st.session_state[_k]

            with gc2:
                _grp_name = st.text_input("Group name", placeholder="e.g. XYZ Group",
                                          key="contra_group_name")
            with gc3:
                sel_ent = st.multiselect(
                    "🏢 Concerns in this group  (companies, directors, firms…)",
                    options=_entities, key="contra_entities")

            _rows = st.session_state.setdefault("contra_rows", [])

            def _canon(p):
                return frozenset({(p["A"], p["A_Ledger"]), (p["B"], p["B_Ledger"])})

            def _find_map(src, ledger):
                """Existing (concern, ledger) mapped to src's `ledger`, else ('','')."""
                for p in _rows:
                    if p["A"] == src and p["A_Ledger"] == ledger:
                        return p["B"], p["B_Ledger"]
                    if p["B"] == src and p["B_Ledger"] == ledger:
                        return p["A"], p["A_Ledger"]
                return "", ""

            if len(sel_ent) < 2:
                st.markdown('<div class="status-running">ℹ️ Pick at least two concerns above '
                            'to start mapping.</div>', unsafe_allow_html=True)
                st.stop()

            NONE = "— none —"
            st.markdown("<hr style='margin:6px 0'>", unsafe_allow_html=True)
            _scol, _ = st.columns([3, 3])
            _src = _scol.selectbox("① Concern to map (source book)", sel_ent, key="contra_src")
            _others = [e for e in sel_ent if e != _src]

            _show_all = st.checkbox(
                "🔎 Show all ledgers when mapping (ignore name filter)",
                key="contra_showall",
                help="Off: counterpart dropdowns list only ledgers whose name resembles the "
                     "source concern. On: list every ledger — use when the match sits under an "
                     "unrelated name.")

            with busy_overlay("Finding ledgers that name another concern…"):
                _cands = _contra_source_cands(_src, tuple(_others), active_fy)
            _src_led = _contra_ledgers(_src, active_fy)

            # Source rows = name-matched ledgers (ANY group) + existing mapped src
            # ledgers + manually added extras, minus any the user removed (🗑).
            _extra = st.session_state.setdefault(f"contra_extra_{_src}", [])
            _dismiss = st.session_state.setdefault(f"contra_dismiss_{_src}", set())
            _by_led = {r["ledger"]: dict(r) for r in _cands}
            for p in _rows:
                for _e, _l in ((p["A"], p["A_Ledger"]), (p["B"], p["B_Ledger"])):
                    if _e == _src and _l and _l not in _by_led:
                        _v = _src_led.get(_l, {})
                        _by_led[_l] = {"ledger": _l, "balance": _v.get("balance", 0.0),
                                       "group": _v.get("group", ""), "sugg_concern": "", "sugg_ledger": ""}
            for _l in _extra:
                if _l not in _by_led:
                    _v = _src_led.get(_l, {})
                    _by_led[_l] = {"ledger": _l, "balance": _v.get("balance", 0.0),
                                   "group": _v.get("group", ""), "sugg_concern": "", "sugg_ledger": ""}
            for _d in _dismiss:
                _by_led.pop(_d, None)
            _show = sorted(_by_led.values(),
                           key=lambda r: (r.get("sugg_concern", "").lower(), r["ledger"].lower()))

            # Add ANY source ledger (across all groups) that wasn't auto-listed.
            with st.expander("➕ Add a specific source ledger"):
                _pool = [nm for nm, _b, _g in _contra_all_src(_src, active_fy)
                         if nm not in _by_led and nm not in _dismiss]
                _addsel = st.selectbox("Ledger", ["—"] + _pool, key="contra_addsrc")
                if st.button("Add", key="contra_addsrc_btn") and _addsel != "—":
                    _extra.append(_addsel)
                    _dismiss.discard(_addsel)          # re-adding un-removes it
                    st.session_state[f"contra_extra_{_src}"] = _extra
                    st.session_state[f"contra_dismiss_{_src}"] = _dismiss
                    st.rerun()

            if not _show:
                st.markdown('<div class="status-running">ℹ️ No ledger in this concern names '
                            'another group concern. Use “Add a specific source ledger”.</div>',
                            unsafe_allow_html=True)
            else:
                st.markdown("""
                <style>
                [data-testid="stVerticalBlockBorderWrapper"] > div > [data-testid="stVerticalBlock"]{gap:.2rem;}
                /* smaller dropdown text so more of the ledger name is visible */
                [data-testid="stSelectbox"] [data-baseweb="select"] > div{
                    font-size:11px !important; min-height:32px !important;}
                /* vertical grid lines between the columns of each bordered row */
                [data-testid="stVerticalBlockBorderWrapper"] [data-testid="column"]{
                    border-right:1px solid #eef1f5;}
                [data-testid="stVerticalBlockBorderWrapper"] [data-testid="column"]:last-child{
                    border-right:none;}
                </style>
                """, unsafe_allow_html=True)

                NONE = "— none —"
                _CW = [4, 2, 4, 5, 3, 1]
                _DOT = {"MATCHED": ("#16a34a", "Matched"), "DIFFERENCE": ("#dc2626", "Difference"),
                        "SAME_SIGN": ("#ea580c", "Same sign"), "ONE_SIDE_ONLY": ("#f59e0b", "One side")}

                def _wrap(txt, size=13, color="inherit"):
                    return (f"<div style='font-size:{size}px;color:{color};white-space:normal;"
                            f"word-break:break-word;line-height:1.25'>{txt}</div>")

                with st.container(border=True):
                    _h = st.columns(_CW)
                    for _c, _t in zip(_h, ["Source ledger", "Amount", "Concern",
                                           "Its ledger · balance", "Status", ""]):
                        _c.markdown(
                            f"<div style='font-size:12px;font-weight:700;text-align:center'>{_t}</div>",
                            unsafe_allow_html=True)

                _screen_pairs, _seen_tgt, _rm = [], {}, None
                for _r in _show:
                    _L = _r["ledger"]
                    _dC, _dL = _find_map(_src, _L)
                    if not _dC:
                        _dC, _dL = _r.get("sugg_concern", ""), _r.get("sugg_ledger", "")

                    with st.container(border=True):
                        row = st.columns(_CW)
                        row[0].markdown(_wrap(_L) + _wrap(_r.get("group", ""), 11, "#94a3b8"),
                                        unsafe_allow_html=True)
                        row[1].markdown(_wrap(contra_engine.fmt_bal(_r["balance"])), unsafe_allow_html=True)

                        # Concern dropdown + wrapped full name below it.
                        _copts = [NONE] + _others
                        _C = row[2].selectbox("c", _copts, label_visibility="collapsed",
                                              index=_copts.index(_dC) if _dC in _copts else 0,
                                              key=f"cc_{_src}_{_L}")
                        if _C != NONE:
                            row[2].markdown(_wrap(_C, 11, "#475569"), unsafe_allow_html=True)

                        _cbtxt, _sttxt = "", ""
                        if _C != NONE:
                            _cleds = _contra_concern_opts(_C, _src, active_fy, _show_all)
                            if _dL and _dL not in {t[0] for t in _cleds}:
                                _dv = _contra_ledgers(_C, active_fy).get(_dL)
                                if _dv:
                                    _cleds = sorted(_cleds + [(_dL, _dv["balance"], _dv["group"])],
                                                    key=lambda t: t[0].lower())
                            _l2n = {f"{nm}  ·  {contra_engine.fmt_bal(b)}": nm for nm, b, g in _cleds}
                            _lopts = [NONE] + list(_l2n)
                            # Default to the suggested ledger, but if it's already
                            # mapped to a row above, auto-advance to the nearest-
                            # amount ledger in this concern that is still free.
                            _names = {t[0] for t in _cleds}
                            _def_led = _dL if (_dL in _names and (_C, _dL) not in _seen_tgt) else ""
                            if not _def_led:
                                _rank = sorted(_cleds, key=lambda t: abs(_r["balance"] + t[1]))
                                _def_led = next((nm for nm, b, g in _rank
                                                 if (_C, nm) not in _seen_tgt), "")
                            _dlab = next((lb for lb, nm in _l2n.items() if nm == _def_led), NONE)
                            _sel = row[3].selectbox("l", _lopts, label_visibility="collapsed",
                                                    index=_lopts.index(_dlab) if _dlab in _lopts else 0,
                                                    key=f"cl_{_src}_{_L}_{_C}_{int(_show_all)}")
                            _LB = _l2n.get(_sel, "")
                            if _LB and (_C, _LB) in _seen_tgt:
                                row[3].markdown(_wrap(f"⚠ already mapped to “{_seen_tgt[(_C, _LB)]}”",
                                                      11, "#dc2626"), unsafe_allow_html=True)
                            elif _LB:
                                _seen_tgt[(_C, _LB)] = _L
                                _bal = _contra_ledgers(_C, active_fy).get(_LB, {}).get("balance", 0.0)
                                _st, _df2 = contra_engine.pair_status(_r["balance"], _bal, True)
                                _cbtxt = contra_engine.fmt_bal(_bal)
                                _clr, _txt = _DOT.get(_st, ("#9ca3af", _st))
                                _sttxt = (f"● {_txt}"
                                          f"{(' Δ '+contra_engine.fmt_bal(_df2)) if _st=='DIFFERENCE' else ''}")
                                _sttxt = f"<span style='color:{_clr}'>{_sttxt}</span>"
                                row[3].markdown(_wrap(f"{_LB}  ·  {_cbtxt}", 11, "#475569"),
                                                unsafe_allow_html=True)
                                _screen_pairs.append({"A": _src, "A_Ledger": _L, "B": _C, "B_Ledger": _LB})
                        else:
                            row[3].markdown(_wrap("—", 12, "#94a3b8"), unsafe_allow_html=True)

                        row[4].markdown(_wrap(_sttxt), unsafe_allow_html=True)
                        if row[5].button("🗑", key=f"del_{_src}_{_L}", help="Remove this source ledger"):
                            _rm = _L

                if _rm is not None:
                    _dismiss.add(_rm)
                    if _rm in _extra:
                        _extra.remove(_rm)
                        st.session_state[f"contra_extra_{_src}"] = _extra
                    st.session_state[f"contra_dismiss_{_src}"] = _dismiss
                    st.session_state["contra_rows"] = [p for p in _rows if not (
                        (p["A"] == _src and p["A_Ledger"] == _rm) or
                        (p["B"] == _src and p["B_Ledger"] == _rm))]
                    st.rerun()

                _shown = {r["ledger"] for r in _show}
                _preserved = [p for p in _rows if not (
                    (p["A"] == _src and p["A_Ledger"] in _shown) or
                    (p["B"] == _src and p["B_Ledger"] in _shown))]
                _seen, _final = set(), []
                for p in _preserved + _screen_pairs:
                    k = _canon(p)
                    if k not in _seen:
                        _seen.add(k)
                        _final.append(p)
                st.session_state["contra_rows"] = _final
                _rows = _final

            st.markdown("<hr style='margin:8px 0'>", unsafe_allow_html=True)

            def _collect(pfx):
                return {e: sorted(st.session_state.get(f"{pfx}{e}", []))
                        for e in sel_ent if st.session_state.get(f"{pfx}{e}")}

            sc1, sc2, sc3 = st.columns([2, 2, 2])
            if sc1.button("💾 Save group", width="stretch", key="contra_save"):
                if not (_grp_name or "").strip():
                    st.session_state["contra_flash"] = ("error", "Enter a group name to save.")
                else:
                    contra_engine.save_group(
                        _grp_name, sel_ent, _rows, active_fy,
                        dismissed=_collect("contra_dismiss_"), extra=_collect("contra_extra_"))
                    # Select the just-saved group so it reloads (concerns + pairs).
                    # Applied at the top of next run, before the selectbox exists.
                    st.session_state["contra_pending_group"] = contra_engine.group_key(_grp_name)
                    st.session_state["contra_flash"] = ("success", f"Saved group ‘{_grp_name.strip()}’.")
                st.rerun()
            if sc3.button("↩️ Reset to defaults", width="stretch", key="contra_reset"):
                st.session_state["contra_reset_confirm"] = True

            if st.session_state.get("contra_reset_confirm"):
                st.markdown(
                    '<div class="status-error">⚠️ This clears ALL your mappings, deletions and '
                    'added ledgers for this group and returns to the auto-detected suggestions. '
                    'This cannot be undone (unless you re-map). Continue?</div>',
                    unsafe_allow_html=True)
                rcx, rcy, _ = st.columns([2, 2, 4])
                if rcx.button("✅ Yes, reset", width="stretch", key="contra_reset_yes"):
                    for _k in [k for k in st.session_state if k.startswith(
                            ("cc_", "cl_", "del_", "contra_dismiss_", "contra_extra_"))]:
                        del st.session_state[_k]
                    st.session_state["contra_rows"] = []
                    st.session_state.pop("contra_reset_confirm", None)
                    st.rerun()
                if rcy.button("Cancel", width="stretch", key="contra_reset_no"):
                    st.session_state.pop("contra_reset_confirm", None)
                    st.rerun()

            if st.session_state.get("contra_flash"):
                _lvl, _msg = st.session_state.pop("contra_flash")
                st.markdown(f'<div class="status-{"success" if _lvl=="success" else "error"}">{_msg}</div>',
                            unsafe_allow_html=True)

            # ── Full group reconciliation (all confirmed pairs) ──────────────
            _rec_df, _summ = contra_engine.reconcile(_rows, active_fy)
            m1, m2, m3, m4 = st.columns(4)
            m1.metric("Pairs", _summ["total"])
            m2.metric("🟢 Matched", _summ["matched"])
            m3.metric("🔴 Difference", _summ["difference"])
            m4.metric("🟡/🟠 Review", _summ["one_side"] + _summ["same_sign"])
            if not _rec_df.empty:
                _RF = {"MATCHED": "#e8f5e9", "DIFFERENCE": "#ffebee",
                       "SAME_SIGN": "#fff3e0", "ONE_SIDE_ONLY": "#fff8e1",
                       "DIAG": "#f3f4f6", "": "#ffffff"}
                # ── Matrix view: concerns × concerns, each book's own balance ──
                # Column headers use a short code; the same code prefixes each row
                # label, so the abbreviations are self-explaining.
                _mat = contra_engine.matrix(_rows, sel_ent, active_fy)
                _NO = {"private", "limited", "limted", "ltd", "pvt", "group",
                       "and", "the", "co", "company", "llp"}
                _ab, _used = {}, {}
                for _e in sel_ent:
                    _tk = [t for t in re.sub(r"[^A-Za-z0-9]+", " ", _e).split()
                           if t.lower() not in _NO]
                    _cd = ("".join(t[0] for t in _tk).upper()[:5]) or _e[:4].upper()
                    _n = _used.get(_cd, 0); _used[_cd] = _n + 1
                    _ab[_e] = _cd if not _n else f"{_cd}{_n + 1}"
                _rowlab = [f"{_ab[e]} · {e}" for e in sel_ent]
                _collab = [_ab[e] for e in sel_ent]
                _val = pd.DataFrame("", index=_rowlab, columns=_collab)
                _sts = pd.DataFrame("", index=_rowlab, columns=_collab)
                for _i, _rw in enumerate(sel_ent):
                    for _j, _cl in enumerate(sel_ent):
                        if _rw == _cl:
                            _val.iloc[_i, _j] = "—"; _sts.iloc[_i, _j] = "DIAG"; continue
                        _cell = _mat.get(_rw, {}).get(_cl)
                        if _cell:
                            _val.iloc[_i, _j] = contra_engine.fmt_bal(_cell["bal"])
                            _sts.iloc[_i, _j] = _cell["status"]

                def _mstyle(_):
                    return pd.DataFrame(
                        [[f"background-color:{_RF.get(_sts.iloc[i, j], '#fff')};"
                          "text-align:right;font-size:12px" for j in range(len(_collab))]
                         for i in range(len(_rowlab))], index=_rowlab, columns=_collab)

                st.markdown("#### Group reconciliation — matrix "
                            "<span style='font-size:12px;color:#64748b'>(row = concern's own "
                            "books · columns use the code shown on each row · 🟢 match · "
                            "🔴 difference · 🟠 same sign · 🟡 one side)</span>",
                            unsafe_allow_html=True)
                st.dataframe(_val.style.apply(_mstyle, axis=None), width="stretch")

                # CSV keeps the detailed per-ledger list.
                _RL = {"MATCHED": "Matched", "DIFFERENCE": "Difference",
                       "SAME_SIGN": "Same sign", "ONE_SIDE_ONLY": "One side only"}
                _csv = pd.DataFrame({
                    "Entity A": _rec_df["Entity A"], "Ledger A": _rec_df["Ledger A"],
                    "Balance A": _rec_df["Balance A"].map(contra_engine.fmt_bal),
                    "Entity B": _rec_df["Entity B"], "Ledger B": _rec_df["Ledger B"],
                    "Balance B": _rec_df["Balance B"].map(contra_engine.fmt_bal),
                    "Difference": _rec_df["Difference"].map(contra_engine.fmt_bal),
                    "Status": [_RL.get(s, s) for s in _rec_df["Status"].tolist()]})
                sc2.download_button(
                    "⬇️ Download CSV", _csv.to_csv(index=False).encode("utf-8"),
                    file_name=f"Contra_{(_grp_name or 'group').strip()}_{active_fy}.csv",
                    mime="text/csv", width="stretch", key="contra_dl")

if _page == "msme":
    st.markdown("""
    <div class="card">
        <div class="card-title">📑 Section 43B(h) — MSME Disallowance Working</div>
        <div class="card-desc">
            Creditors with a credit balance are aged bill-wise (FIFO, oldest paid
            first). Bills to Micro/Small manufacturers &amp; service providers unpaid
            beyond 15/45 days as on 31-Mar are disallowed under 43B(h).
        </div>
    </div>
    """, unsafe_allow_html=True)

    if not company_name:
        st.markdown('<div class="status-error">⚠️ Please select a company first.</div>',
                    unsafe_allow_html=True)
    elif not active_fy:
        st.markdown('<div class="status-error">⚠️ Please select a tax year first.</div>',
                    unsafe_allow_html=True)
    elif not msme_engine._conso_master(company_name, active_fy).exists():
        st.markdown('<div class="status-running">ℹ️ Run consolidation first.</div>',
                    unsafe_allow_html=True)
    else:
        # Year follows the header's active tax year (carry-forward = prior year).
        cur_fy = active_fy
        prev_fy = _fy_prev(active_fy)
        st.caption(f"Tax year **{cur_fy}** · carry-forward from **{prev_fy or '—'}**")

        cr_df = msme_engine.creditors_with_credit_balance(company_name, cur_fy)
        st.caption(f"{len(cr_df)} creditor(s) with a credit balance at year end.")

        # Group concern → keep the Branch column; single company → hide it.
        # Auto-detected from the data (multiple branches in the consolidated file)
        # OR the Extract-tab toggle — so it works even if the toggle wasn't set.
        _branches = msme_engine.detect_branches(company_name, cur_fy)
        _is_group = (st.session_state.get("concern_type") == "Group Concern"
                     or len(_branches) > 1)
        def _hide_branch(df):
            return df.drop(columns=["Branch"]) if (not _is_group and df is not None
                                                   and "Branch" in getattr(df, "columns", [])) else df

        # Seed master from PY if empty (vendor category can change — review)
        _seed_map, _seeded = msme_engine.seed_master_from_prev(company_name, cur_fy, prev_fy)
        if _seeded and not msme_engine.load_master(company_name, cur_fy):
            msme_engine.save_master(company_name, cur_fy, _seed_map)
            st.info(f"ℹ️ Supplier MSME details seeded from {prev_fy}. Please review — "
                    "a vendor's category can change year to year.")

        ms1, ms2 = st.tabs(["🏷️ Supplier MSME Master", "📊 Disallowance Working"])

        # ── Supplier master (edit + bulk import) ──────────────────────────────
        with ms1:
            tmpl = _hide_branch(msme_engine.build_template_df(company_name, cur_fy))
            _filled = tmpl["Registered (Yes/No)"].astype(str).str.strip().replace("nan", "")
            st.caption(f"{(_filled != '').sum()} of {len(tmpl)} suppliers have MSME details filled.")

            tcol1, tcol2 = st.columns([1, 1])
            with tcol1:
                out_t = io.BytesIO()
                with pd.ExcelWriter(out_t, engine="openpyxl") as w:
                    tmpl.to_excel(w, index=False, sheet_name="MSME")
                out_t.seek(0)
                st.download_button(
                    "📥 Download template", data=out_t,
                    file_name=f"MSME_Master_{company_name}_{cur_fy}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    key="btn_msme_tmpl", width="stretch")
            with tcol2:
                up = st.file_uploader("📤 Upload filled template", type=["xlsx"],
                                      key="msme_upload", label_visibility="collapsed")
                if up is not None and st.button("✅ Import", key="btn_msme_import",
                                                width="stretch"):
                    try:
                        udf = pd.read_excel(up)
                        n = msme_engine.merge_template_df(company_name, cur_fy, udf)
                        st.success(f"✅ Imported {n} supplier(s).")
                        st.rerun()
                    except Exception as e:
                        st.error(f"❌ {e}")

            st.markdown("<hr style='margin:8px 0;'>", unsafe_allow_html=True)
            st.markdown("**Edit inline** (or use the template above for bulk):")

            edited = st.data_editor(
                tmpl, hide_index=True, width="stretch", num_rows="fixed",
                disabled=["Branch", "Party", "Closing Balance", "GSTIN"],
                column_config={
                    "Closing Balance": st.column_config.NumberColumn(format="%.2f"),
                    "Registered (Yes/No)": st.column_config.SelectboxColumn(options=msme_engine.YESNO),
                    "Classification (Micro/Small/Medium)": st.column_config.SelectboxColumn(options=msme_engine.CLASS_OPTS),
                    "Type (Manufacturer/Service/Trader)": st.column_config.SelectboxColumn(options=msme_engine.TYPE_OPTS),
                    "Agreement (Yes/No)": st.column_config.SelectboxColumn(options=["Yes", "No"]),
                },
                key="msme_editor")
            if st.button("💾 Save MSME details", key="btn_msme_save"):
                msme_engine.merge_template_df(company_name, cur_fy, edited)
                st.success("✅ Saved.")
                st.rerun()

        # ── Disallowance working ──────────────────────────────────────────────
        with ms2:
            res = msme_engine.compute(company_name, cur_fy, prev_fy or None)
            s = res["summary"]
            _drop = ["_bid"] if _is_group else ["_bid", "Branch"]

            c1, c2, c3, c4 = st.columns(4)
            summary_card(c1, "Disallowed (43B(h))", indian_format(s["disallowed"]), "#c62828")
            summary_card(c2, "Verify next year", indian_format(s["within_time"]), "#e65100")
            summary_card(c3, "Undated opening", indian_format(s["undated"]), "#e65100")
            summary_card(c4, "Applicable suppliers", str(s["applicable_parties"]), "#1f4e79")

            if res["recon"]:
                st.warning("⚠️ Opening balance did not match last year's saved closing "
                           f"for {len(res['recon'])} supplier(s) — carried as undated opening "
                           "(verify): " + ", ".join(res["recon"][:8]) +
                           ("…" if len(res["recon"]) > 8 else ""))

            wdf = res["working"]
            edf = _hide_branch(res["excluded"])
            dis_df = wdf[wdf["Status"] == "Disallowed"] if not wdf.empty else wdf
            ver_df = wdf[wdf["Status"].isin([msme_engine.VERIFY_LABEL,
                                             msme_engine.UNDATED_LABEL])] \
                if not wdf.empty else wdf

            def _fmt_amt(styler):
                return styler.format({"Unpaid Amount": lambda x: indian_format(x)
                                      if pd.notna(x) and x != "" else ""})

            d_tab, v_tab = st.tabs([
                f"🔴 Disallowed straight ({len(dis_df)})",
                f"🟠 Verify with next year ({len(ver_df)})"])

            # ----- Tab 1: straight disallowance -----
            with d_tab:
                if dis_df.empty:
                    st.info("No bills disallowed straight. Fill the Supplier MSME Master "
                            "if this looks wrong.")
                else:
                    st.dataframe(_fmt_amt(dis_df.drop(columns=_drop).style),
                                 hide_index=True, width="stretch",
                                 height=dynamic_height(dis_df))
                    st.caption("Unpaid beyond 15/45 days as on 31-Mar → disallowed u/s 43B(h).")

            # ----- Tab 2: verify with next year (one button: extract + verify) -----
            with v_tab:
                if ver_df.empty:
                    st.info("No bills to verify against next year.")
                else:
                    _due = pd.to_datetime(ver_df["Due Date"], format="%d-%m-%Y",
                                          errors="coerce")
                    _last = _due.max()
                    st.caption(
                        "These bills' 15/45-day limit expires **next year** — not disallowed "
                        "now. Open the **next-year** company in Tally, set the period from "
                        f"**01-Apr** to at least "
                        f"**{_last.strftime('%d-%m-%Y') if pd.notna(_last) else 'the last due date'}**, "
                        "then click below. We pull Sundry Creditor lines and check (FIFO) "
                        "whether each bill was paid by its due date. Flag only.")

                    _vb = ""
                    if _is_group:
                        st.caption("**Group concern:** open EACH branch's next-year "
                                   "company in Tally, type its branch name, and extract "
                                   "once per branch — they accumulate (same names as Step 1).")
                        _vb = st.text_input("Branch Name (next-year company open in Tally)",
                                            placeholder="e.g. Bangalore, Mumbai, HO...",
                                            key="msme_verify_branch")
                        _done_b = msme_engine.list_verify_branches(company_name, cur_fy)
                        if _done_b:
                            st.caption(f"Branches extracted so far: **{', '.join(_done_b)}**")

                    if st.button("📥 Extract next-year payments from Tally & verify",
                                 key="btn_msme_verify", width="stretch"):
                        if _is_group and not _vb.strip():
                            st.error("⚠️ Enter the branch name of the next-year company open in Tally.")
                        else:
                            try:
                                from engines import extract_engine
                                _, n = extract_engine.extract_msme_verify(
                                    company_name, cur_fy, _vb.strip() or None)
                                st.session_state["msme_verify_done"] = True
                                _bsfx = f" for branch '{_vb.strip()}'" if _vb.strip() else ""
                                st.success(f"✅ Extracted {n} creditor line(s){_bsfx} & verified.")
                                st.rerun()
                            except Exception as e:
                                st.error(f"❌ {e}")

                    # Merge next-year verdict (if a verify extract exists)
                    _vtxn = msme_engine.load_verify_txn(company_name, cur_fy)
                    show_df = ver_df.drop(columns=_drop).copy()
                    if not _vtxn.empty:
                        verdicts, paid_dates, asof = msme_engine.verify_next_year(
                            company_name, cur_fy, res, _vtxn)
                        nyc = ver_df["_bid"].map(verdicts).fillna("Pending verification")
                        show_df["Next-Year Check"] = nyc.values
                        show_df["Paid On"] = ver_df["_bid"].map(paid_dates).fillna("").values
                        show_df["Conclusion"] = [msme_engine.verdict_conclusion(v) for v in nyc]
                        if asof:
                            st.caption(f"Next-year data as of **{asof}**.")
                    else:
                        show_df["Next-Year Check"] = "Not verified yet"
                        show_df["Paid On"] = ""
                        show_df["Conclusion"] = "Pending verification"

                    def _hlv(row):
                        c = row.get("Conclusion", "")
                        bg = ("#e8f5e9" if c.startswith("Not disallowed")
                              else "#ffebee" if c.startswith("Disallow")
                              else "#fff3e0")
                        return [f'background-color:{bg}'] * len(row)
                    st.dataframe(_fmt_amt(show_df.style.apply(_hlv, axis=1)),
                                 hide_index=True, width="stretch",
                                 height=dynamic_height(show_df))
                    st.caption("🟢 paid within due → not disallowed • 🔴 paid after due → "
                               "review (stricter view may disallow) • 🟠 unpaid / pending.")

            # Excluded creditors
            with st.expander(f"⚪ Excluded creditors ({len(edf)}) — with reason"):
                if edf.empty:
                    st.write("None.")
                else:
                    st.dataframe(
                        edf.style.format({"Closing": lambda x: indian_format(x)}),
                        hide_index=True, width="stretch", height=dynamic_height(edf))

            # ── Save pending + export (final paper = 3 sheets) ────────────────
            ec1, ec2 = st.columns([1, 1])
            with ec1:
                if st.button("💾 Save closing pending bills", key="btn_msme_pending",
                             help="Saves this year's unpaid bills so next year they "
                                  "become the dated opening.", width="stretch"):
                    msme_engine.save_pending(company_name, cur_fy, res["pending"])
                    st.success(f"✅ Saved closing pending bills for {cur_fy}.")
            with ec2:
                # rebuild the verify sheet (with merged columns) for export
                _vtxn = msme_engine.load_verify_txn(company_name, cur_fy)
                exp_ver = ver_df.drop(columns=_drop).copy() if not ver_df.empty else ver_df
                if not ver_df.empty:
                    if not _vtxn.empty:
                        verdicts, paid_dates, _ = msme_engine.verify_next_year(
                            company_name, cur_fy, res, _vtxn)
                        nyc = ver_df["_bid"].map(verdicts).fillna("Pending verification")
                        exp_ver["Next-Year Check"] = nyc.values
                        exp_ver["Paid On"] = ver_df["_bid"].map(paid_dates).fillna("").values
                        exp_ver["Conclusion"] = [msme_engine.verdict_conclusion(v) for v in nyc]
                    else:
                        exp_ver["Next-Year Check"] = "Not verified yet"
                        exp_ver["Paid On"] = ""
                        exp_ver["Conclusion"] = "Pending verification"
                out_w = msme_engine.build_workpaper_excel({
                    "Disallowed": dis_df.drop(columns=_drop) if not dis_df.empty
                    else pd.DataFrame(),
                    "Verify_Next_Year": exp_ver if not getattr(exp_ver, "empty", True)
                    else pd.DataFrame(),
                    "Excluded": edf,
                })
                st.download_button(
                    "📥 Download working paper", data=out_w,
                    file_name=f"43Bh_MSME_{company_name}_{cur_fy}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    key="btn_msme_dl", width="stretch")


# ── Page: Clause 44 (GST expenditure break-up) ───────────────────────────────
if _page == "clause44":
    st.markdown("""
    <div class="card">
        <div class="card-title">📄 Clause 44 — Break-up of total expenditure (GST)</div>
        <div class="card-desc">
            Total expenditure split by GST registration status of the payee, per
            Form 3CD Clause 44. Registered = supplier has a valid GSTIN.
        </div>
    </div>
    """, unsafe_allow_html=True)

    if not company_name:
        st.markdown('<div class="status-error">⚠️ Please select a company first.</div>',
                    unsafe_allow_html=True)
    elif not active_fy:
        st.markdown('<div class="status-error">⚠️ Please select a tax year first.</div>',
                    unsafe_allow_html=True)
    elif not (clause44_engine._conso_dir(company_name, active_fy) /
              "Conso_MasterData.csv").exists():
        st.markdown('<div class="status-running">ℹ️ Run consolidation first.</div>',
                    unsafe_allow_html=True)
    else:
        cur_fy = active_fy
        prev_fy = _fy_prev(active_fy)

        # seed supplier categories forward from previous year
        _seed_sup, _seeded = clause44_engine.seed_suppliers_from_prev(company_name, cur_fy, prev_fy)
        if _seeded and not clause44_engine.load_suppliers(company_name, cur_fy):
            clause44_engine.save_suppliers(company_name, cur_fy, _seed_sup)
            st.info(f"ℹ️ Supplier categories seeded from {prev_fy}. Please review.")
        suppliers = clause44_engine.load_suppliers(company_name, cur_fy)

        cfg = clause44_engine.load_config(company_name, cur_fy)

        # ── scope controls ────────────────────────────────────────────────────
        sc1, sc2 = st.columns([1, 3])
        with sc1:
            include_capital = st.checkbox("Include capital additions",
                                          value=cfg["include_capital"],
                                          help="Add Fixed-Asset additions to total expenditure.")
        # full head list (no exclusions) to drive the exclude picker
        _full = clause44_engine.compute(company_name, cur_fy, suppliers,
                                        include_capital, exclude_ledgers=[],
                                        exclude_keywords=[])
        _head_opts = _full["by_head"]["Expenditure Head"].tolist() \
            if not _full["by_head"].empty else []
        with sc2:
            exclude_sel = st.multiselect(
                "Exclude ledgers from expenditure (depreciation auto-excluded)",
                options=_head_opts,
                default=[x for x in cfg["exclude_ledgers"] if x in _head_opts],
                help="e.g. inter-branch transfers, provisions, prior-period items.")

        with st.expander("⚙️ Exclusion keywords — employee & statutory costs removed from Col 2"):
            st.caption("Any expenditure ledger whose name contains one of these words is "
                       "excluded from total expenditure (they aren't a GST supply). "
                       "One keyword per line — edit freely.")
            _kw_text = st.text_area(
                "Keywords", value="\n".join(cfg.get("exclude_keywords", [])),
                key="c44_kw", height=120, label_visibility="collapsed")
            exclude_kw = [ln.strip() for ln in _kw_text.splitlines() if ln.strip()]

        if (include_capital, sorted(exclude_sel), sorted(exclude_kw)) != (
                cfg["include_capital"], sorted(cfg["exclude_ledgers"]),
                sorted(cfg.get("exclude_keywords", []))):
            clause44_engine.save_config(company_name, cur_fy, include_capital,
                                        exclude_sel, exclude_kw)

        res = clause44_engine.compute(company_name, cur_fy, suppliers,
                                      include_capital, exclude_sel, exclude_kw)
        s = res["summary"]

        st.markdown("<hr style='margin:6px 0;'>", unsafe_allow_html=True)

        m1, m2, m3, m4 = st.columns(4)
        summary_card(m1, "Total expenditure (2)", indian_format(s["total"]))
        summary_card(m2, "Registered (6)", indian_format(s["registered"]), "#2e9e5b")
        summary_card(m3, "Not registered (7)", indian_format(s["not_registered"]), "#8a5a12")
        summary_card(m4, "Under review", indian_format(s.get("review", 0.0)), "#D97757")
        if s.get("review", 0.0) > 0.5:
            st.markdown(
                f'<div class="status-running">⚠️ {indian_format(s["review"])} is under review '
                '— registered suppliers with no GST on the voucher. Classify them under '
                '<b>Supplier categories</b> (Exempt / Other / Composition) to complete the '
                '3CD identity (2) = (6) + (7).</div>', unsafe_allow_html=True)
        else:
            st.caption("✅ Reconciles: Total (2) = Registered (6) + Not registered (7); "
                       "Registered (6) = Exempt (3) + Composition (4) + Other (5).")

        c_tab, sup_tab, recon_tab, rev_tab = st.tabs(
            ["📄 Clause 44 table", "🏷️ Supplier categories",
             "📐 Reconciliation", "🔎 Review"])

        # ── Clause 44 official table + by-head detail ─────────────────────────
        with c_tab:
            clause_row = pd.DataFrame([{
                "S.No": 1, "Total (2)": s["total"], "Exempt (3)": s["exempt"],
                "Composition (4)": s["composition"], "Other registered (5)": s["other"],
                "Total registered (6)": s["registered"],
                "Under review": s.get("review", 0.0),
                "Not registered (7)": s["not_registered"],
            }])
            _amt_cols = [c for c in clause_row.columns if c != "S.No"]
            st.dataframe(clause_row.style.format({c: indian_format for c in _amt_cols}),
                         hide_index=True, width="stretch")
            st.markdown("**By expenditure head**")
            bh = res["by_head"]
            if bh.empty:
                st.info("No expenditure found for this year.")
            else:
                _bcols = [c for c in bh.columns
                          if c not in ("S.No", "Base Group", "Expenditure Head")]
                st.dataframe(bh.style.format({c: indian_format for c in _bcols}),
                             hide_index=True, width="stretch", height=dynamic_height(bh))

        # ── Reconciliation to books + excluded items ──────────────────────────
        with recon_tab:
            st.markdown("**Total expenses per books → Clause 44 expenditure (2)**")
            rt = res.get("recon_table", pd.DataFrame())
            if rt.empty:
                st.info("No data.")
            else:
                st.dataframe(rt.style.format({"Amount": indian_format}),
                             hide_index=True, width="stretch", height=dynamic_height(rt))
            st.caption(f"Per books (Purchase + Direct/Indirect Exp"
                       f"{' + capital' if include_capital else ''}): "
                       f"**{indian_format(s.get('books_total', 0.0))}**  ·  "
                       f"Excluded: **{indian_format(s.get('excluded', 0.0))}**  ·  "
                       f"Clause 44 (2): **{indian_format(s['total'])}**")
            st.markdown("**Items excluded from total expenditure** "
                        "(depreciation, employee/statutory keywords, specific ledgers)")
            exd = res.get("excluded_detail", pd.DataFrame())
            if exd.empty:
                st.success("✅ Nothing excluded.")
            else:
                st.dataframe(exd.style.format({"Amount": indian_format}),
                             hide_index=True, width="stretch", height=dynamic_height(exd))

        # ── Supplier override editor ──────────────────────────────────────────
        with sup_tab:
            rs = res["registered_suppliers"]
            if rs.empty:
                st.info("No registered suppliers found in expenditure.")
            else:
                st.caption("**Review** = registered but no GST seen on the voucher — set each "
                           "to Exempt / Other registered / Composition. Composition cannot be "
                           "detected from Tally. Anything left as Review stays out of (3)/(4)/(5).")
                edited = st.data_editor(
                    rs, hide_index=True, width="stretch", num_rows="fixed",
                    disabled=["Party", "GSTIN", "Amount"],
                    column_config={
                        "Amount": st.column_config.NumberColumn(format="%.2f"),
                        "Category": st.column_config.SelectboxColumn(
                            options=clause44_engine.CATEGORY_OPTS),
                    }, key="c44_sup_editor")
                if st.button("💾 Save categories", key="btn_c44_save", width="content"):
                    _keep = ("Other registered", "Exempt", "Composition")
                    mapping = {str(r["Party"]).strip(): r["Category"]
                               for _, r in edited.iterrows()
                               if r["Category"] in _keep}
                    clause44_engine.save_suppliers(company_name, cur_fy, mapping)
                    st.success("✅ Saved.")
                    st.rerun()

        # ── Review panels ─────────────────────────────────────────────────────
        with rev_tab:
            st.markdown("**Pending review** (registered supplier, no GST on the voucher) — "
                        "classify each in the **Supplier categories** tab.")
            rvd = res.get("review_detail", pd.DataFrame())
            if rvd.empty:
                st.success("✅ Nothing pending review.")
            else:
                st.dataframe(rvd.style.format({"Amount": indian_format}),
                             hide_index=True, width="stretch", height=dynamic_height(rvd))
            st.markdown("**Parties with no GSTIN** (treated as *not registered*) — "
                        "fix GSTIN in Tally if any are actually registered.")
            ng = res["no_gstin"]
            if ng.empty:
                st.success("✅ None.")
            else:
                st.dataframe(ng.style.format({"Amount": indian_format}),
                             hide_index=True, width="stretch", height=dynamic_height(ng))
            st.markdown("**Exempt (3)** — suppliers you marked as exempt / nil-rated.")
            ed = res["exempt_detail"]
            if ed.empty:
                st.success("✅ None.")
            else:
                st.dataframe(ed.style.format({"Amount": indian_format}),
                             hide_index=True, width="stretch", height=dynamic_height(ed))

        st.markdown("<hr style='margin:6px 0;'>", unsafe_allow_html=True)
        out_c44 = clause44_engine.build_excel(company_name, cur_fy, res)
        st.download_button("📥 Download Clause 44 working paper", data=out_c44,
                           file_name=f"Clause44_{company_name}_{cur_fy}.xlsx",
                           mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                           key="btn_c44_dl", width="content")


# ── Page: Financials (NCE) ────────────────────────────────────────────────────
if _dev and _page == "nce":
    import fs_ui
    fs_ui.render_nce(company_name, active_fy)

# ── Footer ────────────────────────────────────────────────────────────────────
st.markdown("""
<div style="text-align:center; color:#aaa; font-size:11px;
            padding:8px 0; border-top:1px solid #e0e0e0; margin-top:8px;">
    Audit Lite &nbsp;|&nbsp;
    Created by <b style="color:#1f4e79;">CA DSP</b>
</div>
""", unsafe_allow_html=True)