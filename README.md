# Ledger Scrutiny Tool

A Windows desktop tool for Chartered Accountants. It reads data from Tally over ODBC, runs scrutiny, TDS, GST, MSME and Clause 44 checks, and shows the results in a local Streamlit app.

Data stays on your computer or your own shared folder.

## Requirements
- Windows and Python 3.12
- Tally with ODBC enabled (port 9400) and `tally_tdl/DB_Mini_with_LiteV4_1.tdl` loaded

## Run
```
pip install -r requirements.txt
python -m streamlit run streamlit_app.py
```

## Important
- Review every result professionally before use.
- Never add client data, exports or reports to this repository or its issues.

## Known issues
- **Large companies:** Ledger Scrutiny reads only the first transaction file (about 10.48 lakh rows).

## Licence
MIT. See [LICENSE](LICENSE).
