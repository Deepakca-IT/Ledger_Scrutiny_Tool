' LS Tool launcher — runs run_app.bat with a HIDDEN console window so only the
' app window is visible. The "0" = hidden; "False" = don't wait (return at once).
Dim fso, here
Set fso = CreateObject("Scripting.FileSystemObject")
here = fso.GetParentFolderName(WScript.ScriptFullName)
CreateObject("WScript.Shell").Run """" & here & "\run_app.bat""", 0, False
