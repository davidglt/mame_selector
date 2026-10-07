@echo off
setlocal
cd /d "%~dp0"
set "PYTHON_EXE=python"
if exist "%~dp0.venv\Scripts\python.exe" set "PYTHON_EXE=%~dp0.venv\Scripts\python.exe"
"%PYTHON_EXE%" "%~dp0mame_selector.py"
if errorlevel 1 (
    echo ERROR: MAME Selector could not run.
    echo Install dependencies with: "%PYTHON_EXE%" -m pip install -r requirements.txt
    pause
)
endlocal
