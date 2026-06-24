@echo off
chcp 65001 > nul
setlocal EnableDelayedExpansion
echo ================================================
echo  Samba Wave 나이키 배경제거 야간 배치 - 설치
echo ================================================
echo.

set "SCRIPT_DIR=%~dp0"
set "SCRIPT_DIR=%SCRIPT_DIR:~0,-1%"
set "TASK_NAME=SambaNikeNightBgEnqueue"
set "ENVFILE=%SCRIPT_DIR%\bg_worker.env"
set "LOG_DIR=%SCRIPT_DIR%\logs"

REM ── Python 경로 확인 ──────────────────────────────
echo [1/4] Python 경로 확인...
where python >nul 2>nul
if errorlevel 1 (
    echo [오류] Python을 찾을 수 없습니다. Python 3.10 이상을 설치해주세요.
    goto :END
)
for /f "tokens=*" %%i in ('where python') do (
    set "PYTHON=%%i"
    goto :gotpython
)
:gotpython
python --version
echo       사용: !PYTHON!

REM ── bg_worker.env 자격증명 확인 ──────────────────
echo.
echo [2/4] bg_worker.env 확인...
if not exist "%ENVFILE%" (
    echo [오류] bg_worker.env 파일이 없습니다: %ENVFILE%
    echo       bg_worker.env.example을 복사하고 설정 후 다시 실행하세요.
    goto :END
)

findstr /C:"SAMBA_EMAIL" "%ENVFILE%" >nul 2>nul
if errorlevel 1 (
    echo.
    echo [필요] bg_worker.env에 아래 두 줄을 추가해주세요:
    echo.
    echo   SAMBA_EMAIL=your_email@example.com
    echo   SAMBA_PASSWORD=your_password
    echo.
    echo 추가 후 이 파일을 다시 실행하세요.
    notepad "%ENVFILE%"
    goto :END
)
echo       OK - 자격증명 확인됨

REM ── 로그 디렉토리 생성 ────────────────────────────
echo.
echo [3/4] 로그 디렉토리 생성...
if not exist "%LOG_DIR%" mkdir "%LOG_DIR%"
echo       %LOG_DIR%

REM ── 작업 스케줄러 등록 ────────────────────────────
echo.
echo [4/4] 작업 스케줄러 등록 (매일 새벽 3시)...

REM 기존 작업 삭제
schtasks /Delete /TN "%TASK_NAME%" /F >nul 2>nul

REM 새벽 3시(KST) 일 1회 실행
schtasks /Create ^
    /TN "%TASK_NAME%" ^
    /TR "\"!PYTHON!\" \"%SCRIPT_DIR%\night_nike_bg_enqueue.py\"" ^
    /SC DAILY ^
    /ST 03:00 ^
    /RL LIMITED ^
    /F
if errorlevel 1 (
    echo [오류] 작업 스케줄러 등록 실패.
    goto :END
)

echo.
echo ================================================
echo  설치 완료!
echo.
echo  - 작업명: %TASK_NAME%
echo  - 실행: 매일 새벽 3:00 AM (이 PC 켜져있어야 함)
echo  - 로그: %LOG_DIR%\night_nike_bg.log
echo  - 수동 실행: python "%SCRIPT_DIR%\night_nike_bg_enqueue.py"
echo.
echo  bg-worker(배경제거 실행자)가 별도로 실행 중이어야 합니다.
echo  bg-worker 미설치 시 install_bg_worker.bat 먼저 실행하세요.
echo ================================================

:END
echo.
pause
endlocal
