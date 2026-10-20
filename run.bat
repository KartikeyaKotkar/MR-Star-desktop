@echo off
setlocal
cd /d "%~dp0"

set "PYTHON=py -3"
where py >nul 2>nul
if errorlevel 1 (
    set "PYTHON=python"
    where python >nul 2>nul
    if errorlevel 1 (
        echo Python 3.10 or newer is required. Install it from https://www.python.org/downloads/
        exit /b 1
    )
)

if not exist ".venv\Scripts\python.exe" (
    echo Creating .venv...
    %PYTHON% -m venv .venv
    if errorlevel 1 exit /b 1
)

".venv\Scripts\python.exe" -c "import PySide6, bleak, numpy, sounddevice" >nul 2>nul
if errorlevel 1 (
    echo Installing Python dependencies...
    ".venv\Scripts\python.exe" -m pip install -r requirements.txt
    if errorlevel 1 exit /b 1
)

where ffmpeg >nul 2>nul
if errorlevel 1 echo warning: ffmpeg was not found; music playback will be unavailable.

".venv\Scripts\python.exe" -m mrstar %*
