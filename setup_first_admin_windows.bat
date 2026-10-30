@echo off
setlocal
cd /d "%~dp0"

where py >nul 2>nul
if errorlevel 1 (
  echo [HANARO] Python 3 is required.
  echo Download it from https://www.python.org/downloads/windows/
  pause
  exit /b 1
)

if not exist data mkdir data
set "CS_DB=%CD%\data\cs.sqlite3"
set /p "ADMIN_EMAIL=First administrator email: "
if "%ADMIN_EMAIL%"=="" (
  echo [HANARO] Email is required.
  pause
  exit /b 1
)

echo.
py -3 manage.py invite "%ADMIN_EMAIL%" --admin
if errorlevel 1 (
  echo.
  echo [HANARO] If this account already exists, approve it with:
  echo py -3 manage.py approve "%ADMIN_EMAIL%" --admin
  pause
  exit /b 1
)

echo.
echo [HANARO] Copy the invitation_token shown above.
echo [HANARO] Start the site, open the signup screen, and enter that token once.
echo [HANARO] Do not share the administrator invitation token.
pause
