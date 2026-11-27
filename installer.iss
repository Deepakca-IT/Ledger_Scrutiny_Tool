; LS Tool - Inno Setup installer. All app code ships as plain source.
; Wildcards below mean a new module can never be left out of the build.
; Build: place embedded Python in the python folder, then run ISCC.exe installer.iss
; The version comes from version.txt, the same file the updater reads.
#define AppVer Trim(FileRead(FileOpen("version.txt")))
; ISCC /DTestBuild makes a separately named build whose data reset only touches the
; install folder, so the installer can be tested on a working PC.
#ifdef TestBuild
  #define AppTitle "LS Tool TEST"
  #define DocsRoot "{app}\TestDocuments"
  #define OutName "LS_Tool_Setup_TEST"
#else
  #define AppTitle "LS Tool"
  #define DocsRoot "{userdocs}"
  #define OutName "LS_Tool_Setup"
#endif

[Setup]
AppName={#AppTitle}
AppVersion={#AppVer}
VersionInfoVersion={#AppVer}
AppPublisher=CA P Deepak Siddarth
AppPublisherURL=https://github.com/Deepakca-IT/Ledger_Scrutiny_Tool
DefaultDirName={localappdata}\LS_Tool
DefaultGroupName={#AppTitle}
AllowNoIcons=yes
OutputDir=installer_output
OutputBaseFilename={#OutName}
SetupIconFile=app.ico
LicenseFile=LICENSE
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
; Install per-user in a writable folder so updates never need admin rights
PrivilegesRequired=lowest
CloseApplications=yes

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional Icons:"

[InstallDelete]
; Older versions shipped compiled modules, which would override the new source.
Type: files; Name: "{app}\*.pyd"
Type: files; Name: "{app}\engines\*.pyd"
Type: files; Name: "{app}\license_engine.py"
; A half-finished update must never be applied over a fresh install.
Type: filesandordirs; Name: "{app}\update_staging"
Type: files; Name: "{app}\update_ready.txt"
; Replace the embedded Python completely so no old packages remain.
Type: filesandordirs; Name: "{app}\python"

[UninstallDelete]
; Files the app creates beside itself. User data lives elsewhere and is kept.
Type: files; Name: "{app}\update_state.json"
Type: files; Name: "{app}\update_ready.txt"
Type: filesandordirs; Name: "{app}\update_staging"
Type: filesandordirs; Name: "{app}\__pycache__"
Type: filesandordirs; Name: "{app}\engines\__pycache__"

[Files]
; ── App code (every module) ──
Source: "*.py"; DestDir: "{app}"; Flags: ignoreversion
Source: "engines\*.py"; DestDir: "{app}\engines"; Flags: ignoreversion
Source: "tally_tdl\*"; DestDir: "{app}\tally_tdl"; Flags: ignoreversion

; ── Resources, notes + launchers ────────────────────────────────────────────
Source: "app.ico";          DestDir: "{app}"; Flags: ignoreversion
Source: "run.bat";          DestDir: "{app}"; Flags: ignoreversion
Source: "run_app.bat";      DestDir: "{app}"; Flags: ignoreversion
Source: "LS_Tool.vbs";      DestDir: "{app}"; Flags: ignoreversion
Source: "splash.html";      DestDir: "{app}"; Flags: ignoreversion
Source: "version.txt";      DestDir: "{app}"; Flags: ignoreversion
Source: "changelog.txt";    DestDir: "{app}"; Flags: ignoreversion
Source: "requirements.txt"; DestDir: "{app}"; Flags: ignoreversion
Source: "README.md";        DestDir: "{app}"; Flags: ignoreversion
Source: "LICENSE";          DestDir: "{app}"; Flags: ignoreversion

; ── Embedded Python (includes reportlab, pandas, streamlit, etc.) ──────────
Source: "python\*"; DestDir: "{app}\python"; Excludes: "__pycache__"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
; Shortcuts run the hidden VBS launcher (via wscript) so only the app window
; shows. Closing the app window shuts the server down (app_launch.py watchdog).
Name: "{group}\LS Tool"; Filename: "{sys}\wscript.exe"; Parameters: """{app}\LS_Tool.vbs"""; WorkingDir: "{app}"; IconFilename: "{app}\app.ico"
Name: "{group}\Uninstall LS Tool"; Filename: "{uninstallexe}"
Name: "{autodesktop}\LS Tool"; Filename: "{sys}\wscript.exe"; Parameters: """{app}\LS_Tool.vbs"""; WorkingDir: "{app}"; IconFilename: "{app}\app.ico"; Tasks: desktopicon

[Run]
Filename: "{sys}\wscript.exe"; Parameters: """{app}\LS_Tool.vbs"""; WorkingDir: "{app}"; Description: "Launch LS Tool"; Flags: nowait postinstall skipifsilent

[Code]
var
  KeptData: String;

// True when the install folder holds a pre-open-source edition (licence + token updater).
function IsOldEdition(): Boolean;
var
  App: String;
begin
  App := ExpandConstant('{app}');
  Result := FileExists(App + '\updater.cp312-win_amd64.pyd') or
            FileExists(App + '\license_engine.py') or
            FileExists(App + '\license_engine.cp312-win_amd64.pyd');
end;

// Upgrading an old edition starts with empty data: the old default data folder
// is renamed (never deleted) and any custom data location is forgotten. A fresh
// install, or a reinstall of this edition, leaves data alone.
function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  Old, Dest, Stamp: String;
  N: Integer;
begin
  Result := '';
  if not IsOldEdition() then
    exit;
  DeleteFile(ExpandConstant('{app}\data_location.json'));
  Old := ExpandConstant('{#DocsRoot}\LSTool');
  if not DirExists(Old) then
    exit;
  Stamp := GetDateTimeString('yyyy/mm/dd', '-', ':');
  Dest := Old + '_old_' + Stamp;
  N := 2;
  while DirExists(Dest) do
  begin
    Dest := Old + '_old_' + Stamp + '_' + IntToStr(N);
    N := N + 1;
  end;
  if RenameFile(Old, Dest) then
    KeptData := Dest
  else
    Result := 'Could not rename the old data folder ' + Old + '. Close LS Tool and any ' +
              'window or file open from that folder, then run this installer again.';
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if (CurStep = ssPostInstall) and (KeptData <> '') and not WizardSilent() then
    MsgBox('Your previous LS Tool data was kept, renamed to:' + #13#10 + KeptData + #13#10#13#10 +
           'LS Tool now starts with an empty data folder.', mbInformation, MB_OK);
end;
