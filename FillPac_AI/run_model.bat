@echo off
setlocal EnableDelayedExpansion
title FillPac AI Launcher

REM ==========================================================
REM FILLPAC AI
REM Production Vision System + Dashboard Launcher
REM ==========================================================

REM Always work from the folder containing this BAT file
cd /d "%~dp0"

echo.
echo ==========================================================
echo                     FILLPAC AI
echo          Production Vision System Launcher
echo ==========================================================
echo.

REM ==========================================================
REM PYTHON ENVIRONMENT
REM ==========================================================

set "PYTHON_CMD=python"

echo Checking Python dependencies...

python -c "import cv2, ultralytics, torch, supervision, yaml, fastapi, socketio, uvicorn" >nul 2>nul

if errorlevel 1 (

    if exist ".\venv\Scripts\python.exe" (
        set "PYTHON_CMD=.\venv\Scripts\python.exe"
    ) else (
        if exist ".\.venv\Scripts\python.exe" (
            set "PYTHON_CMD=.\.venv\Scripts\python.exe"
        )
    )
)

REM ==========================================================
REM VERIFY PYTHON
REM ==========================================================

%PYTHON_CMD% --version >nul 2>nul

if errorlevel 1 (

    echo.
    echo ==========================================================
    echo ERROR: Python could not be found
    echo ==========================================================
    echo.

    echo Current directory:
    cd
    echo.

    pause
    exit /b 1
)

echo [OK] Python environment ready.
echo [OK] Required packages available.
echo.
echo Python:
echo %PYTHON_CMD%
echo.

REM ==========================================================
REM VERIFY MAIN APPLICATION
REM ==========================================================

if not exist "main.py" (

    echo.
    echo ==========================================================
    echo ERROR: main.py not found
    echo ==========================================================
    echo.

    echo Current directory:
    cd
    echo.

    pause
    exit /b 1
)

echo [OK] main.py found.

REM ==========================================================
REM VERIFY CONFIGURATION
REM ==========================================================

if not exist "config.yaml" (

    echo.
    echo ==========================================================
    echo ERROR: config.yaml not found
    echo ==========================================================
    echo.

    pause
    exit /b 1
)

echo [OK] config.yaml found.

REM ==========================================================
REM VERIFY CORE SOURCE FILES
REM ==========================================================

if not exist "src\pipeline.py" (

    echo.
    echo ==========================================================
    echo ERROR: src\pipeline.py not found
    echo ==========================================================
    echo.

    pause
    exit /b 1
)

if not exist "src\camera.py" (

    echo.
    echo ==========================================================
    echo ERROR: src\camera.py not found
    echo ==========================================================
    echo.

    pause
    exit /b 1
)

if not exist "src\tracker.py" (

    echo.
    echo ==========================================================
    echo ERROR: src\tracker.py not found
    echo ==========================================================
    echo.

    pause
    exit /b 1
)

if not exist "src\counter.py" (

    echo.
    echo ==========================================================
    echo ERROR: src\counter.py not found
    echo ==========================================================
    echo.

    pause
    exit /b 1
)

if not exist "src\print_detector.py" (

    echo.
    echo ==========================================================
    echo ERROR: src\print_detector.py not found
    echo ==========================================================
    echo.

    pause
    exit /b 1
)

if not exist "src\visualizer.py" (

    echo.
    echo ==========================================================
    echo ERROR: src\visualizer.py not found
    echo ==========================================================
    echo.

    pause
    exit /b 1
)

echo [OK] Core vision modules found.

REM ==========================================================
REM VERIFY JAM DETECTOR
REM ==========================================================

if not exist "src\jam_detector.py" (

    echo.
    echo ==========================================================
    echo ERROR: src\jam_detector.py not found
    echo ==========================================================
    echo.

    echo Jam Detection V1 cannot start.
    echo.

    pause
    exit /b 1
)

echo [OK] Jam Detector V1 found.

REM ==========================================================
REM SOURCE IMPORT TEST
REM ==========================================================

