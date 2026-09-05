@echo off
REM ═══════════════════════════════════════════════════════════
REM Build Jbium on Windows
REM Requires: Visual Studio 2022, Python 3.8+, Git
REM ═══════════════════════════════════════════════════════════

setlocal enabledelayedexpansion

set CHROMIUM_DIR=C:\jbium\chromium
set OUTPUT_DIR=%CHROMIUM_DIR%\src\out\Release
set DEPOT_TOOLS_DIR=C:\depot_tools

echo ═══════════════════════════════════════════════════════════
echo   Building Jbium (Windows)
echo ═══════════════════════════════════════════════════════════

REM ── Step 1: Check prerequisites ──
echo [1/6] Checking prerequisites...

where python >nul 2>&1
if errorlevel 1 (
    echo   ❌ Python not found. Install Python 3.8+
    exit /b 1
)

where git >nul 2>&1
if errorlevel 1 (
    echo   ❌ Git not found. Install Git for Windows
    exit /b 1
)

if not exist "%DEPOT_TOOLS_DIR%" (
    echo   Installing depot_tools...
    git clone https://chromium.googlesource.com/chromium/tools/depot_tools.git %DEPOT_TOOLS_DIR%
)

set PATH=%DEPOT_TOOLS_DIR%;%PATH%
set DEPOT_TOOLS_WIN_TOOLCHAIN=0
set GYP_MSVS_VERSION=2022

echo   ✅ Prerequisites OK

REM ── Step 2: Fetch source ──
echo [2/6] Fetching Chromium source...

if not exist "%CHROMIUM_DIR%\src" (
    mkdir %CHROMIUM_DIR%
    cd /d %CHROMIUM_DIR%
    call fetch --no-history --nohooks chromium
)

cd /d %CHROMIUM_DIR%\src

echo   ✅ Source ready

REM ── Step 3: Run hooks ──
echo [3/6] Running hooks...

call gclient runhooks
if errorlevel 1 (
    echo   ❌ Hooks failed
    exit /b 1
)

echo   ✅ Hooks complete

REM ── Step 4: Apply patches ──
echo [4/6] Applying stealth patches...

for %%d in ("%~dp0..\patches\0*") do (
    if exist "%%d\apply.bat" (
        echo   Applying: %%~nxd
        call "%%d\apply.bat"
    ) else if exist "%%d\apply.py" (
        echo   Applying: %%~nxd
        python "%%d\apply.py"
    )
)

echo   ✅ Patches applied

REM ── Step 5: Configure build ──
echo [5/6] Configuring build...

if not exist "%OUTPUT_DIR%" mkdir "%OUTPUT_DIR%"
copy "%~dp0..\config\args_windows.gn" "%OUTPUT_DIR%\args.gn" >nul

call gn gen out\Release
if errorlevel 1 (
    echo   ❌ GN generation failed
    exit /b 1
)

echo   ✅ Build configured

REM ── Step 6: Build ──
echo [6/6] Building (this takes 3-6 hours on 16+ cores)...

set /a NUM_JOBS=%NUMBER_OF_PROCESSORS%
echo   Using %NUM_JOBS% parallel jobs

call ninja -C out\Release chrome -j %NUM_JOBS%
if errorlevel 1 (
    echo   ❌ Build failed
    exit /b 1
)

echo   Renaming binary: chrome.exe -^> jbium.exe
move /y "%OUTPUT_DIR%\chrome.exe" "%OUTPUT_DIR%\jbium.exe" >nul

echo ═══════════════════════════════════════════════════════════
echo   ✅ Build Complete!
echo ═══════════════════════════════════════════════════════════
echo   Binary: %OUTPUT_DIR%\jbium.exe
echo   Size:
for %%F in ("%OUTPUT_DIR%\jbium.exe") do echo   %%~zF bytes

endlocal
