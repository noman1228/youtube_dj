@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\pyside6-designer.exe" (
    echo PySide6 Designer was not found in .venv. Set up the project environment first.
    pause
    exit /b 1
)
if "%~1"=="" (
    ".venv\Scripts\pyside6-designer.exe" "app\ui\main_window.ui" "app\ui\deck.ui" "app\ui\karaoke_window.ui"
) else (
    ".venv\Scripts\pyside6-designer.exe" %*
)