echo.
echo Checking FillPac AI source imports...

%PYTHON_CMD% -c "from src.pipeline import Pipeline; from src.jam_detector import JamDetector; from src.visualizer import Visualizer; print('Source imports OK')" >nul 2>nul

if errorlevel 1 (

    echo.
    echo ==========================================================
    echo ERROR: FillPac AI source import check failed
    echo ==========================================================
    echo.

    echo Run this command for the complete traceback:
    echo.
    echo %PYTHON_CMD% -c "from src.pipeline import Pipeline; from src.jam_detector import JamDetector; from src.visualizer import Visualizer"
    echo.

    pause
    exit /b 1
)

echo [OK] Pipeline import successful.
echo [OK] JamDetector import successful.
echo [OK] Visualizer import successful.

REM ==========================================================
REM CONFIG YAML TEST
REM ==========================================================

echo.
echo Checking config.yaml syntax...

%PYTHON_CMD% -c "import yaml; yaml.safe_load(open('config.yaml','r',encoding='utf-8')); print('Config OK')" >nul 2>nul

if errorlevel 1 (

    echo.
    echo ==========================================================
    echo ERROR: config.yaml could not be parsed
    echo ==========================================================
    echo.

    pause
    exit /b 1
)

echo [OK] config.yaml syntax valid.

REM ==========================================================
REM VERIFY DASHBOARD
REM
REM IMPORTANT:
REM run_model.bat is inside FillPac_AI.
REM Therefore dashboard paths are:
REM
REM dashboard\backend
REM dashboard\frontend
REM
REM NOT:
REM
REM FillPac_AI\dashboard
REM ==========================================================

if not exist "dashboard\backend\server.py" (

    echo.
    echo ==========================================================
    echo ERROR: dashboard\backend\server.py not found
    echo ==========================================================
    echo.

    echo Expected:
    echo %CD%\dashboard\backend\server.py
    echo.

    pause
    exit /b 1
)

if not exist "dashboard\frontend\index.html" (

    echo.
    echo ==========================================================
    echo ERROR: dashboard\frontend\index.html not found
    echo ==========================================================
    echo.

    echo Expected:
    echo %CD%\dashboard\frontend\index.html
    echo.

    pause
    exit /b 1
)

if not exist "dashboard\frontend\js\dashboard.js" (

    echo.
    echo ==========================================================
    echo ERROR: dashboard\frontend\js\dashboard.js not found
    echo ==========================================================
    echo.

    echo Expected:
    echo %CD%\dashboard\frontend\js\dashboard.js
    echo.

    pause
    exit /b 1
)

echo [OK] Dashboard backend found.
echo [OK] Dashboard frontend found.
echo [OK] Dashboard JavaScript found.

REM ==========================================================
REM CREATE RUNTIME DIRECTORIES
REM ==========================================================

if not exist "logs" (
    mkdir "logs"
)

if not exist "data" (
    mkdir "data"
)

if not exist "data\output" (
    mkdir "data\output"
)

echo [OK] Runtime directories ready.

REM ==========================================================
REM CHECK PORT 8000
REM ==========================================================

echo.
echo Checking dashboard API port 8000...

netstat -ano | findstr ":8000 " | findstr "LISTENING" >nul 2>nul

if not errorlevel 1 (

    echo.
    echo ==========================================================
    echo ERROR: Port 8000 is already in use
    echo ==========================================================
    echo.

    netstat -ano | findstr ":8000 "

    echo.
    echo Stop the existing process and run this launcher again.
    echo.

    pause
    exit /b 1
)

echo [OK] Port 8000 available.

REM ==========================================================
REM CHECK PORT 8080
REM ==========================================================

echo Checking dashboard frontend port 8080...

netstat -ano | findstr ":8080 " | findstr "LISTENING" >nul 2>nul

if not errorlevel 1 (

    echo.
    echo ==========================================================
    echo ERROR: Port 8080 is already in use
    echo ==========================================================
    echo.

    netstat -ano | findstr ":8080 "

    echo.
    echo Stop the existing dashboard and run this launcher again.
    echo.

    pause
    exit /b 1
)

