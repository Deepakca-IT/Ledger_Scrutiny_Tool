"""
NCE Financial Statements — grouping vocabulary + predefined default rules.

Two things live here:
  1. FACE_NOTE_VOCAB : controlled vocabulary for the cascading dropdowns
     Face Grouping -> list of Note Groupings (Sub-Note is free level-3 text).
     Special note "Specify at Level 3": the Sub-Note is MANDATORY and is
     displayed AT NOTE LEVEL in the output (not as a third level).
  2. default_grouping(): predefined rules that map a Tally ledger to its
     (Face, Note) automatically. The CA reviews/overrides in the UI; overrides
     are saved per company and carried forward year-on-year.

Adapted for Non-Corporate Entities (Proprietor / Partnership) from the ICAI format.
"""
import math
from collections import OrderedDict

ENTITY_TYPES = ["Partnership", "Proprietor"]

SPECIFY_L3 = "Specify at Level 3"


def is_specify_l3(note):
    return _safe_str(note).lower().startswith("specify at level")


def _safe_str(x):
    """Coerce any value (incl. NaN / None / numbers) to a clean string."""
    if x is None:
        return ""
    if isinstance(x, float) and math.isnan(x):
        return ""
    return str(x).strip()


_INVESTMENT_NOTES = [
    "Quoted Trade Investments in Equity Instruments",
    "Quoted Trade Investments in preference shares",
    "Quoted Trade Investments in Government or trust securities",
    "Quoted Trade Investments in debentures or bonds",
    "Quoted Trade Investments in Mutual Funds",
    "Unquoted Trade Investments in Equity Instruments",
    "Unquoted Trade Investments in preference shares",
    "Unquoted Trade Investments in Government or trust securities",
    "Unquoted Trade Investments in debentures or bonds",
    "Unquoted Trade Investments in Mutual Funds",
    "Quoted Other Investments in Equity Instruments",
    "Quoted Other Investments in preference shares",
    "Quoted Other Investments in Government or trust securities",
    "Quoted Other Investments in debentures or bonds",
    "Quoted Other Investments in Mutual Funds",
    "Unquoted Other Investments in Equity Instruments",
    "Unquoted Other Investments in preference shares",
    "Unquoted Other Investments in Government or trust securities",
    "Unquoted Other Investments in debentures or bonds",
    "Unquoted Other Investments in Mutual Funds",
    "Investments in partnership firms",
]

