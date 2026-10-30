@echo off
setlocal
cd /d "%~dp0"

where py >nul 2>nul
if errorlevel 1 (
  echo [HANARO] Python 3 is required.
  echo Download it from https://www.python.org/downloads/windows/
  echo During installation, select "Add python.exe to PATH".
  pause
  exit /b 1
)

if not exist data mkdir data
set "CS_DB=%CD%\data\cs.sqlite3"
set "PORT=3000"

echo.
echo [HANARO] Starting CS Insight...
echo [HANARO] This window must remain open while the site is in use.
echo [HANARO] On this PC: http://localhost:3000
echo [HANARO] Other office PCs: use this PC's IPv4 address with :3000
echo [HANARO] Press Ctrl+C to stop.
echo.
py -3 app.py

echo.
echo [HANARO] The server has stopped.
pause
