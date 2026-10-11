@echo off
rem Run Minerva from source (the downloadable Minerva.exe doesn't need this).
cd /d "%~dp0"
echo Checking dependencies...
python -m pip install --quiet --disable-pip-version-check -r requirements.txt
if errorlevel 1 (
  echo.
  echo Could not install dependencies. Make sure Python 3.10+ is installed and on PATH,
  echo then try running:  python -m pip install -r requirements.txt
  pause
  exit /b 1
)
python run_minerva.py %*
