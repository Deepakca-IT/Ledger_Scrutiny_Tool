import pandas as pd
from pathlib import Path
import paths
from engines.ls_engine import run_ls_engine, SCRUTINY_REMARKS


def run_ls_for_company(company_name: str, fy: str, prev_year_path: str = None):
    """
    STEP 4 – Ledger Scrutiny Runner

    - Reads consolidated outputs
    - Runs LS Engine
    - Exports Excel report into analysis folder
    """

    consolidated_dir = paths.consolidated_dir(company_name, fy)
    analysis_dir = paths.analysis_dir(company_name, fy)

    analysis_dir.mkdir(parents=True, exist_ok=True)

    conso_master = consolidated_dir / "Conso_MasterData.csv"
    conso_ledgerview = consolidated_dir / "Conso_LedgerView.csv"

    if not conso_master.exists():
        return {
            "status": "warning",
            "message": (
                "Consolidated master data not found.\n\n"
                "Please ensure Step-2 (Consolidation) has been run "
                "or the required files exist in the company folder."
            )
        }

    # --- Run LS Engine ---
    # Load consolidated transactions for transaction-based reports
    txn_files = sorted(consolidated_dir.glob("Transactions_*.csv"))
    txn_path = txn_files[0] if txn_files else None
    print(f"DEBUG txn_path: {txn_path}")
    print(f"DEBUG txn_files: {txn_files}")

    # Group concern: pair each branch's previous-year extract with its current-year
    # extract -> branch-wise OB check (offsetting errors across branches can't hide).
    extracted_dir = paths.extracted_dir(company_name, fy)
    prev_branch_pairs = {}
    if extracted_dir.exists():
        # current-year branch extracts, keyed case-insensitively (typo tolerance)
        cy_files = {f.name[:-len("_MasterData.csv")].lower(): f
                    for f in extracted_dir.glob("*_MasterData.csv")
                    if not f.name.startswith("PrevYear_")}
        for pf in sorted(extracted_dir.glob("PrevYear_*_MasterData.csv")):
            branch = pf.name[len("PrevYear_"):-len("_MasterData.csv")]
            cf = cy_files.get(branch.lower())
            if cf is not None:
                prev_branch_pairs[branch] = (str(pf), str(cf))
            else:
                print(f"WARN: no current-year extract named '{branch}_MasterData.csv' — "
                      f"OB check skipped for this branch")
    # Branch-wise whenever ANY branch pair exists (each branch vs its own PY);
    # the classic consolidated/upload check only runs when there are no pairs.

    results = run_ls_engine(
        conso_masterdata_path=conso_master,
        conso_ledgerview_path=txn_path,
        prev_year_path=prev_year_path,
        prev_branch_pairs=prev_branch_pairs
    )

    output_file = analysis_dir / "Ledger_Scrutiny_Report.xlsx"

    with pd.ExcelWriter(output_file, engine="openpyxl") as writer:
        # Write data sheets first
        for sheet_name, df in results.items():
            safe_sheet = sheet_name[:31]
            df.to_excel(writer, sheet_name=safe_sheet, index=False)

        # Index sheet
        index_rows = []
        for idx, (sheet_name, df) in enumerate(results.items(), start=1):
            info = SCRUTINY_REMARKS.get(sheet_name, {})
            index_rows.append({
                'S.No'   : idx,
                'Sheet'  : sheet_name,
                'Title'  : info.get('title', sheet_name.replace('_', ' ')),
                'Rows'   : len(df),
                'Remarks': info.get('remarks', ''),
                'Action' : info.get('action', '')
            })
        pd.DataFrame(index_rows).to_excel(writer, sheet_name='Index', index=False)

    # Post-process — add hyperlinks and home buttons
    from openpyxl import load_workbook
    from openpyxl.styles import Font, PatternFill, Alignment
    from openpyxl.utils import get_column_letter

    wb = load_workbook(output_file)
    idx_ws = wb['Index']

    # Style Index headers
    header_fill = PatternFill(start_color='1F4E79', end_color='1F4E79', fill_type='solid')
    header_font = Font(bold=True, color='FFFFFF', name='Segoe UI')
    for cell in idx_ws[1]:
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal='center')

    # Add hyperlinks in Index — column B (Sheet name)
    link_font = Font(color='1F4E79', underline='single', name='Segoe UI')
    for row_idx, (sheet_name, df) in enumerate(results.items(), start=2):
        safe_sheet = sheet_name[:31]
        cell = idx_ws.cell(row=row_idx, column=2)
        if safe_sheet in wb.sheetnames:
            cell.hyperlink = f"#{safe_sheet}!A1"
            cell.font = link_font

    # Auto width Index
    for col in idx_ws.columns:
        max_len = max((len(str(c.value)) if c.value else 0) for c in col)
        idx_ws.column_dimensions[col[0].column_letter].width = min(max_len + 4, 60)

    # Move Index to first position
    wb.move_sheet('Index', offset=-len(wb.sheetnames)+1)

    # Add Home button on each sheet
    home_font = Font(color='FFFFFF', bold=True, name='Segoe UI', size=10)
    home_fill = PatternFill(start_color='1F4E79', end_color='1F4E79', fill_type='solid')
    for sheet_name in wb.sheetnames:
        if sheet_name == 'Index':
            continue
        ws = wb[sheet_name]
        # Insert row at top for home button
        ws.insert_rows(1)
        home_cell = ws['A1']
        home_cell.value = '🏠 Home'
        home_cell.hyperlink = '#Index!A1'
        home_cell.font = home_font
        home_cell.fill = home_fill
        home_cell.alignment = Alignment(horizontal='center')
        ws.row_dimensions[1].height = 20

    wb.save(output_file)

    return {
        "status": "success",
        "message": f"Ledger Scrutiny report generated:\n{output_file}"
    }
