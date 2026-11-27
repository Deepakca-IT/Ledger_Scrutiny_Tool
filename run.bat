@echo off
cd /d "%~dp0"
rem Install an update downloaded by the app, before Python starts.
if exist update_ready.txt (
  %SystemRoot%\System32\xcopy.exe /e /y /q "update_staging\*" "." >nul && (
    rd /s /q update_staging
    del /q update_ready.txt
  )
)
rem toolbarMode=minimal hides the developer toolbar and disables the R / C
rem keyboard shortcuts (Rerun / Clear-cache) so Ctrl+C copies normally.
python\python.exe -m streamlit run streamlit_app.py --client.toolbarMode=minimal
pause
