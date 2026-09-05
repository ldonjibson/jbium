@echo off
REM ═══════════════════════════════════════════════════════════
REM Jbium — Windows Launcher
REM ═══════════════════════════════════════════════════════════

setlocal

REM Find Python
set PYTHON=python
where python >nul 2>&1
if errorlevel 1 (
    set PYTHON=python3
    where python3 >nul 2>&1
    if errorlevel 1 (
        echo Error: Python 3.8+ required
        exit /b 1
    )
)

REM Get script directory
set SCRIPT_DIR=%~dp0

REM Launch
%PYTHON% "%SCRIPT_DIR%stealth_browser.py" %*

endlocal
