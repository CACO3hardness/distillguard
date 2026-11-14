@echo off
rem ASCII only. cmd parses .cmd with the OEM code page, so any UTF-8 Chinese
rem here would be split into bogus commands.
rem Do NOT call chcp here: it corrupts %~dp0 when the path contains non-ASCII.
setlocal
set "PYEXE="
set "RUNTIME=%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"

for %%P in (python.exe) do if not defined PYEXE if exist "%%~$PATH:P" set "PYEXE=%%~$PATH:P"
if defined PYEXE (
  "%PYEXE%" -c "import yaml" >nul 2>nul
  if errorlevel 1 set "PYEXE="
)
if not defined PYEXE if exist "%RUNTIME%" set "PYEXE=%RUNTIME%"

if not defined PYEXE goto :nopython
"%PYEXE%" -c "import yaml" >nul 2>nul
if errorlevel 1 goto :noyaml

"%PYEXE%" "%~dp0run_demo.py" %*
if errorlevel 1 pause
endlocal
exit /b 0

:nopython
echo.
echo   [ERROR] Python not found.
echo   Install Python 3.9+ and check "Add Python to PATH", then run again.
echo.
pause
exit /b 1

:noyaml
echo.
echo   [ERROR] PyYAML is not installed for:
echo   %PYEXE%
echo.
echo   Run:  "%PYEXE%" -m pip install pyyaml
echo.
pause
exit /b 1