# ── Controlled vocabulary: Face Grouping -> allowed Note Groupings ─────────────
FACE_NOTE_VOCAB = OrderedDict([
    # --- Owners' fund ---
    ("Partners Capital Account", ["Partners Capital Account", "Partners Current Account"]),
    ("Owner's Capital Account", ["Capital Account", "Drawings", "Others"]),
    ("Reserves and surplus", ["General Reserve", "Revaluation Reserve",
                              "Profit & Loss Account", "Other Reserves", "Capital Reserves"]),
    # --- Non-current liabilities ---
    ("Long term borrowings", [
        "Secured Term loans from banks", "Secured Term loans from other parties",
        "Secured Deferred payment liabilities", "Secured Loans and advances from related parties",
        "Secured Long term maturities of finance lease obligations",
        "Secured Other loans and advances",
        "Unsecured Term loans from banks", "Unsecured Term loans from other parties",
        "Unsecured Deferred payment liabilities",
        "Unsecured Loans and advances from related parties",
        "Unsecured Long term maturities of finance lease obligations",
        "Unsecured Other loans and advances"]),
    ("Deferred tax liabilities Net", [SPECIFY_L3]),
    ("Other Long term liabilities", ["Trade Payable", "Others", SPECIFY_L3]),
    ("Long term provisions", ["Provision for employee benefits", "Others", SPECIFY_L3]),
    # --- Current liabilities ---
    ("Short term borrowings", [
        "Current maturities of long-term debt",
        "Secured Loans repayable on demand from banks",
        "Secured Loans repayable on demand from other parties",
        "Secured Loans and advances from related parties", "Secured Other loans and advances",
        "Unsecured Loans repayable on demand from banks",
        "Unsecured Loans repayable on demand from other parties",
        "Unsecured Loans and advances from related parties",
        "Unsecured Other loans and advances"]),
    ("Trade payables due to MSME", ["Due to Micro ,Small and Medium Enterprises"]),
    ("Trade payables due to others", ["Due to others"]),
    ("Other current liabilities", [
        "Current maturities of finance lease obligations",
        "Interest accrued but not due on borrowings", "Interest accrued and due on borrowings",
        "Income received in advance", "Advances from Customers", "Income Tax Payable",
        "GST Payable", "TDS Payable", "TCS Payable", "Provident Fund Payable",
        "ESIC Payable", "Professional Tax Payable", "Other Payables", SPECIFY_L3]),
    ("Short term provisions", ["Provision for employee benefits", "Provision for Income tax",
                               "Other provisions", SPECIFY_L3]),
    # --- Non-current assets ---
    ("Property Plant and Equipment", ["Captured from FAR"]),
    ("Intangible assets", ["Captured From FAR"]),
    ("Capital work in progress", ["Captured in PPE Notes"]),
    ("Intangible assets under development", ["Captured in PPE Notes"]),
    ("Non current investments", ["Investment Property"] + _INVESTMENT_NOTES +
        ["Investments in Fixed Deposits", "Other Non Current Investment"]),
    ("Deferred tax assets net", [SPECIFY_L3]),
    ("Long term loans and advances", [
        "Capital Advances", "Loans and advances to related parties",
        "Advance Income Tax (Net of provision for taxes)",
        "Balances with Government Authorities",
        "Other loans and advances (Secured, considered good)",
        "Other loans and advances (Unsecured, considered good)",
        "Other loans and advances (Doubtful)", "Provision for doubtful advances", "Others"]),
    ("Other non current assets", [
        "Long-term Trade Receivables (Secured, considered good)",
        "Long-term Trade Receivables (Unsecured, considered good)",
        "Long-term Trade Receivables (Doubtful)", "Provision for doubtful debts",
        "Security Deposits", "Bank Deposit having maturity of greater than 12 months",
        "Others", SPECIFY_L3]),
    # --- Current assets ---
    ("Current investments", _INVESTMENT_NOTES + ["Other investments"]),
    ("Inventories", ["Captured from Disclosure Tab"]),
    ("Trade receivables", ["Secured considered good", "Unsecured considered good",
                           "Doubtful", "Provision for doubtful debts"]),
    ("Cash and bank balances", [
        "Cash on hand", "Balances with banks", "Cheques, drafts on hand",
        "Bank Deposit having maturity of less than 3 months",
        "Bank Deposit having maturity of greater than 3 months and less than 12 months",
        "Bank Deposit having maturity of greater than 12 months", "Others"]),
    ("Short term loans and advances", [
        "Loans and advances to related parties",
        "Advance Income Tax (Net of provision for taxes)",
        "Balances with Government Authorities", "Advances to Creditors",
        "Advances to Employees",
        "Other loans and advances (Secured, considered good)",
        "Other loans and advances (Unsecured, considered good)",
        "Other loans and advances (Doubtful)", "Provision for doubtful advances", "Others"]),
    ("Other current assets", ["Advances to Creditors", "Prepaid Expenses",
                              "Interest Receivable", "Rent Receivable",
                              "Other Income Receivable", SPECIFY_L3]),
    ("HO Branch Account", [SPECIFY_L3]),
    # --- P&L : income ---
    ("Revenue from operations", ["Sale of products", "Sale of services",
                                 "Grants or donations received",
                                 "Other operating revenues", "Others"]),
    ("Other Income", ["Interest Income", "Dividend Income", "Rent Income",
                      "Net gain/loss on sale of investments",
                      "Other non-operating income (net of expenses)", "Others", SPECIFY_L3]),
    # --- P&L : expenses ---
    ("Cost of material consumed", ["Captured from Disclosure Tab"]),
    ("Purchases of stock in trade", [SPECIFY_L3]),
    ("Change in Inventories of work in progress and finished goods",
        ["Captured from Disclosure Tab"]),
    ("Direct Expenses", [SPECIFY_L3]),
    ("Employee benefit expenses", ["Salaries and wages",
                                   "Contribution to provident and other funds",
                                   "Expense on ESOP and ESPP", "Staff welfare expenses"]),
    ("Partners remuneration", ["Fill details in the Partners Sheet"]),
    ("Finance costs", ["Interest expense", "Interest on Partners' Capital",
                       "Other borrowing costs",
                       "Applicable net gain/loss on foreign currency transactions and translation"]),
    ("Depreciation and amortization expenses", [SPECIFY_L3]),
    ("Other expenses", [
        "Commission", "Consultancy fees", "Consumption of stores and spare parts",
        "Conveyance expenses", "Direct expenses", "Freight Inward", "Freight outward",
        "Indirect expenses", "Auditors' Remuneration", "Administrative Expenses",
        "Advertisement", "Bad debts", "Insurance", "Manufacturing Expenses",
        "Power and fuel", "Rent", "Repairs to buildings", "Repairs to machinery",
        "Repairs others", "Rates and taxes", "Professional fees",
        "Provision for bad and doubtful debts", "Royalty",
        "Selling & Distribution Expenses", "Other Business Administrative Expenses",
        "Telephone expenses", "Travelling Expenses", "Miscellaneous expenses",
        "Other Expenses", SPECIFY_L3]),
    # --- P&L : exceptional / extraordinary / discontinuing ---
    ("Exceptional item", [SPECIFY_L3]),
    ("Extraordinary Item", [SPECIFY_L3]),
    ("Prior Period Item", [SPECIFY_L3]),
    ("Profit loss from discontinuing operation before tax", [SPECIFY_L3]),
    # --- P&L : tax ---
    ("Tax Expenses", ["Current Tax", "Deferred Tax", "AMT Credit Entitlement",
                      "Prior Period Taxes", "Excess/Short Provision Written back/off"]),
    ("Tax expenses of discontinuing operation", [SPECIFY_L3]),
    ("Not Mapped", ["To be grouped"]),
])

