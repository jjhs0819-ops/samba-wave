' Samba Wave BG Worker Watchdog launcher (portable, invisible)
' Locates ps1 in same directory as this vbs.
Set fso = CreateObject("Scripting.FileSystemObject")
scriptDir = fso.GetParentFolderName(WScript.ScriptFullName)
ps1Path = scriptDir & "\bg_worker_watchdog.ps1"
Set WshShell = CreateObject("WScript.Shell")
WshShell.Run "powershell.exe -NoProfile -ExecutionPolicy Bypass -File """ & ps1Path & """", 0, False
