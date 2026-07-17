@echo off
setlocal

cd /d "%~dp0"

set "PYTHON_CMD=python"
set "IMPORT_CHECK=import cv2, ultralytics, torch, supervision, yaml"

if exist "..\.venv\Scripts\python.exe" (
    "..\.venv\Scripts\python.exe" -c "%IMPORT_CHECK%" >nul 2>nul
    if not errorlevel 1 (
        set "PYTHON_CMD=..\.venv\Scripts\python.exe"
    )
)

if "%PYTHON_CMD%"=="python" if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" -c "%IMPORT_CHECK%" >nul 2>nul
    if not errorlevel 1 (
        set "PYTHON_CMD=.venv\Scripts\python.exe"
    )
)

%PYTHON_CMD% -c "%IMPORT_CHECK%" >nul 2>nul
if errorlevel 1 (
    echo Required Python packages are not installed in the selected environment.
    echo Install dependencies with:
    echo python -m pip install -r requirements.txt
    echo.
    pause
    exit /b 1
)

echo Starting FillPac AI with %PYTHON_CMD%
%PYTHON_CMD% main.py

if errorlevel 1 (
    echo.
    echo FillPac AI stopped with an error.
    pause
)

endlocal