FACE_LIST = list(FACE_NOTE_VOCAB.keys())


def face_list_for(entity_label=None):
    """Face dropdown options for the mapping editor. 'Reserves and surplus' is
    hidden for a Proprietor or a Partnership Firm (only an LLP carries reserves);
    it stays in the vocabulary so any already-saved mapping still renders — it's
    only hidden from the picker."""
    el = _safe_str(entity_label).lower()
    if el == "llp":
        return list(FACE_LIST)
    return [f for f in FACE_LIST if f != "Reserves and surplus"]
# Flat list of all notes (for the grid's Note dropdown)
ALL_NOTES = []
for _notes in FACE_NOTE_VOCAB.values():
    for _n in _notes:
        if _n not in ALL_NOTES:
            ALL_NOTES.append(_n)


# ── Which financial statement each Face belongs to ────────────────────────────
FACE_SECTION = {
    # Owners' fund
    "Partners Capital Account": "equity",
    "Owner's Capital Account": "equity",
    "Reserves and surplus": "equity",
    # Liabilities
    "Long term borrowings": "liability",
    "Deferred tax liabilities Net": "liability",
    "Other Long term liabilities": "liability",
    "Long term provisions": "liability",
    "Short term borrowings": "liability",
    "Trade payables due to MSME": "liability",
    "Trade payables due to others": "liability",
    "Other current liabilities": "liability",
    "Short term provisions": "liability",
    # Assets
    "Property Plant and Equipment": "asset",
    "Intangible assets": "asset",
    "Capital work in progress": "asset",
    "Intangible assets under development": "asset",
    "Non current investments": "asset",
    "Deferred tax assets net": "asset",
    "Long term loans and advances": "asset",
    "Other non current assets": "asset",
    "Current investments": "asset",
    "Inventories": "asset",
    "Trade receivables": "asset",
    "Cash and bank balances": "asset",
    "Short term loans and advances": "asset",
    "Other current assets": "asset",
    "HO Branch Account": "asset",   # inter-branch net; review sign per entity
    # P&L income
    "Revenue from operations": "income",
    "Other Income": "income",
    # P&L expenses
    "Cost of material consumed": "expense",
    "Purchases of stock in trade": "expense",
    "Change in Inventories of work in progress and finished goods": "expense",
    "Direct Expenses": "expense",
    "Employee benefit expenses": "expense",
    "Partners remuneration": "expense",
    "Finance costs": "expense",
    "Depreciation and amortization expenses": "expense",
    "Other expenses": "expense",
    "Exceptional item": "expense",
    "Extraordinary Item": "expense",
    "Prior Period Item": "expense",
    "Profit loss from discontinuing operation before tax": "expense",
    "Tax Expenses": "expense",
    "Tax expenses of discontinuing operation": "expense",
    # Unmapped
    "Not Mapped": "unmapped",
}


def face_section(face):
    """Statement section for a Face: asset / liability / equity / income / expense / unmapped."""
    return FACE_SECTION.get(_safe_str(face), "unmapped")


