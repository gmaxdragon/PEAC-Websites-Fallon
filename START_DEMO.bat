@echo off
setlocal
cd /d "%~dp0"
where py >nul 2>nul
if errorlevel 1 goto fail
if not exist .venv\Scripts\python.exe (
  py -3 -m venv .venv
  if errorlevel 1 goto fail
)
.venv\Scripts\python.exe -c "import numpy, openpyxl; from zoneinfo import ZoneInfo; ZoneInfo('America/Los_Angeles')" >nul 2>nul
if errorlevel 1 (
  .venv\Scripts\python.exe -m pip install -r requirements-core.txt -r requirements-excel.txt
  if errorlevel 1 goto fail
)
echo.
echo PEAC v5 SYNTHETIC LOCAL DEMO
echo This uses data\demo.sqlite3 and never touches data\peac.sqlite3.
echo On first launch you will create a separate demo admin login.
echo.
.venv\Scripts\python.exe demo_seed.py --db data\demo.sqlite3
if errorlevel 1 goto fail
.venv\Scripts\python.exe peac.py --local-server --db data\demo.sqlite3
if errorlevel 1 goto fail
exit /b 0
:fail
echo.
echo Demo could not start. Read the error above.
pause
exit /b 1
