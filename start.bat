@echo off
rem One-click start for Windows: creates the virtual environment on first
rem run, then starts collector + dashboard and opens the browser.
rem Sources and search terms come from .env (SS_RUN_SOURCES, SS_TRACK_TERMS).
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo First run: creating virtual environment and installing dependencies...
    python -m venv .venv || goto :error
    .venv\Scripts\python.exe -m pip install -r requirements.txt || goto :error
)
.venv\Scripts\python.exe -m socialsentiment run
goto :end
:error
echo.
echo Setup failed. Is Python 3.10+ installed and on PATH?
:end
echo.
pause
