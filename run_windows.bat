@echo off
setlocal
cd /d "%~dp0"

where py >nul 2>nul
if %errorlevel%==0 (
    set PYTHON=py -3.11
) else (
    set PYTHON=python
)

if not exist .venv (
    %PYTHON% -m venv .venv || goto :error
)

call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
python -m pip install -r requirements.txt || goto :error
python main.py
goto :eof

:error
echo.
echo Setup or launch failed. Confirm Python 3.11+ is installed.
pause
