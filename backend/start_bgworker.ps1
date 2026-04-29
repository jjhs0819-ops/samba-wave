$env:PYTHONUNBUFFERED = '1'
$env:PYTHONIOENCODING = 'utf-8'
# 부팅 시 reset-running 엔드포인트가 stuck 잡을 자동 정리하므로 SKIP 리스트 불필요
Set-Location 'C:\Users\canno\workspace\samba-wave\backend'
& '.\.venv\Scripts\python.exe' '-u' 'scripts/local_bg_worker.py'
