@echo off
rem Runs the Internship Watch on its own, without Docker:
rem   installs its Python packages (first run), starts the app and its
rem   background worker on http://127.0.0.1:8700/, and opens the browser.
rem Data is kept in the "data" folder next to this file.
rem
rem   start.bat --no-browser     start without opening the browser
setlocal
cd /d "%~dp0"

where python >nul 2>nul
if errorlevel 1 (
  echo Python 3.11 or newer is needed: https://www.python.org/downloads/
  exit /b 1
)

if not exist data\.installed (
  echo Installing packages...
  python -m pip install --quiet -r requirements.txt || exit /b 1
  if not exist data mkdir data
  echo ok> data\.installed
)

if exist .env (
  for /f "usebackq eol=# tokens=1,* delims==" %%a in (".env") do if not "%%b"=="" set "%%a=%%b"
)
if "%INTERNSHIPS_HOST%"=="" set INTERNSHIPS_HOST=127.0.0.1

echo Internship Watch: http://127.0.0.1:8700/
if /i not "%~1"=="--no-browser" start "" cmd /c "timeout /t 3 >nul & start http://127.0.0.1:8700/"
python serve.py
