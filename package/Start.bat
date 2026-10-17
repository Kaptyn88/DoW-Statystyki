@echo off
rem DoW - statystyki powtorek: podglad + Dawn of War DE z rejestratorem (tylko do ogladania powtorek).
setlocal
cd /d "%~dp0"
title DoW - statystyki powtorek

tasklist /FI "IMAGENAME eq W40k.exe" 2>nul | find /I "W40k.exe" >nul
if not errorlevel 1 (
    echo Gra juz dziala. Zamknij Dawn of War i uruchom Start.bat ponownie.
    pause
    exit /b 1
)

"bin\dowprobe_launcher.exe" --where >nul
if errorlevel 1 (
    echo Nie znaleziono Dawn of War: Definitive Edition w bibliotekach Steam.
    echo Upewnij sie, ze gra jest zainstalowana przez Steam.
    pause
    exit /b 1
)

start "" "%~dp0Podglad.exe"
echo Podglad uruchomiony. Uruchamiam gre z rejestratorem...
echo Po dojsciu do menu: Powtorki - wybierz powtorke - Odtworz.
echo.
"bin\dowprobe_launcher.exe" --rec --out "%~dp0recordings" --logs "%~dp0logs"
echo.
echo To okno mozna zamknac.
timeout /t 15