echo [OK] Port 8080 available.
echo.

REM ==========================================================
REM START FRONTEND
REM
REM THIS IS THE IMPORTANT FIX
REM ==========================================================

echo ==========================================================
echo Starting FillPac AI services
echo ==========================================================
echo.

echo [1/2] Starting Dashboard Frontend...

start "FillPac AI - Dashboard Frontend" cmd /c ^
"%PYTHON_CMD% -m http.server 8080 --bind 127.0.0.1 --directory dashboard/frontend"

REM ==========================================================
REM WAIT FOR FRONTEND
REM ==========================================================

echo Waiting for dashboard frontend...

set /a FRONTEND_ATTEMPTS=0

:WAIT_FRONTEND

curl --silent --fail http://127.0.0.1:8080/ >nul 2>nul

if not errorlevel 1 (
    goto FRONTEND_READY
)

set /a FRONTEND_ATTEMPTS+=1

if !FRONTEND_ATTEMPTS! GEQ 20 (

    echo.
    echo ==========================================================
    echo ERROR: Dashboard frontend failed to start
    echo ==========================================================
    echo.

    pause
    exit /b 1
)

timeout /t 1 /nobreak >nul

goto WAIT_FRONTEND

:FRONTEND_READY

echo [OK] Dashboard frontend ready.
echo.

REM ==========================================================
REM START MAIN APPLICATION
REM ==========================================================

echo [2/2] Starting FillPac AI...
echo.

REM ==========================================================
REM OPEN NEW DASHBOARD
REM ==========================================================

start "" http://127.0.0.1:8080/

REM ==========================================================
REM DISPLAY URLS
REM ==========================================================

echo ==========================================================
echo                   FillPac AI Runtime
echo ==========================================================
echo.

echo Dashboard UI:
echo     http://127.0.0.1:8080/
echo.

echo Dashboard API:
echo     http://127.0.0.1:8000/
echo.

echo Health API:
echo     http://127.0.0.1:8000/health
echo.

echo ==========================================================
echo                    DASHBOARD SOURCE
echo ==========================================================
echo.

echo Frontend:
echo     %CD%\dashboard\frontend\index.html
echo.

echo JavaScript:
echo     %CD%\dashboard\frontend\js\dashboard.js
echo.

echo Backend:
echo     %CD%\dashboard\backend\server.py
echo.

echo ==========================================================
echo                    COUNTING DISPLAY
echo ==========================================================
echo.

echo Dashboard should show:
echo.
echo     Line Count
echo     Frame ROI Count
echo     Bags Inside ROI
echo     ROI Track IDs
echo     Printed Bags
echo     Missing Bags
echo     Jam Status
echo.

echo ==========================================================
echo.

REM ==========================================================
REM RUN MAIN APPLICATION
REM ==========================================================

%PYTHON_CMD% main.py

set "EXITCODE=%ERRORLEVEL%"

REM ==========================================================
REM APPLICATION STOPPED
REM ==========================================================

echo.
echo ==========================================================
echo FillPac AI application stopped.
echo ==========================================================
echo.

REM ==========================================================
REM STOP FRONTEND
REM ==========================================================

echo Stopping Dashboard Frontend...

taskkill /FI "WINDOWTITLE eq FillPac AI - Dashboard Frontend*" /F >nul 2>nul

echo [OK] Dashboard frontend stopped.
echo.

REM ==========================================================
REM FINAL STATUS
REM ==========================================================

if "%EXITCODE%"=="0" (

    echo ==========================================================
    echo        FillPac AI Closed Successfully
    echo ==========================================================

) else (

    echo ==========================================================
    echo        FillPac AI Closed With Error (%EXITCODE%)
    echo ==========================================================

    echo.
    echo Check the traceback above.
    echo.
    echo Logs:
    echo     %CD%\logs\
)

echo.

pause

endlocal
exit /b %EXITCODE%