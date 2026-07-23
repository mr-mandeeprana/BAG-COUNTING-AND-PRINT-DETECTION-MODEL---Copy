@echo off
setlocal EnableDelayedExpansion
title FillPac AI Launcher

REM ==========================================================
REM FillPac AI
REM Production Vision System Launcher
REM ==========================================================

cd /d "%~dp0"

echo.
echo ==========================================================
echo                 FILLPAC AI
echo          Production Vision System Launcher
echo ==========================================================
echo.

REM ==========================================================
REM PYTHON ENVIRONMENT
REM ==========================================================

set "PYTHON_CMD=python"

set "IMPORT_CHECK=import cv2, ultralytics, torch, supervision, yaml, fastapi, socketio, uvicorn"

REM ==========================================================
REM CHECK PARENT VENV
REM ==========================================================

if exist "..\.venv\Scripts\python.exe" (

    "..\.venv\Scripts\python.exe" -c "%IMPORT_CHECK%" >nul 2>nul

    if not errorlevel 1 (
        set "PYTHON_CMD=..\.venv\Scripts\python.exe"
    )
)

REM ==========================================================
REM CHECK LOCAL VENV
REM ==========================================================

if "%PYTHON_CMD%"=="python" (

    if exist ".venv\Scripts\python.exe" (

        ".venv\Scripts\python.exe" -c "%IMPORT_CHECK%" >nul 2>nul

        if not errorlevel 1 (
            set "PYTHON_CMD=.venv\Scripts\python.exe"
        )

    )

)

REM ==========================================================
REM VERIFY DEPENDENCIES
REM ==========================================================

%PYTHON_CMD% -c "%IMPORT_CHECK%" >nul 2>nul

if errorlevel 1 (

    echo.
    echo ============================================
    echo ERROR: Required Python packages missing
    echo ============================================
    echo.
    echo Install using:
    echo.
    echo %PYTHON_CMD% -m pip install -r requirements.txt
    echo.
    pause
    exit /b 1
)

echo [OK] Python:
echo %PYTHON_CMD%
echo.

REM ==========================================================
REM START DASHBOARD BACKEND
REM ==========================================================

echo [1/3] Starting Dashboard Backend...

start "FillPac AI - Dashboard Backend" cmd /k ^
"%PYTHON_CMD% -m uvicorn dashboard.backend.server:app --host 0.0.0.0 --port 8000 --workers 1 --log-level warning"

echo Waiting for backend...

:WAIT_BACKEND

curl http://127.0.0.1:8000/health >nul 2>nul

if errorlevel 1 (

    timeout /t 1 >nul
    goto WAIT_BACKEND

)

echo Backend Ready.
echo.

REM ==========================================================
REM START FRONTEND
REM ==========================================================

echo [2/3] Starting Dashboard Frontend...

start "FillPac AI - Dashboard Frontend" cmd /k ^
"%PYTHON_CMD% -m http.server 8080 --directory dashboard/frontend"

echo Waiting for frontend...

:WAIT_FRONTEND

curl http://127.0.0.1:8080 >nul 2>nul

if errorlevel 1 (

    timeout /t 1 >nul
    goto WAIT_FRONTEND

)

echo Frontend Ready.
echo.

REM ==========================================================
REM OPEN DASHBOARD
REM ==========================================================

echo Opening Dashboard...

start "" http://localhost:8080

echo.

REM ==========================================================
REM START AI APPLICATION
REM ==========================================================

echo [3/3] Starting FillPac AI...
echo.

%PYTHON_CMD% main.py

set EXITCODE=%ERRORLEVEL%

echo.
echo ==========================================================
echo Main AI application stopped.
echo ==========================================================
echo.

REM ==========================================================
REM SHUTDOWN DASHBOARD
REM ==========================================================

echo Stopping Dashboard Backend...

taskkill /FI "WINDOWTITLE eq FillPac AI - Dashboard Backend*" /F >nul 2>nul

echo Stopping Dashboard Frontend...

taskkill /FI "WINDOWTITLE eq FillPac AI - Dashboard Frontend*" /F >nul 2>nul

echo.

if "%EXITCODE%"=="0" (

    echo ============================================
    echo FillPac AI Closed Successfully
    echo ============================================

) else (

    echo ============================================
    echo FillPac AI Closed With Error (%EXITCODE%)
    echo ============================================

)

echo.
pause

endlocal
exit /b %EXITCODE%