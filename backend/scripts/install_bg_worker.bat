@echo off
echo ================================================
echo  Samba Wave BG Worker - Install
echo ================================================
echo.

echo [Check] Python version...
python --version
if errorlevel 1 (
    echo.
    echo [ERROR] Python not found. Install Python 3.10+ from https://python.org
    echo         Check "Add Python to PATH" during install.
    goto :END
)

echo.
echo [1/3] Installing packages (may take a few minutes)...
pip install "rembg[cpu]" httpx boto3 pillow
if errorlevel 1 (
    echo.
    echo [ERROR] Package install failed. See error above.
    goto :END
)
echo       Done.

echo.
echo [2/3] Setting up .env config file...
if not exist "%~dp0bg_worker.env" (
    copy "%~dp0bg_worker.env.example" "%~dp0bg_worker.env" > nul
    echo       Created .env file. Opening for editing...
    echo       Fill in: SAMBA_TOKEN, R2_ACCOUNT_ID, R2_ACCESS_KEY, R2_SECRET_KEY, R2_BUCKET, R2_PUBLIC_URL
    echo.
    notepad "%~dp0bg_worker.env"
) else (
    echo       bg_worker.env already exists.
)

echo.
echo [3/3] Registering Windows Startup...
set "STARTUP_DIR=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup"
set "STARTUP_BAT=%STARTUP_DIR%\samba_bg_worker.bat"
set "WORKER=%~dp0local_bg_worker.py"

(echo @echo off
echo cd /d "%~dp0"
echo python "%~dp0local_bg_worker.py"
) > "%STARTUP_BAT%"

if errorlevel 1 (
    echo [ERROR] Failed to register startup.
    goto :END
)
echo       Registered: %STARTUP_BAT%

echo.
echo ================================================
echo  Install complete!
echo  Worker will auto-start on next Windows boot.
echo.
echo  To run now:  python "%WORKER%"
echo ================================================

:END
echo.
pause
