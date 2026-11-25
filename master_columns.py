"""Column names shared by every module that reads extracted ledger masters."""

GSTIN = "$PartyGSTIN1"          # name used inside the engines (and older extracts)
GSTIN_EXTRACT = "$_PartyGSTIN1"  # name written by the current extraction


def unify_gstin(df):
    """Return df with the party GSTIN under `GSTIN`.

    Current extracts use `$_PartyGSTIN1`, older ones `$PartyGSTIN1`. When a file
    has both (old and new branches consolidated together), the new column wins
    and the old one fills its blanks.
    """
    if GSTIN_EXTRACT not in df.columns:
        return df
    df = df.copy()
    new = df[GSTIN_EXTRACT]
    if GSTIN in df.columns:
        new = new.astype("object")
        blank = new.isna() | (new.astype("string").fillna("").str.strip() == "")
        df[GSTIN] = new.where(~blank, df[GSTIN])
        return df.drop(columns=[GSTIN_EXTRACT])
    return df.rename(columns={GSTIN_EXTRACT: GSTIN})
