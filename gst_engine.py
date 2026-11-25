import pandas as pd
from pathlib import Path
import glob

import paths


def get_gst_group(name: str) -> str:
    n = str(name).upper()
    if 'CGST' in n: return 'CGST'
    if 'SGST' in n: return 'SGST'
    if 'IGST' in n: return 'IGST'
    if 'GST'  in n: return 'GST Group'
    return 'Other'


def load_transactions(company_name: str, fy: str) -> pd.DataFrame:
    consolidated_dir = paths.consolidated_dir(company_name, fy)
    files = sorted(consolidated_dir.glob("Transactions_*.csv"))
    if not files:
        raise FileNotFoundError("No consolidated transaction files found.")
    df = pd.concat([pd.read_csv(f) for f in files], ignore_index=True)
    # Tally's column CASE varies between runs — normalise so lookups are safe.
    from engines.extract_engine import normalize_txn_columns
    return normalize_txn_columns(df)


def get_gst_ledgers(df: pd.DataFrame) -> pd.DataFrame:
    """Returns all Duties & Taxes ledgers with GST Group assigned."""
    gst_df = df[df['$Led_BaseGroup'] == 'Duties & Taxes'].copy()
    gst_df['GST_Group'] = gst_df['$Particulars'].apply(get_gst_group)
    return gst_df


def filter_by_selection(df: pd.DataFrame, selected_ledgers: list) -> pd.DataFrame:
    return df[df['$Particulars'].isin(selected_ledgers)].copy()


def is_blank_party(val):
    return pd.isna(val) or str(val).strip() in ['', 'nan']


def make_pivot(df, rows, cols='GST_Group', values='$Amount'):
    if df.empty:
        return pd.DataFrame()
    pivot = df.pivot_table(
        index=rows, columns=cols, values=values,
        aggfunc='sum', fill_value=0, margins=True, margins_name='Total'
    ).reset_index()
    pivot.columns.name = None
    return pivot


def get_sales_view(df: pd.DataFrame) -> pd.DataFrame:
    filtered = df[df['$VchTypeParent'].isin(['Sales', 'Credit Note'])]
    return make_pivot(filtered, rows='$Particulars')


def get_purchase_view(df: pd.DataFrame) -> pd.DataFrame:
    filtered = df[df['$VchTypeParent'].isin(['Purchase', 'Debit Note'])]
    return make_pivot(filtered, rows='$Particulars')


def get_journal_with_party_view(df: pd.DataFrame) -> pd.DataFrame:
    filtered = df[
        (df['$VchTypeParent'] == 'Journal') &
        (~df['$Party_LedName'].apply(is_blank_party))
    ]
    return make_pivot(filtered, rows='$Party_LedName')


def get_journal_no_party_view(df: pd.DataFrame) -> pd.DataFrame:
    filtered = df[
        (df['$VchTypeParent'] == 'Journal') &
        (df['$Party_LedName'].apply(is_blank_party))
    ]
    return make_pivot(filtered, rows='$Particulars')


def get_payment_view(df: pd.DataFrame) -> pd.DataFrame:
    filtered = df[df['$VchTypeParent'] == 'Payment']
    return make_pivot(filtered, rows=['$Party_LedName', '$Particulars'])


def get_drilldown(df: pd.DataFrame, vch_type_parents: list,
                  row_field: str, row_value: str) -> pd.DataFrame:
    filtered = df[df['$VchTypeParent'].isin(vch_type_parents)]
    if row_value != 'Total':
        filtered = filtered[filtered[row_field] == row_value]
    return filtered


def export_to_excel(views: dict) -> bytes:
    import io
    out = io.BytesIO()
    with pd.ExcelWriter(out, engine='openpyxl') as writer:
        for sheet, df in views.items():
            if not df.empty:
                df.to_excel(writer, sheet_name=sheet[:31], index=False)
    out.seek(0)
    return out.read()
