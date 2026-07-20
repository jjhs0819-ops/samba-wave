# Samba Wave BG Worker Watchdog (portable template)
# Self-locates: uses its own directory as worker home, uses system 'python' from PATH.
$ErrorActionPreference = 'SilentlyContinue'

$workerDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$workerScript = Join-Path $workerDir 'local_bg_worker.py'

$running = Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
    Where-Object { $_.CommandLine -like '*local_bg_worker.py*' }

# Minimal log for diagnosing silent crash loops (e.g. empty token): last start / instant-death.
$logFile = Join-Path $workerDir 'bg_worker_watchdog.log'
$ts = (Get-Date).ToString('yyyy-MM-dd HH:mm:ss')

if (-not $running) {
    $env:PYTHONIOENCODING = 'utf-8'
    $env:PYTHONUTF8 = '1'
    $python = (Get-Command python -ErrorAction SilentlyContinue).Source
    if (-not $python) {
        "$ts [watchdog] python not found in PATH" | Out-File -Append -Encoding utf8 $logFile
        return
    }
    "$ts [watchdog] worker not running -> starting" | Out-File -Append -Encoding utf8 $logFile
    Start-Process -WindowStyle Hidden `
        -WorkingDirectory $workerDir `
        -FilePath $python `
        -ArgumentList '-u', $workerScript
}
