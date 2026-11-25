# ================= FINAL CORRECTED SCRIPT =================
# Expense-wise TDS Analysis with Hyperlinked Index (openpyxl only)
# GUARANTEE:
# - No business logic changed
# - No xlsxwriter dependency
# - Winman PAN issue fixed
# - Existing reports untouched

import os
import re
import pandas as pd
import tds_rules_engine
import paths
import logging
from openpyxl.utils import get_column_letter

# -------------------------------------------------
# Logging
# -------------------------------------------------
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# -------------------------------------------------
# SHEET DESCRIPTIONS — Add new sheet description here
# when a new report is added in future
# -------------------------------------------------
SHEET_DESCRIPTIONS = {
    "Final_Merged_Report"     : "Expense wise analysis merged with TDS deductions and TDS rate",
    "TDS_Report_Master"       : "TDS deducted grouped by PAN and TDS Ledger — Hidden by default",
    "TDS_Party_PAN_Status"    : "All parties where TDS is deducted including missing PAN entries",
    "Winman_TDS_Register"     : "TDS deposited as per Winman — Hidden by default",
    "Purchase_Analysis"       : "Purchase transactions merged with TDS data",
    "Sales_Analysis"          : "Sales transactions pivot analysis",
    "Missing_PAN_Report"      : "Parties with missing PAN having expense transactions",
    "GST_Analysis"             : "GST ledger wise transactions with GST Group classification",
    "PAN_Wise_TDS_Summary": "PAN wise TDS deducted as per books vs deposited as per Winman",
    "Advanced_TDS_Report": "Party wise TDS section analysis with threshold and variance",
}

# -------------------------------------------------
# UI FUNCTIONS
# -------------------------------------------------

