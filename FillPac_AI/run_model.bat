@echo off
setlocal
title FillPac AI Launcher

REM ==========================================================
REM FillPac AI
REM Production Application + Dashboard Launcher
REM ==========================================================

cd /d "%~dp0"

echo.
echo ==========================================================
echo                 FILLPAC AI
echo        Production Vision System Launcher
echo ==========================================================
echo.

REM ==========================================================
REM PYTHON ENVIRONMENT
REM ==========================================================

set "PYTHON_CMD=python"

set "IMPORT_CHECK=import cv2, ultralytics, torch, supervision, yaml, fastapi, socketio, uvicorn"


REM ==========================================================
REM CHECK PARENT VIRTUAL ENVIRONMENT
REM ==========================================================

if exist "..\.venv\Scripts\python.exe" (

    "..\.venv\Scripts\python.exe" -c "%IMPORT_CHECK%" >nul 2>nul

    if not errorlevel 1 (

        set "PYTHON_CMD=..\.venv\Scripts\python.exe"

    )

)


REM ==========================================================
REM CHECK LOCAL VIRTUAL ENVIRONMENT
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

    echo [ERROR] Required Python packages are missing.
    echo.
    echo Install dependencies using:
    echo.
    echo %PYTHON_CMD% -m pip install -r requirements.txt
    echo.

    pause

    exit /b 1

)


echo [OK] Python environment found:
echo %PYTHON_CMD%
echo.


REM ==========================================================
REM START DASHBOARD BACKEND
REM ==========================================================

echo [1/3] Starting Dashboard Backend...

start "FillPac AI - Dashboard Backend" cmd /k ^
"%PYTHON_CMD% -m uvicorn dashboard.backend.server:app --host 0.0.0.0 --port 8000"

echo Dashboard Backend:
echo http://localhost:8000
echo.


REM ==========================================================
REM WAIT FOR BACKEND STARTUP
REM ==========================================================

timeout /t 2 /nobreak >nul


REM ==========================================================
REM START DASHBOARD FRONTEND
REM ==========================================================

echo [2/3] Starting Dashboard Frontend...

start "FillPac AI - Dashboard Frontend" cmd /k ^
"%PYTHON_CMD% -m http.server 8080 --directory dashboard/frontend"

echo Dashboard Frontend:
echo http://localhost:8080
echo.


REM ==========================================================
REM WAIT FOR FRONTEND STARTUP
REM ==========================================================

timeout /t 2 /nobreak >nul


REM ==========================================================
REM OPEN DASHBOARD
REM ==========================================================

echo Opening FillPac AI Dashboard...

start "" "http://localhost:8080"


REM ==========================================================
REM START MAIN AI APPLICATION
REM ==========================================================

echo.
echo [3/3] Starting FillPac AI Vision Application...
echo.

%PYTHON_CMD% main.py


REM ==========================================================
REM APPLICATION EXIT HANDLING
REM ==========================================================

if errorlevel 1 (

    echo.
    echo ==========================================================
    echo [ERROR] FillPac AI stopped with an error.
    echo ==========================================================
    echo.

    pause

) else (

    echo.
    echo ==========================================================
    echo FillPac AI application stopped.
    echo ==========================================================

)


endlocal