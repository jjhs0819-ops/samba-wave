@echo off
chcp 65001 > nul
REM 워커 한글 로그 깨짐 방지
set PYTHONIOENCODING=utf-8
set PYTHONUTF8=1
REM PowerShell로 commandline 매칭 — 안 떠 있으면 hidden으로 새로 기동
powershell -NoProfile -ExecutionPolicy Bypass -Command "$running = Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" -ErrorAction SilentlyContinue ^| Where-Object { $_.CommandLine -like '*local_bg_worker.py*' }; if (-not $running) { $env:PYTHONIOENCODING='utf-8'; $env:PYTHONUTF8='1'; Start-Process -WindowStyle Hidden -WorkingDirectory 'C:\Users\canno\workspace\samba-wave\backend' -FilePath 'C:\Users\canno\workspace\samba-wave\backend\.venv\Scripts\python.exe' -ArgumentList '-u','scripts\local_bg_worker.py' }"
