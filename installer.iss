; LS Tool - Inno Setup installer. All app code ships as plain source.
; Wildcards below mean a new module can never be left out of the build.
; Build: place embedded Python in the python folder, then run ISCC.exe installer.iss
[Setup]
AppName=LS Tool
AppVersion=1.0.10
AppPublisher=CA DSP
DefaultDirName={localappdata}\LS_Tool
DefaultGroupName=LS Tool
AllowNoIcons=yes
OutputDir=installer_output
OutputBaseFilename=LS_Tool_Setup
SetupIconFile=app.ico
Compression=lzma
SolidCompression=yes
WizardStyle=modern
; Install per-user in a writable folder so auto-updates never need admin rights
PrivilegesRequired=lowest

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional Icons:"

[InstallDelete]
; Older versions shipped compiled modules, which would override the new source.
Type: files; Name: "{app}\*.pyd"
Type: files; Name: "{app}\engines\*.pyd"
Type: files; Name: "{app}\updater.py"
Type: files; Name: "{app}\license_engine.py"

[Files]
; ── App code (every module) ──
Source: "*.py"; DestDir: "{app}"; Flags: ignoreversion
Source: "engines\*.py"; DestDir: "{app}\engines"; Flags: ignoreversion
Source: "tally_tdl\*.tdl"; DestDir: "{app}\tally_tdl"; Flags: ignoreversion

; ── Resources + launchers ───────────────────────────────────────────────────
Source: "app.ico";       DestDir: "{app}"; Flags: ignoreversion
Source: "run.bat";       DestDir: "{app}"; Flags: ignoreversion
Source: "run_app.bat";   DestDir: "{app}"; Flags: ignoreversion
Source: "LS_Tool.vbs";   DestDir: "{app}"; Flags: ignoreversion
Source: "splash.html";   DestDir: "{app}"; Flags: ignoreversion
Source: "version.txt";   DestDir: "{app}"; Flags: ignoreversion

; ── Embedded Python (includes reportlab, pandas, streamlit, etc.) ──────────
Source: "python\*"; DestDir: "{app}\python"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
; Shortcuts run the hidden VBS launcher (via wscript) so only the app window
; shows. Closing the app window shuts the server down (app_launch.py watchdog).
Name: "{group}\LS Tool"; Filename: "{sys}\wscript.exe"; Parameters: """{app}\LS_Tool.vbs"""; WorkingDir: "{app}"; IconFilename: "{app}\app.ico"
Name: "{group}\Uninstall LS Tool"; Filename: "{uninstallexe}"
Name: "{autodesktop}\LS Tool"; Filename: "{sys}\wscript.exe"; Parameters: """{app}\LS_Tool.vbs"""; WorkingDir: "{app}"; IconFilename: "{app}\app.ico"; Tasks: desktopicon

[Run]
Filename: "{sys}\wscript.exe"; Parameters: """{app}\LS_Tool.vbs"""; WorkingDir: "{app}"; Description: "Launch LS Tool"; Flags: nowait postinstall skipifsilent
