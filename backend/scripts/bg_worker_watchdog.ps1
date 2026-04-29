# Samba Wave BG Worker Watchdog
# 작업 스케줄러가 1분마다 호출 — 워커가 죽어있으면 hidden 모드로 재기동
$ErrorActionPreference = 'SilentlyContinue'

$workerDir = 'C:\Users\canno\workspace\samba-wave\backend'
$python = "$workerDir\.venv\Scripts\python.exe"
$workerScript = 'scripts\local_bg_worker.py'

$running = Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
    Where-Object { $_.CommandLine -like '*local_bg_worker.py*' }

if (-not $running) {
    $env:PYTHONIOENCODING = 'utf-8'
    $env:PYTHONUTF8 = '1'
    Start-Process -WindowStyle Hidden `
        -WorkingDirectory $workerDir `
        -FilePath $python `
        -ArgumentList '-u', $workerScript
}
