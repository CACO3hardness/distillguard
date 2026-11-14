@echo off
chcp 65001 >nul
setlocal
set "PYEXE="

for %%P in (python.exe) do if not defined PYEXE if exist "%%~$PATH:P" set "PYEXE=%%~$PATH:P"
if not defined PYEXE if exist "%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" set "PYEXE=%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"

if not defined PYEXE (
  echo.
  echo   [错误] 找不到 Python。请安装 Python 3.9+ 并勾选 Add Python to PATH。
  echo.
  pause
  exit /b 1
)

"%PYEXE%" "%~dp0run_demo.py" %*
if errorlevel 1 pause
endlocal
