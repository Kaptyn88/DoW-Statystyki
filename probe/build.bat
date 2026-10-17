@echo off
rem Buduje dowprobe.dll, dowrec.dll i dowprobe_launcher.exe (x64, MSVC Build Tools) do probe\bin
setlocal
call "C:\Program Files (x86)\Microsoft Visual Studio\18\BuildTools\VC\Auxiliary\Build\vcvars64.bat" >nul || exit /b 1
cd /d "%~dp0"
if not exist bin mkdir bin
if not exist obj mkdir obj
set MH=..\third_party\minhook
cl /nologo /O2 /MT /W3 /EHsc /std:c++17 /utf-8 /DNDEBUG /I%MH%\include /Foobj\ ^
   src\probe.cpp %MH%\src\buffer.c %MH%\src\hook.c %MH%\src\trampoline.c %MH%\src\hde\hde64.c ^
   /LD /Fe:bin\dowprobe.dll /link /NOLOGO || exit /b 1
cl /nologo /O2 /MT /W3 /EHsc /std:c++17 /utf-8 /DNDEBUG /I%MH%\include /Foobj\ ^
   src\recorder.cpp %MH%\src\buffer.c %MH%\src\hook.c %MH%\src\trampoline.c %MH%\src\hde\hde64.c ^
   /LD /Fe:bin\dowrec.dll /link /NOLOGO || exit /b 1
cl /nologo /O2 /MT /W3 /EHsc /std:c++17 /utf-8 /Foobj\ src\launcher.cpp /Fe:bin\dowprobe_launcher.exe ^
   /link /NOLOGO psapi.lib user32.lib advapi32.lib || exit /b 1
echo OK
