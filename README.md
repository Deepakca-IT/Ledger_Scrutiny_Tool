# Ledger Scrutiny Tool

A Windows desktop tool for Chartered Accountants. It reads data from Tally over ODBC, runs scrutiny, TDS, GST, MSME and Clause 44 checks, and shows the results in a local Streamlit app.

Data stays on your computer or your own shared folder.

## Requirements
- Windows and Python 3.12
- Tally with ODBC enabled (port 9400) and one of the `DB_Mini` TDL files in `tally_tdl`

## Run
```
pip install -r requirements.txt
python -m streamlit run streamlit_app.py
```

## Important
- Review every result professionally before use.
- Never add client data, exports or reports to this repository or its issues.

## Known issues
- **TDL files:** the two `DB_Mini` versions are still to be tested. The corrected optional/cancelled voucher rule still needs testing in Tally.
- **Large companies:** Ledger Scrutiny reads only the first transaction file (about 10.48 lakh rows).

## Licence
MIT. See [LICENSE](LICENSE).