# -------------------------------------------------
# MAIN PROCESS
# -------------------------------------------------
def main(selected_reports: list, input_files: list, winman_file: str,
         company_name: str = None, fy: str = None, selected_expenses: list = None,
         selected_tds_ledgers: list = None, excluded_parties: list = None,
         selected_gst_ledgers: list = None):
    try:
        if not selected_reports:
            raise ValueError("No reports selected")
        if not input_files:
            raise ValueError("No input CSV files provided")
        # Winman holds the TDS actually deposited — only the TDS comparison in
        # Final_Merged_Report uses it. GST / Purchase / Sales analyses don't.
        needs_winman = "Final_Merged_Report" in selected_reports
        if needs_winman and not winman_file:
            raise ValueError("No Winman file provided")

        
        # ---- DERIVE COMPANY FOLDER FROM INPUT FILE ----
        if company_name:
            analysis_dir = str(paths.analysis_dir(company_name, fy))
        else:
            first_file = input_files[0]
            exports_dir = os.path.dirname(first_file)
            company_dir = os.path.dirname(exports_dir)
            analysis_dir = os.path.join(company_dir, "analysis")

        os.makedirs(analysis_dir, exist_ok=True)

        from datetime import datetime
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_file = os.path.join(
            analysis_dir,
            f"TDS_&Expense_Analysis_{timestamp}.xlsx"
        )

        data = pd.concat([pd.read_csv(f) for f in input_files], ignore_index=True)
        # Tally can return column names in a different case run to run
        # (e.g. $vouchertypename) — normalise before the required-column check.
        from engines.extract_engine import normalize_txn_columns
        data = normalize_txn_columns(data)

        required_columns = [
            '$VoucherTypeName', '$Particulars', '$Amount', '$Led_Parent',
            '$Led_Group', '$Party_LedName', '$Led_PAN'
        ]
        if not all(c in data.columns for c in required_columns):
            raise ValueError("Missing required columns in CSV")

        # ── Layer 3: Apply PAN Override if exists ─────────────────────────────
        pan_override_path = str(paths.analysis_dir(company_name, fy) / "PAN_Override.xlsx")
        if company_name and os.path.exists(pan_override_path):
            print("✅ PAN Override file found — applying...")
            pan_override_df = pd.read_excel(pan_override_path)
            pan_override_df = pan_override_df[['Party Name', 'PAN']].dropna(subset=['PAN'])
            pan_override_df['Party Name'] = pan_override_df['Party Name'].astype(str).str.strip()
            pan_override_df['PAN'] = pan_override_df['PAN'].astype(str).str.strip()
            pan_override_map = pan_override_df.set_index('Party Name')['PAN'].to_dict()

            def apply_pan_override(row):
                if pd.isna(row['$Led_PAN']) or str(row['$Led_PAN']).strip() == '':
                    party = str(row['$Party_LedName']).strip()
                    return pan_override_map.get(party, row['$Led_PAN'])
                return row['$Led_PAN']

            data['$Led_PAN'] = data.apply(apply_pan_override, axis=1)
            print(f"✅ PAN Override applied for {len(pan_override_map)} parties.")
        else:
            print("ℹ️ No PAN Override file found — skipping.")
            
        # ── Auto fill PAN from GSTIN if PAN missing ───────────────────────────
        def extract_pan_from_gstin(row):
            pan = str(row['$Led_PAN']).strip()
            gstin = str(row['$Led_GSTIN']).strip()
            if pan in ['', 'nan', 'None', 'Missing'] and len(gstin) == 15:
                return gstin[2:12]
            return row['$Led_PAN']

        data['$Led_PAN'] = data.apply(extract_pan_from_gstin, axis=1)
        print("✅ PAN auto-filled from GSTIN where missing.")

        # -------------------------------------------------
        # TDS REPORT MASTER
        # -------------------------------------------------
        if True:  # TDS Report Master always runs
            # ── TDS Ledger filter — dynamic ───────────────────────────────
            tds_mask = (
                data['$Led_BaseGroup'] == 'Duties & Taxes'
            )

            if selected_tds_ledgers:
                tds_mask &= data['$Particulars'].isin(selected_tds_ledgers)

            if excluded_parties:
                exclude_pattern = '|'.join([re.escape(p) for p in excluded_parties])
                tds_mask &= ~data['$Party_LedName'].str.contains(
                    exclude_pattern, case=False, na=False
                )

            # All TDS rows including missing PAN — for TDS_Party_PAN_Status
            tds_filtered_all = data.loc[tds_mask].copy()

            # Only valid PANs — for TDS Report Master, Final Merged, Expense Wise
            tds_filtered_data = tds_filtered_all[
                tds_filtered_all['$Led_PAN'].notna() &
                (tds_filtered_all['$Led_PAN'].astype(str).str.strip() != '') 
            ].fillna('Missing')

            tds_filtered_data['TDS Ledger'] = (
                tds_filtered_data.groupby('$Led_PAN')['$Particulars']
                .transform(lambda x: ' & '.join(x.dropna().unique()))
            )

            tds_report_master = (
                tds_filtered_data
                .groupby(['$Led_PAN', 'TDS Ledger'], as_index=False)
                .agg({'$Amount': 'sum'})
            )
            tds_report_master.rename(columns={'$Amount': 'TDSAmount'}, inplace=True)

        # -------------------------------------------------
        # FINAL MERGED REPORT (EXPENSE BASE)
        # -------------------------------------------------
        if "Final_Merged_Report" in selected_reports:
            tds_expense_analysis = data.loc[
                data['$Led_BaseGroup'].isin(['Direct Expenses', 'Indirect Expenses'])
            ].copy()

            unique_expenses = sorted(tds_expense_analysis['$Particulars'].dropna().unique())

            if selected_expenses:
                tds_expense_analysis = tds_expense_analysis[
                    tds_expense_analysis['$Particulars'].isin(selected_expenses)
                ]

            grouping_columns = ['$Led_Group', '$Led_BaseGroup', '$Particulars', '$Led_Parent', '$Party_LedName', '$Led_PAN']
            tds_expense_analysis[grouping_columns] = tds_expense_analysis[grouping_columns].fillna('Missing')

            tds_expense_analysis = (
                tds_expense_analysis
                .groupby(grouping_columns, as_index=False)
                .agg({'$Amount': 'sum'})
            )
            tds_expense_analysis.rename(columns={'$Amount': 'ExpenseAmount'}, inplace=True)
            tds_expense_analysis['ExpenseAmount'] *= -1

            merged_data = tds_expense_analysis.merge(
                tds_report_master[['$Led_PAN', 'TDSAmount', 'TDS Ledger']],
                on='$Led_PAN',
                how='left'
            )
                    # Ensure numeric safety
            merged_data['TDSAmount'] = pd.to_numeric(
                merged_data['TDSAmount'], errors='coerce'
            ).fillna(0)
            
            merged_data['ExpenseAmount'] = pd.to_numeric(
                merged_data['ExpenseAmount'], errors='coerce'
            ).fillna(0)
            
            # --- NEW COLUMN: TDS Rate ---
            merged_data['TDS Rate'] = (
                merged_data['TDSAmount'] / merged_data['ExpenseAmount'].abs()
            )
            
            # Handle division by zero
            merged_data['TDS Rate'] = merged_data['TDS Rate'].replace([float('inf'), -float('inf')], 0).fillna(0)
            
            # --- Reorder columns to place TDS Rate after TDSAmount ---
            cols = list(merged_data.columns)
            tds_amt_index = cols.index('TDSAmount')
            cols.insert(tds_amt_index + 1, cols.pop(cols.index('TDS Rate')))
            merged_data = merged_data[cols]


        # -------------------------------------------------
        # WINMAN DEDUCTION DATA (PAN FIXED) — loaded only when the TDS
        # comparison (Final_Merged_Report) is being produced.
        grouped_winman_data = pd.DataFrame(
            columns=["PAN", "Name", "TDS_Deposited", "Section"])
        if needs_winman:
            sheet_data = pd.read_excel(winman_file, sheet_name="Deduction", skiprows=3)

            if len(sheet_data.columns) == 4:
                sheet_data.columns = [
                    'PAN', 'Name', 'Total Tax - deducted and deposited', 'Section'
                ]
            elif len(sheet_data.columns) >= 18:
                # Handle 18 or 19 columns — use position based
                cols = [
                    "Challan ID", "Name", "PAN", "Type of Deductee",
                    "PAN validation result", "PAN Status",
                    "Amount Paid / Credited", "Paid / Credited Date",
                    "Cash withdrawal exceeding limit", "Deduction Date",
                    "Deducted and deposited - Tax",
                    "Total Tax - deducted and deposited",
                    "Deduction Rate", "Reason for Lower/Higher Deduction",
                    "Certificate number u/s 197", "Section",
                    "194N Deduction Type", "Shortfall/Excess (-)"
                ]
                sheet_data = sheet_data.iloc[:, :18]
                sheet_data.columns = cols
            else:
                raise ValueError(
                    f"Winman file has {len(sheet_data.columns)} columns. "
                    "Expected 4 (manual template) or 18+ (Winman export)."
                )
            sheet_data = sheet_data.astype(str).fillna("null")
            sheet_data["Total Tax - deducted and deposited"] = pd.to_numeric(
                sheet_data["Total Tax - deducted and deposited"], errors="coerce"
            ).fillna(0)
            sheet_data["PAN"] = sheet_data["PAN"].str.replace(" ", "")
            grouped_winman_data = (
                sheet_data[["PAN", "Name", "Total Tax - deducted and deposited", "Section"]]
                .groupby(["PAN", "Name"], as_index=False)
                .agg(
                    TDS_Deposited=("Total Tax - deducted and deposited", "sum"),
                    Section=("Section", lambda x: " & ".join(sorted(set(x))))
                )
            )

        # ── PAN Wise TDS Summary ──────────────────────────────────────────────
        if "Final_Merged_Report" in selected_reports:

            # All TDS rows including missing PAN
            tds_all = tds_filtered_all.copy()
            tds_all['$Led_PAN'] = tds_all['$Led_PAN'].astype(str).str.strip()
            tds_all['$Led_PAN'] = tds_all['$Led_PAN'].replace(
                ['', 'nan', 'None', 'Missing'], 'NO_PAN')

            # Rows with valid PAN — group and concat party names
            has_pan = tds_all[tds_all['$Led_PAN'] != 'NO_PAN']
            tds_with_pan = (
                has_pan
                .groupby('$Led_PAN', as_index=False)
                .agg(
                    Party_Names=('$Party_LedName',
                        lambda x: ' | '.join(sorted(set(
                            str(v).strip() for v in x
                            if str(v).strip() not in ['','nan','None']
                        )))),
                    TDS_Ledgers=('$Particulars',
                        lambda x: ' | '.join(sorted(set(
                            str(v).strip() for v in x
                            if str(v).strip() not in ['','nan','None']
                        )))),
                    TDS_Books=('$Amount', 'sum')
                )
            )

            # Rows with no PAN — keep individual, no grouping
            no_pan = tds_all[tds_all['$Led_PAN'] == 'NO_PAN'].copy()
            tds_no_pan = (
                no_pan
                .groupby('$Party_LedName', as_index=False)
                .agg(
                    TDS_Ledgers=('$Particulars',
                        lambda x: ' | '.join(sorted(set(
                            str(v).strip() for v in x
                            if str(v).strip() not in ['','nan','None']
                        )))),
                    TDS_Books=('$Amount', 'sum')
                )
                .rename(columns={'$Party_LedName': 'Party_Names'})
            )
            tds_no_pan['$Led_PAN'] = 'NO_PAN'

            tds_books = pd.concat(
                [tds_with_pan, tds_no_pan], ignore_index=True)

            # Outer join with Winman
            pan_wise = tds_books.merge(
                grouped_winman_data[['PAN','Name','TDS_Deposited','Section']],
                left_on='$Led_PAN',
                right_on='PAN',
                how='outer'
            )
            pan_wise['$Led_PAN']      = pan_wise['$Led_PAN'].fillna(pan_wise['PAN'])
            pan_wise['TDS_Books']     = pd.to_numeric(pan_wise['TDS_Books'], errors='coerce').fillna(0)
            pan_wise['TDS_Deposited'] = pd.to_numeric(pan_wise['TDS_Deposited'], errors='coerce').fillna(0)
            pan_wise['Difference']    = pan_wise['TDS_Deposited'] - pan_wise['TDS_Books']
            pan_wise['Status']        = pan_wise['Difference'].apply(
                lambda x: 'Short' if x < 0 else ('Excess' if x > 0 else 'OK')
            )
            pan_wise['Source']        = pan_wise.apply(
                lambda r: 'Both' if r['TDS_Books'] != 0 and r['TDS_Deposited'] != 0
                else ('Books Only' if r['TDS_Books'] != 0 else 'Winman Only'), axis=1
            )
            pan_wise = pan_wise[[
                '$Led_PAN', 'Party_Names', 'Name',
                'TDS_Ledgers', 'Section',
                'TDS_Books', 'TDS_Deposited',
                'Difference', 'Status', 'Source'
            ]].rename(columns={
                '$Led_PAN'   : 'PAN',
                'Party_Names': 'Party Name (Books)',
                'Name'       : 'Party Name (Winman)',
                'TDS_Ledgers': 'TDS Ledger',
                'TDS_Books'  : 'TDS Books',
                'TDS_Deposited': 'TDS Winman'
            })

            # NO_PAN rows — source always Books Only
            pan_wise.loc[
                pan_wise['PAN'] == 'NO_PAN', 'Source'] = 'Books Only - No PAN'

        # ── Merge Winman with Final Merged — only when selected ───────────────
        if "Final_Merged_Report" in selected_reports:
            merged_data = merged_data.merge(
                grouped_winman_data,
                left_on="$Led_PAN",
                right_on="PAN",
                how="left"
            )
            merged_data['TDSAmount'] = pd.to_numeric(
                merged_data['TDSAmount'], errors='coerce'
            ).fillna(0)
            merged_data['TDS_Deposited'] = pd.to_numeric(
                merged_data['TDS_Deposited'], errors='coerce'
            ).fillna(0)
            merged_data['Difference in TDS'] = (
                merged_data['TDS_Deposited'] - merged_data['TDSAmount']
            )

         # Step 4: Purchase Analysis (New Report)
        if "Purchase_Analysis" in selected_reports:
            purchase_analysis = data.loc[data['$Led_BaseGroup'] == 'Purchase Accounts'].copy()
            purchase_analysis['$Led_PAN'] = purchase_analysis['$Led_PAN'].fillna("")
            purchase_analysis['$Party_LedName'] = purchase_analysis['$Party_LedName'].fillna("")
            
            # Fill blank "$Led_PAN" with respective "PartyLedgerName"
            purchase_analysis['$Led_PAN'] = purchase_analysis.apply(
                lambda row: row['$Party_LedName'] if row['$Led_PAN'] == "null" else row['$Led_PAN'], axis=1
            )
            
            # Concatenate "$Party_LedName" for each "$Led_PAN"
            purchase_analysis["PartyLedgerName"] = (
                purchase_analysis.groupby('$Led_PAN')['$Party_LedName']
                .transform(lambda x: ' & '.join(x.dropna().unique()))
            )
            purchase_analysis.drop(columns=['$Party_LedName'], inplace=True)

            # Group by "PartyLedgerName", "$Led_PAN", "$Particulars" and sum "$Amount"
            purchase_analysis_summary = (
                purchase_analysis
                .groupby(["PartyLedgerName", "$Led_PAN", "$Particulars"], as_index=False)
                .agg({'$Amount': 'sum'})
            )
            purchase_analysis_summary['$Amount'] *= -1
            purchase_analysis_summary.rename(columns={'$Amount': 'PurchaseAmount'}, inplace=True)
            
            

            # Merge Purchase Analysis with TDS Report Master (Including TDSAmount & TDS Ledger)
            purchase_analysis_merged = purchase_analysis_summary.merge(
                tds_report_master[['$Led_PAN', 'TDSAmount', 'TDS Ledger']],
                on='$Led_PAN',
                how='left'
            )

            # Step 5: Sales Analysis (New Report)
        if "Sales_Analysis" in selected_reports:  
            sales_analysis = data.loc[data['$Led_BaseGroup'] == 'Sales Accounts'].copy()
            sales_analysis['$Led_PAN'] = sales_analysis['$Led_PAN'].fillna("null")
            sales_analysis['$Party_LedName'] = sales_analysis['$Party_LedName'].fillna("null")

            # Fill blank "$Led_PAN" with respective "PartyLedgerName"
            sales_analysis['$Led_PAN'] = sales_analysis.apply(
                lambda row: row['$Party_LedName'] if row['$Led_PAN'] == "null" else row['$Led_PAN'], axis=1
            )

            # Concatenate "$Party_LedName" for each "$Led_PAN"
            sales_analysis["PartyLedgerName"] = (
                sales_analysis.groupby('$Led_PAN')['$Party_LedName']
                .transform(lambda x: ' & '.join(x.dropna().unique()))
            )
            sales_analysis.drop(columns=['$Party_LedName'], inplace=True)


            # Group by "PartyLedgerName", "$Led_PAN", "$VchTypeParent" and sum "$Amount"
            sales_analysis_summary = (
                sales_analysis
                .groupby(["PartyLedgerName", "$Led_PAN", "$VchTypeParent"], as_index=False)
                .agg({'$Amount': 'sum'})
            )
            sales_analysis_summary.rename(columns={'$Amount': 'SalesAmount'}, inplace=True)

            # Pivot "$VoucherTypeName" and sum "$Amount"
            sales_pivot = sales_analysis_summary.pivot_table(
                index=["PartyLedgerName", "$Led_PAN"], 
                columns="$VchTypeParent", 
                values="SalesAmount", 
                aggfunc="sum", 
                fill_value=0
            ).reset_index() 
        # -------------------------------------------------

        # ── Layer 1: Missing PAN Report ───────────────────────────────────────
        PARTY_GROUPS_PAN = {'Sundry Debtors', 'Sundry Creditors'}
        EXPENSE_GROUPS = {'Direct Expenses', 'Indirect Expenses'}

        # Get party-wise primary group mapping
        party_group_map = (
            data[data['$Led_BaseGroup'].isin(PARTY_GROUPS_PAN)]
            [['$Party_LedName', '$Led_Group']]
            .drop_duplicates()
            .rename(columns={
                '$Party_LedName': 'Party Name',
                '$Led_Group': 'Primary Group'
            })
        )

        # Get expense rows with missing PAN
        EXCLUDE_PARTY_GROUPS = {'Bank Accounts', 'Cash-in-Hand', 'Bank OD Accounts'}
        missing_pan_df = data[
            (data['$Led_Group'].isin(EXPENSE_GROUPS)) &
            (data['$Party_LedName'].notna()) &
            (data['$Party_LedName'] != '') &
            (~data['$Led_BaseGroup'].isin(EXCLUDE_PARTY_GROUPS)) &
            (
                data['$Led_PAN'].isna() |
                (data['$Led_PAN'].astype(str).str.strip() == '') |
                (data['$Led_PAN'].astype(str).str.strip() == 'nan')
            )
        ].copy()

        if not missing_pan_df.empty:
            # Group by Party Name and Expense Head
            missing_pan_summary = (
                missing_pan_df
                .groupby(['$Party_LedName', '$Particulars'], as_index=False)
                .agg({'$Amount': 'sum'})
                .rename(columns={
                    '$Party_LedName': 'Party Name',
                    '$Particulars': 'Expense Head',
                    '$Amount': 'Expense Amount'
                })
            )

            # Merge Primary Group
            missing_pan_summary = missing_pan_summary.merge(
                party_group_map,
                on='Party Name',
                how='left'
            )

            # Add blank PAN column
            missing_pan_summary['PAN'] = ''

            # Final column order
            # Add TDS amount for missing PAN parties
            tds_for_missing = (
                tds_filtered_all[
                    tds_filtered_all['$Party_LedName'].isin(missing_pan_summary['Party Name'])
                ]
                .groupby('$Party_LedName', as_index=False)['$Amount']
                .sum()
                .rename(columns={'$Party_LedName': 'Party Name', '$Amount': 'TDS Amount'})
            )
            missing_pan_summary = missing_pan_summary.merge(
                tds_for_missing, on='Party Name', how='left')
            missing_pan_summary['TDS Amount'] = pd.to_numeric(
                missing_pan_summary['TDS Amount'], errors='coerce').fillna(0)
            missing_pan_summary = missing_pan_summary[[
                'Party Name', 'Primary Group',
                'Expense Head', 'Expense Amount', 'TDS Amount', 'PAN'
            ]].sort_values('Expense Amount', ascending=True)

            # ── Layer 2: Save PAN Override Excel ─────────────────────────────
            pan_override_output = os.path.join(
                analysis_dir, "PAN_Override.xlsx"
            )
            # One row per party (expense heads collapsed -> no duplicate parties).
            # TDS-deducted parties first (PAN most critical there), then by
            # total expense amount, higher to lower.
            pan_override_export = (
                missing_pan_summary
                .groupby('Party Name', as_index=False)
                .agg({'Expense Amount': 'sum', 'TDS Amount': 'first'})
            )
            pan_override_export['PAN'] = ''
            pan_override_export['_tds'] = pan_override_export['TDS Amount'].abs()
            pan_override_export = (
                pan_override_export
                .sort_values(['_tds', 'Expense Amount'],
                             ascending=[False, False],
                             key=lambda s: s.abs())
                .drop(columns=['_tds'])
            )[['Party Name', 'Expense Amount', 'TDS Amount', 'PAN']]

            with pd.ExcelWriter(pan_override_output, engine='openpyxl') as override_writer:
                pan_override_export.to_excel(
                    override_writer,
                    sheet_name='PAN Override',
                    index=False
                )
                # Style the sheet
                ws = override_writer.sheets['PAN Override']
                from openpyxl.styles import Font, PatternFill, Alignment
                header_font = Font(bold=True, color='FFFFFF')
                header_fill = PatternFill(
                    start_color='1F4E79',
                    end_color='1F4E79',
                    fill_type='solid'
                )
                pan_fill = PatternFill(
                    start_color='FFF2CC',
                    end_color='FFF2CC',
                    fill_type='solid'
                )
                for cell in ws[1]:
                    cell.font = header_font
                    cell.fill = header_fill
                    cell.alignment = Alignment(horizontal='center')

                # Highlight PAN column yellow
                pan_col_idx = 4
                for row in ws.iter_rows(min_row=2, min_col=pan_col_idx, max_col=pan_col_idx):
                    for cell in row:
                        cell.fill = pan_fill

                # Auto column width
                for col in ws.columns:
                    max_len = max(
                        (len(str(cell.value)) if cell.value else 0)
                        for cell in col
                    )
                    ws.column_dimensions[col[0].column_letter].width = min(max_len + 4, 50)

            print(f"✅ PAN Override Excel saved: {pan_override_output}")
        else:
            missing_pan_summary = pd.DataFrame()
            print("ℹ️ No missing PANs found.")
