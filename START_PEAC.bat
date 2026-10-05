@echo off
setlocal
cd /d "%~dp0"
where py >nul 2>nul
if errorlevel 1 (set "PYTHON=python") else (set "PYTHON=py -3")
if not exist ".venv\Scripts\python.exe" (
  %PYTHON% -m venv .venv
  if errorlevel 1 goto fail
)
.venv\Scripts\python.exe -c "import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)"
if errorlevel 1 goto fail
.venv\Scripts\python.exe -c "import numpy, openpyxl; from zoneinfo import ZoneInfo; ZoneInfo('America/Los_Angeles')" >nul 2>nul
if errorlevel 1 (
  .venv\Scripts\python.exe -m pip install -r requirements-core.txt -r requirements-excel.txt
  if errorlevel 1 goto fail
)
echo.
echo PEAC Community v5
echo Create your administrator account at the first start. Password input is hidden.
echo Public preview: http://127.0.0.1:5000/
echo Private console: http://127.0.0.1:5000/console
echo.
.venv\Scripts\python.exe peac.py --local-server
if errorlevel 1 goto fail
exit /b 0
:fail
echo.
echo PEAC could not start. Read the error above. Python 3.10+ and an internet connection are needed for first-time setup.
echo Existing school records were not intentionally reset. Keep a backup before upgrades.
pause
exit /b 1