# ── Migration: old face names (saved groupings) -> new canonical names ─────────
FACE_MIGRATE = {
    "Partners' Capital Account": "Partners Capital Account",
    "Reserves and Surplus": "Reserves and surplus",
    "Long-term Borrowings": "Long term borrowings",
    "Deferred Tax Liabilities (net)": "Deferred tax liabilities Net",
    "Other Long-term Liabilities": "Other Long term liabilities",
    "Long-term Provisions": "Long term provisions",
    "Short-term Borrowings": "Short term borrowings",
    "Other Current Liabilities": "Other current liabilities",
    "Short-term Provisions": "Short term provisions",
    "Property, Plant and Equipment": "Property Plant and Equipment",
    "Intangible Assets": "Intangible assets",
    "Capital Work-in-progress": "Capital work in progress",
    "Non-current Investments": "Non current investments",
    "Deferred Tax Assets (net)": "Deferred tax assets net",
    "Long-term Loans and Advances": "Long term loans and advances",
    "Other Non-current Assets": "Other non current assets",
    "Current Investments": "Current investments",
    "Trade Receivables": "Trade receivables",
    "Cash and Bank Balances": "Cash and bank balances",
    "Short-term Loans and Advances": "Short term loans and advances",
    "Other Current Assets": "Other current assets",
    "Revenue from Operations": "Revenue from operations",
    "Cost of Materials Consumed": "Cost of material consumed",
    "Purchases of Stock-in-Trade": "Purchases of stock in trade",
    "Changes in Inventories": "Change in Inventories of work in progress and finished goods",
    "Direct / Manufacturing Expenses": "Direct Expenses",
    "Employee Benefit Expenses": "Employee benefit expenses",
    "Finance Costs": "Finance costs",
    "Depreciation and Amortization": "Depreciation and amortization expenses",
    "Other Expenses": "Other expenses",
    "Exceptional Items": "Exceptional item",
    "Extraordinary Items": "Extraordinary Item",
}


def migrate_face_note(face, note):
    """Map a saved (face, note) from the old vocabulary to the new one.
    Faces already in the new vocabulary pass through unchanged. Notes that no
    longer exist are kept as free text (they still render)."""
    face = _safe_str(face)
    note = _safe_str(note)
    if face == "Trade Payables":   # old single face split into MSME / others
        if "msme" in note.lower() or "micro" in note.lower():
            return "Trade payables due to MSME", "Due to Micro ,Small and Medium Enterprises"
        return "Trade payables due to others", "Due to others"
    return FACE_MIGRATE.get(face, face), note


# ── Statement layouts (ICAI NCE order) ────────────────────────────────────────
# Three-level layout: (group, [(sub_label, lettered, [(subsub_label|None, roman, [faces])])]).
#   lettered  -> each rendered item under the sub gets a letter (a), (b), (c)…
#   roman     -> visible faces inside a named sub-sub group get (i), (ii), (iii)…
# Letters/romans are assigned dynamically to the items that actually appear, so
# hidden (zero) faces never leave a gap in the sequence.
BS_LAYOUT = [
    ("EQUITY AND LIABILITIES", [
        ("Owners' funds", False,
            [(None, False, ["Partners Capital Account", "Owner's Capital Account",
                            "Reserves and surplus"])]),
        ("Non-current liabilities", False,
            [(None, False, ["Long term borrowings", "Deferred tax liabilities Net",
                            "Other Long term liabilities", "Long term provisions"])]),
        ("Current liabilities", False,
            [(None, False, ["Short term borrowings", "Trade payables due to MSME",
                            "Trade payables due to others", "Other current liabilities",
                            "Short term provisions"])]),
    ]),
    ("ASSETS", [
        ("Non-current assets", True, [
            ("Property, Plant and Equipment and Intangible Assets", True,
                ["Property Plant and Equipment", "Intangible assets",
                 "Capital work in progress", "Intangible assets under development"]),
            (None, False, ["Non current investments"]),
            (None, False, ["Deferred tax assets net"]),
            (None, False, ["Long term loans and advances"]),
            (None, False, ["Other non current assets"]),
        ]),
        ("Current assets", False,
            [(None, False, ["Current investments", "Inventories", "Trade receivables",
                            "Cash and bank balances", "Short term loans and advances",
                            "Other current assets", "HO Branch Account"])]),
    ]),
]

