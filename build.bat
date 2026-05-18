@echo off
REM ══════════════════════════════════════════════════════════════════════════════
REM  BetBot Build Script
REM  Run this to produce dist\BetBot\ (PyInstaller) and dist\installer\ (Inno Setup)
REM
REM  Requirements:
REM    pip install pyinstaller
REM    Inno Setup 6 installed at default path (C:\Program Files (x86)\Inno Setup 6\)
REM ══════════════════════════════════════════════════════════════════════════════

setlocal enabledelayedexpansion

echo.
echo ╔══════════════════════════════════════╗
echo ║        BetBot Build Script           ║
echo ╚══════════════════════════════════════╝
echo.

REM ── Step 1: Generate update manifest ─────────────────────────────────────────
echo [1/3] Generating update manifest...
python tools\generate_manifest.py
if errorlevel 1 (
    echo ERROR: generate_manifest.py failed
    pause
    exit /b 1
)
echo.

REM ── Step 2: PyInstaller ───────────────────────────────────────────────────────
echo [2/3] Building EXE with PyInstaller...
pyinstaller bet-bot.spec --noconfirm --clean
if errorlevel 1 (
    echo ERROR: PyInstaller failed
    pause
    exit /b 1
)

REM Move app/ from _internal to top level so it can be hot-updated independently
echo Moving app/ to top level...
if exist "dist\BetBot\_internal\app" (
    xcopy /E /I /Y "dist\BetBot\_internal\app" "dist\BetBot\app" >nul
    rmdir /S /Q "dist\BetBot\_internal\app"
)
echo.

REM ── Step 3: Inno Setup ────────────────────────────────────────────────────────
echo [3/3] Building installer with Inno Setup...

REM Try default Inno Setup install paths
set ISCC="C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
if not exist %ISCC% set ISCC="C:\Program Files\Inno Setup 6\ISCC.exe"

if not exist %ISCC% (
    echo WARNING: Inno Setup not found. Skipping installer build.
    echo          Download from https://jrsoftware.org/isdl.php
    echo          Then run:  ISCC.exe installer\BetBot.iss
    goto :done
)

%ISCC% installer\BetBot.iss
if errorlevel 1 (
    echo ERROR: Inno Setup build failed
    pause
    exit /b 1
)

:done
echo.
echo ══════════════════════════════════════════
echo  Build complete!
echo.
echo  Distributable EXE:   dist\BetBot\BetBot.exe
if exist "dist\installer\BetBot-Setup-*.exe" (
    echo  Installer:           dist\installer\BetBot-Setup-*.exe
)
echo ══════════════════════════════════════════
echo.
pause
