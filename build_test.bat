@echo off
rem Test build for tests\emulate.py: same source with TCSU_TEST entry points, no CRT start-up needed by the tests.
setlocal
call "C:\Program Files\Microsoft Visual Studio\18\Community\VC\Auxiliary\Build\vcvars32.bat" >nul || exit /b 1
cd /d "%~dp0"
if not exist out\test mkdir out\test
cl /nologo /O2 /GS- /W3 /MT /LD /DTCSU_TEST src\tcs_universal.c /Fo:out\test\ /Fe:out\test\dinput8_test.dll /link /NOLOGO /DLL /FIXED:NO /BASE:0x10000000 user32.lib kernel32.lib || exit /b 1
echo built out\test\dinput8_test.dll
