@echo off
rem DoW - statystyki powtorek / replay statistics
rem Komunikaty wypisuje launcher w jezyku uzytkownika (pl/en/ru), dlatego tu nie ma tekstow.
setlocal
cd /d "%~dp0"
title DoW - Statystyki

"bin\dowprobe_launcher.exe" --check
if errorlevel 1 (
    pause
    exit /b 1
)
start "" "%~dp0Podglad.exe"
"bin\dowprobe_launcher.exe" --rec --out "%~dp0recordings" --logs "%~dp0logs"
echo.
timeout /t 15