# Roman/letter sequences for the Balance-Sheet sub-grouping.
ROMAN_SEQ = ["(i)", "(ii)", "(iii)", "(iv)", "(v)", "(vi)", "(vii)", "(viii)", "(ix)", "(x)"]
LETTER_SEQ = ["(a)", "(b)", "(c)", "(d)", "(e)", "(f)", "(g)", "(h)", "(i)", "(j)"]

# Statement of P&L: ordered Face buckets.
PL_INCOME = ["Revenue from operations", "Other Income"]
PL_EXPENSES = ["Cost of material consumed", "Purchases of stock in trade",
               "Change in Inventories of work in progress and finished goods",
               "Direct Expenses", "Employee benefit expenses", "Partners remuneration",
               "Finance costs", "Depreciation and amortization expenses", "Other expenses"]
PL_EXCEPTIONAL = ["Exceptional item", "Extraordinary Item", "Prior Period Item",
                  "Profit loss from discontinuing operation before tax"]
PL_TAX = ["Tax Expenses", "Tax expenses of discontinuing operation"]

# ── Presentation registries (themes / borders / fonts) ────────────────────────
THEMES = OrderedDict([
    ("Theme 1", {"header_bg": "#1f4e79", "header_fg": "#ffffff",
                 "heading": "#1f4e79", "cy_shade": "#dbe7f3"}),   # blue
    ("Theme 2", {"header_bg": "#2e7d32", "header_fg": "#ffffff",
                 "heading": "#1b6b34", "cy_shade": "#d8efdc"}),   # green (ref look)
    ("Theme 3", {"header_bg": "#4d4d4d", "header_fg": "#ffffff",
                 "heading": "#333333", "cy_shade": "#e6e6e6"}),   # grey
    ("Theme 4", {"header_bg": "#7b1fa2", "header_fg": "#ffffff",
                 "heading": "#5e1280", "cy_shade": "#ead6f2"}),   # purple
    ("Theme 5", {"header_bg": "#b34700", "header_fg": "#ffffff",
                 "heading": "#8a3700", "cy_shade": "#f6e2d2"}),   # rust
])
THEME_LIST = list(THEMES.keys())

BORDERS = OrderedDict([
    ("Layout 1", {"css": "1px solid #333", "xl": "thin"}),      # full grid
    ("Layout 2", {"css": "1px solid #bbb", "xl": "hair"}),      # light grid
    ("Layout 3", {"css": "none", "xl": None}),                  # rule lines only
])
BORDER_LIST = list(BORDERS.keys())

FONTS = ["Calibri", "Arial", "Times New Roman", "Georgia", "Verdana"]

ROUND_OFF_OPTIONS = ["In Rs", "Rs '00", "Rs '000", "Rs Lakhs", "Rs Crores"]
ENTITY_TYPE_OPTIONS = ["Proprietorship", "Partnership Firm", "LLP"]
DESIGNATION_OPTIONS = ["Partner", "Designated Partner", "Proprietor"]


# ── FAR (Fixed Assets Register) — Income-tax block depreciation ───────────────
FAR_CATEGORIES = ["Tangible", "Intangible"]
FAR_RATES = OrderedDict([
    ("Tangible", OrderedDict([
        ("Land", 0),
        ("Building", 10),
        ("Furniture", 10),
        ("Plant and Machinery", 15),
        ("Office equipment", 15),
        ("Vehicles", 15),
        ("Computers", 40),
    ])),
    ("Intangible", OrderedDict([
        ("Intangible Assets", 25),
    ])),
])
FAR_FACE = {"Tangible": "Property Plant and Equipment",
            "Intangible": "Intangible assets"}


def far_blocks(category):
    return list(FAR_RATES.get(category, OrderedDict()).keys())


def far_rate(category, block):
    return float(FAR_RATES.get(category, {}).get(block, 0) or 0)


def far_face(category):
    return FAR_FACE.get(category, "Property Plant and Equipment")


def theme(name):
    return THEMES.get(name, THEMES["Theme 1"])


def border(name):
    return BORDERS.get(name, BORDERS["Layout 1"])


def _kw(name, words):
    n = (name or "").lower()
    return any(w in n for w in words)


