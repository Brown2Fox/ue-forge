@echo off
where pwsh.exe >nul 2>nul
if errorlevel 1 (
    echo PowerShell 7 was not found. Install it and try again.
    pause
    exit /b 1
)

pwsh.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0build.ps1"
if errorlevel 1 (
    echo.
    echo Build failed.
    pause
    exit /b 1
)

echo.
pause
