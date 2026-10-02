@echo off
rem M9 first Codex LIVE proof (one shot). Run on the user's Windows PC only.
rem Starting this file never starts LIVE by itself: the Python runner asks for a typed confirmation.
setlocal
chcp 65001 >nul
set PYTHONUTF8=1
set "PYTHONPATH=%~dp0src"
set "PYEXE="
where py >nul 2>nul && set "PYEXE=py -3"
if not defined PYEXE (where python >nul 2>nul && set "PYEXE=python")
if not defined PYEXE (
  echo Python 3.11 or newer was not found. Install Python, then run this file again.
  pause
  exit /b 2
)
%PYEXE% -c "import sys; sys.exit(0 if sys.version_info[:2] >= (3, 11) else 1)"
if errorlevel 1 (
  echo Python 3.11 or newer is required. Install it, then run this file again.
  pause
  exit /b 2
)
cd /d "%~dp0"
%PYEXE% -m relay.m9_codex_first_live
set "RC=%ERRORLEVEL%"
echo.
echo (exit code: %RC%)
pause
exit /b %RC%
