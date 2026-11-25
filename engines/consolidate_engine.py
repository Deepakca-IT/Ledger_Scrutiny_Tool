import os
import pandas as pd
from datetime import datetime
import paths


def get_branch_name(filename):
    """
    Extracts branch name from filename.
    Example: Bangalore_Transactions.csv → Bangalore
    """
    return filename.split('_')[0]


def load_master_data(folder_path):
    """
    Loads branch-wise MasterData files into a dictionary.
    Key = Branch Name
    """
    master_data = {}
    all_files = [f for f in os.listdir(folder_path) if f.endswith("_MasterData.csv")]

    for file in all_files:
        branch_name = get_branch_name(file)
        file_path = os.path.join(folder_path, file)
        try:
            df = pd.read_csv(file_path)
            if '$Name' in df.columns and '$IncomeTaxNumber' in df.columns:
                master_data[branch_name] = df[['$Name', '$IncomeTaxNumber']]
            else:
                print(f"Skipping {file} – required columns missing.")
        except Exception as e:
            print(f"Error reading {file}: {e}")

    return master_data


def consolidate_files(folder_path, file_suffix, master_data=None):
    """
    Consolidates branch-wise CSV files.
    Adds Branch column.
    Optionally merges IncomeTaxNumber from MasterData.
    """
    all_files = [f for f in os.listdir(folder_path) if f.endswith(f"_{file_suffix}.csv")]

    if not all_files:
        print(f"No {file_suffix} files found.")
        return None

    consolidated = []

    for file in all_files:
        branch_name = get_branch_name(file)
        file_path = os.path.join(folder_path, file)

        try:
            df = pd.read_csv(file_path)
            df.insert(0, 'Branch', branch_name)

            if master_data and branch_name in master_data:
                df = df.merge(
                    master_data[branch_name],
                    left_on='$PartyLedgerName',
                    right_on='$Name',
                    how='left'
                )
                df.drop(columns=['$Name'], inplace=True)

            consolidated.append(df)

        except Exception as e:
            print(f"Error processing {file}: {e}")

    return pd.concat(consolidated, ignore_index=True) if consolidated else None


def save_large_transactions(df, output_folder):
    """
    Splits Transactions if rows exceed Excel limit.
    """
    max_rows = 1_048_576
    log_entries = []

    total_rows = len(df)
    parts = (total_rows // max_rows) + 1

    for i in range(parts):
        chunk = df.iloc[i * max_rows:(i + 1) * max_rows]
        if chunk.empty:
            continue

        filename = f"Transactions_{i + 1}.csv"
        path = os.path.join(output_folder, filename)
        chunk.to_csv(path, index=False)
        log_entries.append((filename, len(chunk)))

        print(f"Saved {filename} with {len(chunk)} rows.")

    return log_entries


def save_log(output_folder, log_entries):
    """
    Saves consolidation log file.
    """
    log_path = os.path.join(output_folder, "Export_Log.txt")
    with open(log_path, 'w') as f:
        f.write(f"Export Date: {datetime.now()}\n")
        f.write("File Name, Number of Rows\n")
        for name, count in log_entries:
            f.write(f"{name}, {count}\n")

    print(f"Log saved at {log_path}")


def main(company_name: str, fy: str):
    """
    STEP-2 – CONSOLIDATION ENGINE
    """

    if not company_name:
        raise ValueError("Company name is required")

    input_folder = str(paths.extracted_dir(company_name, fy))
    output_folder = str(paths.consolidated_dir(company_name, fy))

    if not os.path.exists(input_folder):
        raise FileNotFoundError("No extracted data found for this company")

    os.makedirs(output_folder, exist_ok=True)

    # Load MasterData per branch
    master_data = load_master_data(input_folder)

    # Consolidate MasterData
    master_df = consolidate_files(input_folder, "MasterData")
    if master_df is not None:        
        master_df.to_csv(
            os.path.join(output_folder, "Conso_MasterData.csv"),
            index=False
        )
        print("Consolidated MasterData saved.")

    # Consolidate Transactions
    txn_df = consolidate_files(input_folder, "Transactions", master_data)
    if txn_df is not None:
        log_entries = save_large_transactions(txn_df, output_folder)
        save_log(output_folder, log_entries)
    
    # Consolidate LedgerView
    ledger_view_df = consolidate_files(input_folder, "LedgerView", master_data)
    if ledger_view_df is not None:
        ledger_view_df.to_csv(
            os.path.join(output_folder, "Conso_LedgerView.csv"),
            index=False
        )
        print("Consolidated LedgerView saved.")
        
        # ── Extract filter options ────────────────────────────────────────────────
    if txn_df is not None:
        try:
            filter_cols = [
                '$Particulars', '$Led_BaseGroup',
                '$Party_LedName', '$Led_Group'
            ]
            available = [c for c in filter_cols if c in txn_df.columns]
            filt = txn_df[available].copy()

            import json
            filter_options = {
                "tds_ledgers": sorted(filt[
                    filt['$Led_BaseGroup'] == 'Duties & Taxes'
                ]['$Particulars'].dropna().unique().tolist()),
                "party_names": sorted(
                    filt['$Party_LedName'].dropna().unique().tolist()),
                "expenses": sorted(filt[
                    filt['$Led_BaseGroup'].isin([
                        'Direct Expenses', 'Indirect Expenses'])
                ]['$Particulars'].dropna().unique().tolist()),
                "gst_ledgers": sorted(filt[
                    filt['$Led_BaseGroup'] == 'Duties & Taxes'
                ]['$Particulars'].dropna().unique().tolist())
            }

            filter_path = os.path.join(
                output_folder, "Filter_Options.json")
            with open(filter_path, 'w') as f:
                json.dump(filter_options, f)
            print("✅ Filter options saved.")

            # Save related party eligible ledgers
            INCLUDE_GROUPS = {
                'Sundry Debtors', 'Sundry Creditors',
                'Loans (Liability)', 'Loans & Advances (Asset)',
                'Capital Account', 'Investments',
                'Secured Loans', 'Unsecured Loans',
                'Bank Accounts', 'Bank OD Accounts'
            }
            if master_df is not None and '$_PrimaryGroup' in master_df.columns:
                rp_ledgers = sorted(
                    master_df[master_df['$_PrimaryGroup'].isin(INCLUDE_GROUPS)]['$Name']
                    .dropna().unique().tolist()
                )
                rp_path = os.path.join(output_folder, "RP_Ledgers.json")
                with open(rp_path, 'w') as f:
                    json.dump(rp_ledgers, f)
                print("✅ RP ledgers saved.")
        except Exception as e:
            print(f"⚠️ Filter options save failed: {e}")

    print("✅ Consolidation completed successfully.")


def consolidate_prev_year(company_name: str, fy: str):
    """Consolidate previous year master data for Group Concern."""
    in_dir    = str(paths.extracted_dir(company_name, fy))
    out_dir   = str(paths.consolidated_dir(company_name, fy))
    os.makedirs(out_dir, exist_ok=True)

    files = [
        os.path.join(in_dir, f)
        for f in os.listdir(in_dir)
        if f.startswith("PrevYear_") and f.endswith("_MasterData.csv")
    ]
    if not files:
        raise FileNotFoundError("No previous year master files found. Extract first.")

    df = pd.concat([pd.read_csv(f) for f in files], ignore_index=True)
    out_path = os.path.join(out_dir, "PrevYear_Conso_MasterData.csv")
    df.to_csv(out_path, index=False)
    print(f"✅ PrevYear consolidated: {out_path}")
    return out_path
