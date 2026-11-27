@echo off
cd /d "%~dp0"
rem Install an update downloaded by the app, before Python starts.
if exist update_ready.txt (
  %SystemRoot%\System32\xcopy.exe /e /y /q "update_staging\*" "." >nul && (
    rd /s /q update_staging
    del /q update_ready.txt
  )
)
rem === LS Tool — desktop app launcher (used by the installed shortcut) =========
rem app_launch.py starts the server, opens the app window, and shuts the server
rem down when that window is closed. No pause — this runs hidden via LS_Tool.vbs.
python\python.exe app_launch.py
