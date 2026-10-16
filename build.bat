@echo off
rem Builds dinput8.dll (32-bit) with the Visual Studio C++ tools.
setlocal
call "C:\Program Files\Microsoft Visual Studio\18\Community\VC\Auxiliary\Build\vcvars32.bat" >nul || exit /b 1
cd /d "%~dp0"
if not exist out mkdir out
cl /nologo /O2 /GS- /W3 /MT /LD src\tcs_universal.c /Fo:out\ /Fe:out\dinput8.dll /link /NOLOGO /DLL user32.lib kernel32.lib || exit /b 1
echo built out\dinput8.dll
