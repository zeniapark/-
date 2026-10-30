@echo off
setlocal
cd /d "%~dp0"

where py >nul 2>nul
if errorlevel 1 (
  echo [HANARO] Python 3 is required.
  pause
  exit /b 1
)

set "CS_DB=%CD%\data\cs.sqlite3"
py -3 backup.py
if errorlevel 1 (
  echo [HANARO] Backup failed.
  pause
  exit /b 1
)

echo [HANARO] Backup complete. Check the backups folder.
pause
