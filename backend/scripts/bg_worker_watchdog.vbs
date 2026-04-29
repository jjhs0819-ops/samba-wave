' Samba Wave BG Worker Watchdog launcher (invisible)
' Runs the PowerShell watchdog with no visible window.
Set WshShell = CreateObject("WScript.Shell")
WshShell.Run "powershell.exe -NoProfile -ExecutionPolicy Bypass -File """ & _
    "C:\Users\canno\workspace\samba-wave\backend\scripts\bg_worker_watchdog.ps1""", 0, False
