@echo off
rem Build Minerva.exe on this computer: the same steps the GitHub build runs,
rem for when GitHub Actions isn't available. Needs Python 3.10 or newer (3.12
rem is what the GitHub build uses) installed with "Add python.exe to PATH".
cd /d "%~dp0"
echo Installing what the build needs...
python -m pip install --quiet --disable-pip-version-check -r requirements-dev.txt
if errorlevel 1 goto nopython
echo.
echo Running the tests...
python -m pytest -q
if errorlevel 1 goto failed
echo.
echo Building Minerva.exe. This takes a few minutes...
python packaging\build.py
if errorlevel 1 goto failed
echo.
echo Checking the built app...
start "" /wait dist\Minerva.exe --selftest
if errorlevel 1 goto failed
echo.
echo Done: %CD%\dist\Minerva.exe
explorer /select,"%CD%\dist\Minerva.exe"
pause
exit /b 0
:nopython
echo.
echo Could not install what the build needs. Make sure Python 3.10+ is installed
echo and on PATH (python.org, tick "Add python.exe to PATH"), then run this again.
pause
exit /b 1
:failed
echo.
echo The build stopped at the step above. Copy what it says and send it over.
pause
exit /b 1
