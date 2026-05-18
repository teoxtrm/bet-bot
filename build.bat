@echo off
setlocal enabledelayedexpansion

echo.
echo ╔══════════════════════════════════════════╗
echo ║         BetBot  —  Release Builder       ║
echo ╚══════════════════════════════════════════╝
echo.

REM ── Read current version ──────────────────────────────────────────────────────
set /p CURRENT_VER=<version.txt
set CURRENT_VER=%CURRENT_VER: =%

REM ── Ask for new version ───────────────────────────────────────────────────────
echo  Current version : %CURRENT_VER%
set /p NEW_VER= New version    :

if "%NEW_VER%"=="" (
    echo ERROR: Version cannot be empty.
    pause
    exit /b 1
)

echo.
echo  Building v%NEW_VER% ...
echo.

REM ── Step 1: Bump version.txt ──────────────────────────────────────────────────
echo [1/6] Bumping version to %NEW_VER% ...
echo %NEW_VER%> version.txt
echo  Done.
echo.

REM ── Step 2: Update installer script version ───────────────────────────────────
echo [2/6] Updating installer script...
powershell -Command "(Get-Content 'installer\betbot_installer.iss') -replace 'AppVersion=.*', 'AppVersion=%NEW_VER%' -replace 'OutputBaseFilename=.*', 'OutputBaseFilename=BetBot_Setup_v%NEW_VER%' | Set-Content 'installer\betbot_installer.iss'"
echo  Done.
echo.

REM ── Step 3: Generate update manifest ─────────────────────────────────────────
echo [3/6] Generating update manifest...
python tools\generate_manifest.py
if errorlevel 1 (
    echo ERROR: generate_manifest.py failed
    pause
    exit /b 1
)
echo.

REM ── Step 4: PyInstaller ───────────────────────────────────────────────────────
echo [4/6] Building EXE with PyInstaller...
pyinstaller bet-bot.spec --noconfirm --clean
if errorlevel 1 (
    echo ERROR: PyInstaller failed
    pause
    exit /b 1
)

echo  Moving app\ to top level of dist...
if exist "dist\BetBot\_internal\app" (
    xcopy /E /I /Y "dist\BetBot\_internal\app" "dist\BetBot\app" >nul
    rmdir /S /Q "dist\BetBot\_internal\app"
)
echo  Done.
echo.

REM ── Step 5: Inno Setup installer ─────────────────────────────────────────────
echo [5/6] Building installer...

set ISCC="C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
if not exist %ISCC% set ISCC="C:\Program Files\Inno Setup 6\ISCC.exe"

if not exist %ISCC% (
    echo  WARNING: Inno Setup not found — skipping installer.
    echo           Download: https://jrsoftware.org/isdl.php
) else (
    %ISCC% installer\betbot_installer.iss
    if errorlevel 1 (
        echo ERROR: Inno Setup failed
        pause
        exit /b 1
    )
    echo  Done.
)
echo.

REM ── Step 6: Git commit + push ─────────────────────────────────────────────────
echo [6/6] Pushing to GitHub...
git add -A
git commit -m "Release v%NEW_VER%"
git push
if errorlevel 1 (
    echo ERROR: git push failed — check your connection or GitHub auth.
    pause
    exit /b 1
)
echo  Done.
echo.

REM ── Summary ───────────────────────────────────────────────────────────────────
echo ══════════════════════════════════════════════════════
echo   Release v%NEW_VER% complete!
echo.
echo   EXE folder : dist\BetBot\BetBot.exe
echo   Installer  : installer\BetBot_Setup_v%NEW_VER%.exe
echo   GitHub     : pushed to main — users will auto-update
echo ══════════════════════════════════════════════════════
echo.
pause