# ── GST Analysis ──────────────────────────────────────────────────────
        if "GST_Analysis" in selected_reports and selected_gst_ledgers:
            from gst_engine import get_gst_group
            gst_df = data[
                (data['$Led_BaseGroup'] == 'Duties & Taxes') &
                (data['$Particulars'].isin(selected_gst_ledgers))
            ].copy()
            gst_df['GST_Group'] = gst_df['$Particulars'].apply(get_gst_group)
            
# ── Apply TDS Rules ───────────────────────────────────────────────────
        if "Final_Merged_Report" in selected_reports:
            expense_ledgers = merged_data['$Particulars'].dropna().unique().tolist()
            rules = tds_rules_engine.get_effective_rules(company_name, fy, expense_ledgers)
            merged_data = tds_rules_engine.apply_rules_to_df(merged_data, rules)
            advanced_tds = tds_rules_engine.build_advanced_tds_report(merged_data, rules)
            
        with pd.ExcelWriter(output_file, engine='openpyxl') as writer:

            if "Final_Merged_Report" in selected_reports:
                merged_data.to_excel(writer, sheet_name="Final_Merged_Report", index=False)
                
            if "Final_Merged_Report" in selected_reports and not advanced_tds.empty:
                advanced_tds.to_excel(writer, sheet_name="Advanced_TDS_Report", index=False)

            if True:  # Always write TDS Report Master
                tds_report_master.to_excel(writer, sheet_name="TDS_Report_Master", index=False)

                # ── TDS Party PAN Status — auto generated with TDS Report Master ──
                tds_party_pan = (
                    tds_filtered_all
                    .groupby(
                        ['$Party_LedName', '$Led_Group', '$Particulars', '$Led_PAN'],
                        as_index=False,
                        dropna=False
                    )
                    .agg({'$Amount': 'sum'})
                )
                tds_party_pan.rename(columns={
                    '$Party_LedName': 'Party Name',
                    '$Led_Group'    : 'Primary Group',
                    '$Particulars'  : 'TDS Ledger',
                    '$Led_PAN'      : 'PAN',
                    '$Amount'       : 'TDS Amount'
                }, inplace=True)

                # Get party primary group from main data
                party_group = (
                    data[data['$Led_BaseGroup'].isin(['Sundry Debtors', 'Sundry Creditors'])]
                    [['$Party_LedName', '$Led_Group']]
                    .drop_duplicates()
                    .rename(columns={
                        '$Party_LedName': 'Party Name',
                        '$Led_Group'    : 'Primary Group'
                    })
                )

                tds_party_pan = tds_party_pan.drop(columns=['Primary Group']).merge(
                    party_group,
                    on='Party Name',
                    how='left'
                )

                tds_party_pan = tds_party_pan[[
                    'Party Name', 'Primary Group',
                    'TDS Ledger', 'TDS Amount', 'PAN'
                ]]

                tds_party_pan['PAN'] = tds_party_pan['PAN'].replace('Missing', '')

                tds_party_pan.to_excel(
                    writer,
                    sheet_name="TDS_Party_PAN_Status",
                    index=False
                )

            if True:  # Winman always runs
                grouped_winman_data.to_excel(writer, sheet_name="Winman_TDS_Register", index=False)
                
            if "Purchase_Analysis" in selected_reports:
                purchase_analysis_merged.to_excel(writer, sheet_name="Purchase_Analysis", index=False)

            if "Sales_Analysis" in selected_reports:
                sales_pivot.to_excel(writer, sheet_name="Sales_Analysis", index=False)
            
            if "GST_Analysis" in selected_reports and selected_gst_ledgers:
                gst_df.to_excel(writer, sheet_name="GST_Analysis", index=False)
                
            if "Final_Merged_Report" in selected_reports:
                pan_wise.to_excel(
                    writer, sheet_name="PAN_Wise_TDS_Summary", index=False)
            
            # Always write Missing PAN report
            if not missing_pan_summary.empty:
                missing_pan_summary.to_excel(
                    writer, sheet_name="Missing_PAN_Report", index=False
                )

            # (Expense_Wise_TDS_Analysis sheet removed — superseded by the TDS
            # Compliance Report Builder.)

        # ── Hide sheets after writing ─────────────────────────────────────────
        from openpyxl import load_workbook
        from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
        
        wb = load_workbook(output_file)

        for sheet_to_hide in ['Winman_TDS_Register']:
            if sheet_to_hide in wb.sheetnames:
                wb[sheet_to_hide].sheet_state = 'hidden'

        # ── Dynamic Index Sheet ───────────────────────────────────────────────
        # Remove existing index if present
        if "Index" in wb.sheetnames:
            del wb["Index"]

        # Create Index as first sheet
        idx_ws = wb.create_sheet("Index", 0)

        # Styles
        title_font   = Font(name='Segoe UI', size=16, bold=True, color='FFFFFF')
        header_font  = Font(name='Segoe UI', size=11, bold=True, color='FFFFFF')
        link_font    = Font(name='Segoe UI', size=11, color='1F4E79', underline='single')
        normal_font  = Font(name='Segoe UI', size=11)
        hidden_font  = Font(name='Segoe UI', size=11, color='999999', italic=True)

        title_fill  = PatternFill(start_color='1F4E79', end_color='1F4E79', fill_type='solid')
        header_fill = PatternFill(start_color='2E75B6', end_color='2E75B6', fill_type='solid')
        alt_fill    = PatternFill(start_color='EBF3FB', end_color='EBF3FB', fill_type='solid')

        thin = Side(style='thin', color='C5D8EC')
        border = Border(left=thin, right=thin, top=thin, bottom=thin)

        center = Alignment(horizontal='center', vertical='center')
        left   = Alignment(horizontal='left', vertical='center', wrap_text=True)

        # Title row
        idx_ws.merge_cells('A1:D1')
        title_cell = idx_ws['A1']
        title_cell.value = "📊  TDS & Expense Analysis — Report Index"
        title_cell.font = title_font
        title_cell.fill = title_fill
        title_cell.alignment = center
        idx_ws.row_dimensions[1].height = 36

        # Header row
        headers = ['#', 'Report Name', 'Description', 'Status']
        header_widths = [5, 30, 55, 12]
        for col_idx, (header, width) in enumerate(zip(headers, header_widths), start=1):
            cell = idx_ws.cell(row=2, column=col_idx)
            cell.value = header
            cell.font = header_font
            cell.fill = header_fill
            cell.alignment = center
            cell.border = border
            idx_ws.column_dimensions[get_column_letter(col_idx)].width = width
        idx_ws.row_dimensions[2].height = 22

        # Data rows — dynamic from workbook sheets
        data_row = 3
        serial = 1
        for sheet_name in wb.sheetnames:
            if sheet_name == "Index":
                continue

            is_hidden = wb[sheet_name].sheet_state == 'hidden'
            status    = "Hidden" if is_hidden else "Visible"
            desc      = SHEET_DESCRIPTIONS.get(sheet_name, "—")
            row_fill  = alt_fill if data_row % 2 == 0 else None

            # Serial number
            cell_sr = idx_ws.cell(row=data_row, column=1)
            cell_sr.value = serial
            cell_sr.font = normal_font
            cell_sr.alignment = center
            cell_sr.border = border
            if row_fill:
                cell_sr.fill = row_fill

            # Report Name — hyperlink
            cell_name = idx_ws.cell(row=data_row, column=2)
            cell_name.value = sheet_name
            cell_name.font = link_font if not is_hidden else hidden_font
            cell_name.hyperlink = f"#{sheet_name}!A1"
            cell_name.alignment = left
            cell_name.border = border
            if row_fill:
                cell_name.fill = row_fill

            # Description
            cell_desc = idx_ws.cell(row=data_row, column=3)
            cell_desc.value = desc
            cell_desc.font = hidden_font if is_hidden else normal_font
            cell_desc.alignment = left
            cell_desc.border = border
            if row_fill:
                cell_desc.fill = row_fill

            # Status
            cell_status = idx_ws.cell(row=data_row, column=4)
            cell_status.value = status
            cell_status.font = Font(
                name='Segoe UI', size=11,
                color='2E7D32' if not is_hidden else '999999',
                bold=True
            )
            cell_status.alignment = center
            cell_status.border = border
            if row_fill:
                cell_status.fill = row_fill

            idx_ws.row_dimensions[data_row].height = 20
            data_row += 1
            serial += 1

        # Freeze header rows
        idx_ws.freeze_panes = idx_ws['A3']

        import company_info as ci
        ci.save_analysis_info(company_name, fy, selected_reports)        
        wb.save(output_file)
        print("✅ Index sheet generated successfully.")

    except Exception as e:
        import traceback
        logging.error(f"Error: {e}")
        logging.error(traceback.format_exc())
        raise


def create_winman_template() -> bytes:
    import io
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Alignment
    wb = Workbook()
    ws = wb.active
    ws.title = "Deduction"
    ws.append([])
    ws.append([])
    ws.append([])
    headers = ['PAN', 'Name', 'Total Tax - deducted and deposited', 'Section']
    ws.append(headers)
    header_fill = PatternFill(start_color='1F4E79', end_color='1F4E79', fill_type='solid')
    header_font = Font(bold=True, color='FFFFFF', name='Segoe UI')
    for cell in ws[4]:
        cell.fill      = header_fill
        cell.font      = header_font
        cell.alignment = Alignment(horizontal='center')
    ws.append(['ABCDE1234F', 'Party Name', 10000, '194C'])
    ws.column_dimensions['A'].width = 15
    ws.column_dimensions['B'].width = 30
    ws.column_dimensions['C'].width = 35
    ws.column_dimensions['D'].width = 10
    out = io.BytesIO()
    wb.save(out)
    out.seek(0)
    return out.read()
	