@echo off
cd /d "%~dp0"
rem toolbarMode=minimal hides the developer toolbar and disables the R / C
rem keyboard shortcuts (Rerun / Clear-cache) so Ctrl+C copies normally.
python\python.exe -m streamlit run streamlit_app.py --client.toolbarMode=minimal
pause
