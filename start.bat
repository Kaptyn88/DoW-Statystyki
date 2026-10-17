@echo off
rem Start jednym kliknieciem: podglad statystyk + Dawn of War DE z rejestratorem (tylko do powtorek offline).
setlocal
cd /d "%~dp0"
title DoW - statystyki powtorek

tasklist /FI "IMAGENAME eq W40k.exe" 2>nul | find /I "W40k.exe" >nul
if not errorlevel 1 (
    echo Gra juz dziala. Zamknij Dawn of War i uruchom start.bat ponownie.
    pause
    exit /b 1
)

rem 1. srodowisko Pythona (podglad uzywa tylko biblioteki standardowej)
if not exist ".venv\Scripts\pythonw.exe" (
    echo Tworze srodowisko Pythona .venv ...
    py -3 -m venv .venv || python -m venv .venv || goto :blad
)

rem 2. DLL rejestratora i launcher (kompilacja MSVC, tylko gdy brakuje)
if not exist "probe\bin\dowrec.dll" call probe\build.bat || goto :blad
if not exist "probe\bin\dowprobe_launcher.exe" call probe\build.bat || goto :blad

rem 3. katalog nazw z danych gry (ok. 20 s, tylko gdy brakuje)
if not exist "catalog\catalog.json" (
    echo Buduje katalog jednostek, broni i zdolnosci z danych gry ...
    ".venv\Scripts\python.exe" catalog\build_catalog.py || goto :blad
)

rem 4. podglad (z nakladka, jesli wlaczona) i gra z rejestratorem
call viewer\podglad.bat
echo.
echo Podglad uruchomiony. Uruchamiam gre z rejestratorem...
echo Po dojsciu do menu: Powtorki - wybierz powtorke - Odtworz.
echo.
"probe\bin\dowprobe_launcher.exe" --rec
echo.
echo To okno mozna zamknac. Nagrania: %~dp0recordings
timeout /t 15
exit /b 0

:blad
echo.
echo Cos poszlo nie tak - szczegoly powyzej.
pause
exit /b 1
