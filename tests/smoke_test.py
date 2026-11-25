"""Offline smoke test using made-up data only. Run: python -B tests/smoke_test.py

All app data is redirected to a temporary folder before any engine is imported,
so real company data is never read or written. Tally is not needed.
"""
import os, sys, tempfile, pathlib
ROOT = pathlib.Path(__file__).resolve().parents[1]
TMP = pathlib.Path(tempfile.mkdtemp(prefix="lstool_test_"))
os.environ["USERPROFILE"] = str(TMP)
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))
import paths
paths._LOCATION_FILE = TMP / "data_location.json"
paths.LSTOOL_ROOT = TMP / "LSTool"
paths.BASE = paths.LSTOOL_ROOT / "data"
paths.SYSTEM_SECTIONS = paths.BASE / "system_sections.json"
paths.WORD_RULES = paths.BASE / "word_rules.json"

import pandas as pd
CO, FY = "Sample Traders", "2025-26"
paths.ensure_year(CO, FY)
import fs_engine, streamlit
assert str(TMP) in str(fs_engine.BASE_DATA_DIR)
PAN = "AAAAA0000A"
# Extraction writes $_PartyGSTIN1; override only to test the older layout.
GSTIN_COL = os.environ.get("LSTOOL_TEST_GSTIN_COL", "$_PartyGSTIN1")
pd.DataFrame([
    # name, primary group, parent, opening, closing, prev, gstin, pan, nature, gp
    ["Supplier One", "Sundry Creditors", "Sundry Creditors", 0, 59000, 0, "", PAN, "BS", 0],
    ["Supplier Debit", "Sundry Creditors", "Sundry Creditors", 0, -5000, 0, "", "", "BS", 0],
    ["Old Deposit", "Deposits (Asset)", "Deposits (Asset)", -1000, -1000, -1000, "", "", "BS", 0],
    ["Office Rent", "Indirect Expenses", "Indirect Expenses", 0, -50000, 0, "", "", "PL", 0],
    ["Cash", "Cash-in-hand", "Cash-in-hand", -20000, -5000, -20000, "", "", "BS", 0],
], columns=["$Name", "$_PrimaryGroup", "$Parent", "$OpeningBalance", "$ClosingBalance",
            "$_PrevYearBalance", GSTIN_COL, "$PAN", "$Nature_Led", "$GP"]
).to_csv(paths.extracted_dir(CO, FY) / "HO_MasterData.csv", index=False)
cols = ["$VoucherNumber", "$Supplier_VchNo", "$VoucherId", "$Date", "$VoucherTypeName",
        "$VchTypeParent", "$Particulars", "$Amount", "$Led_Parent", "$Led_Group",
        "$Led_BaseGroup", "$Party_LedName", "$Led_GSTIN", "$Led_PAN", "$Party_Flag"]
def v(no, d, typ, led, amt, grp, party):
    return [no, "", no, d, typ, typ, led, amt, grp, grp, grp, party, "", PAN, ""]
pd.DataFrame([
    v("1", "2025-04-05", "Journal", "Office Rent", -50000, "Indirect Expenses", "Supplier One"),
    v("1", "2025-04-05", "Journal", "Supplier One", 50000, "Sundry Creditors", "Supplier One"),
    v("2", "2025-05-05", "Payment", "Supplier One", -15000, "Sundry Creditors", "Supplier One"),
    v("2", "2025-05-05", "Payment", "Cash", 15000, "Cash-in-hand", "Supplier One"),
], columns=cols).to_csv(paths.extracted_dir(CO, FY) / "HO_Transactions.csv", index=False)

from engines import consolidate_engine, ls_runner
consolidate_engine.main(CO, FY)
res = ls_runner.run_ls_for_company(CO, FY)
rep = paths.analysis_dir(CO, FY) / "Ledger_Scrutiny_Report.xlsx"
print("scrutiny:", res.get("status"))
assert rep.exists()
sheets = pd.read_excel(rep, sheet_name=None, header=None)
same = sheets["Same_Opening_Closing"].astype(str)
assert same.apply(lambda c: c.str.contains("Old Deposit")).any().any()
print("report sheets:", len(sheets))

from streamlit.testing.v1 import AppTest
fails = 0
at = AppTest.from_file(str(ROOT / "streamlit_app.py"), default_timeout=120)
at.run()
assert CO in at.selectbox(key="selected_company").options
assert all(o in ("", CO) for o in at.selectbox(key="selected_company").options)
at.selectbox(key="selected_company").select(CO).run()
pages = ["extract", "analysis", "tdsrules", "scrutiny", "viewer", "related", "contra", "msme", "clause44"]
for p in pages:
    at.session_state["nav_page"] = p
    at.run()
    ex = [e.message for e in at.exception]
    fails += bool(ex)
    print(f"page {p}: {'OK' if not ex else ex}")
print("company shown:", at.selectbox(key="selected_company").value)
assert at.selectbox(key="selected_company").value == CO
sys.exit(1 if fails else 0)
