@echo off
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0run_external_windows.ps1"
if errorlevel 1 (
  echo.
  echo [HANARO] External connection stopped with an error.
  pause
)
