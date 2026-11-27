# Ledger Scrutiny Tool

A Windows desktop tool for Chartered Accountants. It reads data from Tally over ODBC, runs scrutiny, TDS, GST, MSME and Clause 44 checks, and shows the results in a local Streamlit app.

Data stays on your computer or your own shared folder.

## Install (Windows)
1. Download `LS_Tool_Setup.exe` from the latest [release](https://github.com/Deepakca-IT/Ledger_Scrutiny_Tool/releases/latest).
2. Run it. Windows may warn about an unrecognised app: choose **More info, Run anyway**.
3. In Tally, load `tally_tdl\DB_Mini_with_LiteV4_1.tdl` from the install folder and restart Tally.

Upgrading from an older licensed version starts with empty data. The old `Documents\LSTool` folder is renamed, never deleted.

## Updates
The app checks GitHub once a day. A new version downloads in the background and installs the next time you open the app. Use **Check for updates** in the sidebar to check now. If a release needs new Python packages, the app asks you to run the new installer instead.

## Run from source
### Requirements
- Windows and Python 3.12
- Tally with ODBC enabled (port 9400) and `tally_tdl/DB_Mini_with_LiteV4_1.tdl` loaded

### Run
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
