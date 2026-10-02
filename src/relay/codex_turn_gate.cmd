@echo off
rem Relay one-generation gate launcher for Windows (CODEX_PATH target).
rem codex-acp runs: "<this file>" app-server   (through cmd.exe, shell mode)
setlocal
if defined RELAY_GATE_PYTHON (set "RELAY_PY=%RELAY_GATE_PYTHON%") else (set "RELAY_PY=python")
"%RELAY_PY%" "%~dp0codex_turn_gate.py" %*
exit /b %ERRORLEVEL%
