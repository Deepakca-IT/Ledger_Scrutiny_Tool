@echo off
cd /d "%~dp0"
rem === LS Tool — desktop app launcher (used by the installed shortcut) =========
rem app_launch.py starts the server, opens the app window, and shuts the server
rem down when that window is closed. No pause — this runs hidden via LS_Tool.vbs.
python\python.exe app_launch.py
