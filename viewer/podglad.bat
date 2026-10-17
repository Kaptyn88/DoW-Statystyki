@echo off
rem Podglad statystyk oddzialow: najnowsze nagranie z ..\recordings albo plik podany jako argument
start "" "%~dp0..\.venv\Scripts\pythonw.exe" "%~dp0dow_viewer.py" %*