def default_grouping(primary_group, ledger_name="", entity_type="Partnership", closing=0.0):
    """Predefined rule: Tally primary group (+ ledger-name keywords + balance sign) -> (face, note).
    Sign convention: Debit = negative, Credit = positive.
    Returns dict(face, note, subnote). For "Specify at Level 3" notes the ledger
    name is used as the (mandatory) sub-note so the output shows it at note level."""
    pg = _safe_str(primary_group).lower()
    name = _safe_str(ledger_name)
    nl = name.lower()
    # Accept both the collapsed ('Proprietor'/'Partnership') and the rich
    # ('Proprietorship'/'Partnership Firm'/'LLP') entity vocabularies.
    et = _safe_str(entity_type).lower()
    is_prop = et.startswith("propriet")
    is_llp = (et == "llp")
    is_firm = not is_prop and not is_llp     # Partnership / Partnership Firm

    def r(face, note="", subnote=""):
        if is_specify_l3(note) and not subnote:
            subnote = name   # mandatory level-3 detail; shown at note level
        return {"face": face, "note": note, "subnote": subnote}

    # P&L appropriation account (Tally's "Profit & Loss A/c" primary ledger).
    # It carries no Tally primary group, so route it by entity type: it belongs
    # to the proprietor's / firm's capital; only an LLP shows Reserves & Surplus.
    if ("profit & loss" in nl or "profit and loss" in nl
            or nl in ("p&l a/c", "p & l a/c")) and pg in ("", "profit & loss a/c", "primary"):
        if is_prop:
            return r("Owner's Capital Account", "Capital Account")
        if is_llp:
            return r("Reserves and surplus", "Profit & Loss Account")
        return r("Partners Capital Account", "Partners Capital Account")

    # ── Owners' fund & liabilities ──
    if pg in ("capital account",):
        if is_prop:
            return r("Owner's Capital Account", "Capital Account")
        return r("Partners Capital Account", "Partners Capital Account")
    if pg in ("reserves & surplus", "reserves and surplus"):
        if _kw(name, ["general"]):
            return r("Reserves and surplus", "General Reserve")
        return r("Reserves and surplus", "Other Reserves")
    if pg in ("secured loans",):
        return r("Long term borrowings", "Secured Term loans from banks")
    if pg in ("unsecured loans",):
        # user to confirm long vs short
        return r("Long term borrowings", "Unsecured Other loans and advances")
    if pg in ("loans (liability)",):
        return r("Long term borrowings", "Secured Term loans from banks")
    if pg in ("bank od a/c", "bank od accounts", "bank occ a/c"):
        return r("Short term borrowings", "Secured Loans repayable on demand from banks")
    if pg in ("sundry creditors",):
        # Debit balance (negative) on a creditor = advance paid to supplier
        if closing < 0:
            return r("Short term loans and advances", "Advances to Creditors")
        if _kw(name, ["msme", "micro"]):
            return r("Trade payables due to MSME", "Due to Micro ,Small and Medium Enterprises")
        return r("Trade payables due to others", "Due to others")
    if pg in ("duties & taxes", "duties and taxes"):
        if _kw(name, ["gst", "cgst", "sgst", "igst"]):
            return r("Other current liabilities", "GST Payable")
        if _kw(name, ["tds"]):
            return r("Other current liabilities", "TDS Payable")
        if _kw(name, ["tcs"]):
            return r("Other current liabilities", "TCS Payable")
        if _kw(name, ["provident", "pf "]):
            return r("Other current liabilities", "Provident Fund Payable")
        if _kw(name, ["esi"]):
            return r("Other current liabilities", "ESIC Payable")
        if _kw(name, ["profession"]):
            return r("Other current liabilities", "Professional Tax Payable")
        if _kw(name, ["income tax"]):
            return r("Other current liabilities", "Income Tax Payable")
        return r("Other current liabilities", "Other Payables")
    if pg in ("provisions",):
        if _kw(name, ["tax", "income tax"]):
            return r("Short term provisions", "Provision for Income tax")
        return r("Short term provisions", "Other provisions")
    if pg in ("current liabilities",):
        return r("Other current liabilities", "Other Payables")
    if pg in ("branch / divisions", "branch/divisions", "branch / division"):
        return r("HO Branch Account", SPECIFY_L3)

    # ── Assets ──
    if pg in ("fixed assets",):
        return r("Property Plant and Equipment", "Captured from FAR")
    if pg in ("investments",):
        return r("Non current investments", "Other Non Current Investment")
    if pg in ("stock-in-hand", "stock in hand"):
        return r("Inventories", "Captured from Disclosure Tab")
    if pg in ("sundry debtors",):
        # Credit balance (positive) on a debtor = advance received from customer
        if closing > 0:
            return r("Other current liabilities", "Advances from Customers")
        return r("Trade receivables", "Unsecured considered good")
    if pg in ("cash-in-hand", "cash in hand"):
        return r("Cash and bank balances", "Cash on hand")
    if pg in ("bank accounts",):
        if _kw(name, ["deposit", "fd", "fixed deposit"]):
            return r("Cash and bank balances",
                     "Bank Deposit having maturity of greater than 3 months and less than 12 months")
        return r("Cash and bank balances", "Balances with banks")
    if pg in ("loans & advances (asset)", "loans and advances (asset)"):
        if _kw(name, ["deposit"]):
            return r("Other non current assets", "Security Deposits")
        return r("Short term loans and advances", "Others")
    if pg in ("deposits (asset)",):
        return r("Other non current assets", "Security Deposits")
    if pg in ("misc. expenses (asset)", "misc expenses (asset)"):
        return r("Other non current assets", "Others")
    if pg in ("current assets",):
        return r("Other current assets", SPECIFY_L3)

    # ── P&L income ──
    if pg in ("sales accounts",):
        return r("Revenue from operations", "Sale of products")
    if pg in ("direct income", "direct incomes"):
        return r("Revenue from operations", "Other operating revenues")
    if pg in ("indirect income", "indirect incomes"):
        if _kw(name, ["interest"]):
            return r("Other Income", "Interest Income")
        if _kw(name, ["rent"]):
            return r("Other Income", "Rent Income")
        if _kw(name, ["dividend"]):
            return r("Other Income", "Dividend Income")
        return r("Other Income", "Other non-operating income (net of expenses)")

    # ── P&L expenses ──
    if pg in ("purchase accounts",):
        return r("Purchases of stock in trade", SPECIFY_L3)
    if pg in ("direct expenses",):
        return r("Direct Expenses", SPECIFY_L3)
    if pg in ("indirect expenses",):
        if _kw(name, ["remuneration"]) and _kw(name, ["partner"]):
            return r("Partners remuneration", "Fill details in the Partners Sheet")
        if _kw(name, ["interest on capital", "interest on partners"]):
            return r("Finance costs", "Interest on Partners' Capital")
        if _kw(name, ["salary", "salaries", "wages", "bonus", "staff", "pf", "esi",
                      "gratuity", "welfare", "epf"]):
            return r("Employee benefit expenses", "Salaries and wages")
        if _kw(name, ["bank charge", "processing fee", "loan charge"]):
            return r("Finance costs", "Other borrowing costs")
        if _kw(name, ["interest", "finance"]):
            return r("Finance costs", "Interest expense")
        if _kw(name, ["depreciation", "amortization", "amortisation"]):
            return r("Depreciation and amortization expenses", SPECIFY_L3)
        if _kw(name, ["rent"]):
            return r("Other expenses", "Rent")
        if _kw(name, ["insurance"]):
            return r("Other expenses", "Insurance")
        if _kw(name, ["rates", "tax"]):
            return r("Other expenses", "Rates and taxes")
        if _kw(name, ["audit"]):
            return r("Other expenses", "Auditors' Remuneration")
        if _kw(name, ["consultanc"]):
            return r("Other expenses", "Consultancy fees")
        if _kw(name, ["legal", "professional"]):
            return r("Other expenses", "Professional fees")
        if _kw(name, ["telephone", "mobile"]):
            return r("Other expenses", "Telephone expenses")
        if _kw(name, ["travel"]):
            return r("Other expenses", "Travelling Expenses")
        if _kw(name, ["convey"]):
            return r("Other expenses", "Conveyance expenses")
        if _kw(name, ["advertis"]):
            return r("Other expenses", "Advertisement")
        if _kw(name, ["commission"]):
            return r("Other expenses", "Commission")
        if _kw(name, ["power", "electric", "fuel"]):
            return r("Other expenses", "Power and fuel")
        if _kw(name, ["freight in", "carriage in"]):
            return r("Other expenses", "Freight Inward")
        if _kw(name, ["freight", "carriage"]):
            return r("Other expenses", "Freight outward")
        if _kw(name, ["bad debt"]):
            return r("Other expenses", "Bad debts")
        return r("Other expenses", "Other Expenses")

    # ── Fallback ──
    return r("Not Mapped", "To be grouped")
