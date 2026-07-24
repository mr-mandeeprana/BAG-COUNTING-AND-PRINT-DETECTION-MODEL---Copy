@echo off
setlocal EnableDelayedExpansion
title FillPac AI Launcher

REM ==========================================================
REM FillPac AI
REM Production Vision System + Dashboard Launcher
REM ==========================================================

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
REM VERIFY PYTHON
REM ==========================================================

%PYTHON_CMD% --version >nul 2>nul

if errorlevel 1 (

    echo.
    echo ==========================================================
    echo ERROR: Python could not be found
    echo ==========================================================
    echo.
    echo Install Python or create the project virtual environment.
    echo.
    pause
    exit /b 1
)

REM ==========================================================
REM VERIFY REQUIRED DEPENDENCIES
REM ==========================================================

echo Checking Python dependencies...

%PYTHON_CMD% -c "%IMPORT_CHECK%" >nul 2>nul

if errorlevel 1 (

    echo.
    echo ==========================================================
    echo ERROR: Required Python packages are missing
    echo ==========================================================
    echo.
    echo Python:
    echo %PYTHON_CMD%
    echo.
    echo Install dependencies using:
    echo.
    echo %PYTHON_CMD% -m pip install -r requirements.txt
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
REM VERIFY PYTHON SOURCE IMPORTS
REM
REM This catches syntax/import errors before starting the
REM frontend and production application.
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
    echo Possible causes:
    echo   - Python syntax error
    echo   - Missing Python module
    echo   - Invalid JamDetector import
    echo   - Invalid Pipeline import
    echo   - Invalid Visualizer import
    echo.
    echo Run this command manually for the full traceback:
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
REM VERIFY CONFIG YAML PARSING
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
    echo Check YAML indentation and syntax.
    echo.
    echo Run:
    echo.
    echo %PYTHON_CMD% -c "import yaml; print(yaml.safe_load(open('config.yaml','r',encoding='utf-8')))"
    echo.
    pause
    exit /b 1
)

echo [OK] config.yaml syntax valid.

REM ==========================================================
REM VERIFY DASHBOARD FILES
REM ==========================================================

if not exist "dashboard\backend\server.py" (

    echo.
    echo ==========================================================
    echo ERROR: dashboard\backend\server.py not found
    echo ==========================================================
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
    pause
    exit /b 1
)

echo [OK] Dashboard files found.

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

if not exist "dashboard\backend" (
    mkdir "dashboard\backend"
)

echo [OK] Runtime directories ready.

REM ==========================================================
REM PORT CHECK - BACKEND
REM
REM main.py owns port 8000.
REM We must NOT start another Uvicorn process.
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
    echo Another FillPac dashboard/Uvicorn instance may
    echo already be running.
    echo.
    echo Process information:
    echo.

    netstat -ano | findstr ":8000 "

    echo.
    echo Close the existing process and run this launcher again.
    echo.
    pause
    exit /b 1
)

echo [OK] Port 8000 available.

REM ==========================================================
REM PORT CHECK - FRONTEND
REM ==========================================================

echo Checking dashboard frontend port 8080...

netstat -ano | findstr ":8080 " | findstr "LISTENING" >nul 2>nul

if not errorlevel 1 (

    echo.
    echo ==========================================================
    echo ERROR: Port 8080 is already in use
    echo ==========================================================
    echo.
    echo Another dashboard frontend may already be running.
    echo.
    echo Process information:
    echo.

    netstat -ano | findstr ":8080 "

    echo.
    echo Close the existing process and run this launcher again.
    echo.
    pause
    exit /b 1
)

echo [OK] Port 8080 available.
echo.

REM ==========================================================
REM START FRONTEND
REM
REM FastAPI backend is NOT started here.
REM main.py starts it internally so it shares memory with the
REM camera Pipeline objects required by Live Monitor.
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

    taskkill /FI "WINDOWTITLE eq FillPac AI - Dashboard Frontend*" /F >nul 2>nul

    pause
    exit /b 1
)

timeout /t 1 /nobreak >nul

goto WAIT_FRONTEND


:FRONTEND_READY

echo [OK] Dashboard frontend ready.
echo.

REM ==========================================================
REM START FILLPAC AI
REM
REM main.py starts:
REM
REM   Application
REM   Detector
REM   InferenceManager
REM   Camera pipelines
REM   Tracker
REM   Physical-center Counter
REM   PrintDetector
REM   JamDetector V1
REM   DashboardState
REM   FastAPI
REM   Socket.IO
REM   Live camera endpoints
REM
REM DO NOT start Uvicorn separately.
REM ==========================================================

echo [2/2] Starting FillPac AI...
echo.

REM ==========================================================
REM OPEN DASHBOARD
REM ==========================================================

start "" http://127.0.0.1:8080

REM ==========================================================
REM RUNTIME INFORMATION
REM ==========================================================

echo ==========================================================
echo                   FillPac AI Runtime
echo ==========================================================
echo.
echo Dashboard UI:
echo     http://127.0.0.1:8080
echo.
echo Dashboard API:
echo     http://127.0.0.1:8000
echo.
echo Health API:
echo     http://127.0.0.1:8000/health
echo.
echo ----------------------------------------------------------
echo Live Camera Streams
echo ----------------------------------------------------------
echo.
echo Camera 1:
echo     http://127.0.0.1:8000/live/Camera%%201
echo.
echo Camera 2:
echo     http://127.0.0.1:8000/live/Camera%%202
echo.
echo Camera 3:
echo     http://127.0.0.1:8000/live/Camera%%203
echo.
echo Camera 4:
echo     http://127.0.0.1:8000/live/Camera%%204
echo.
echo ----------------------------------------------------------
echo Jam Detection V1
echo ----------------------------------------------------------
echo.
echo Algorithm:
echo     Bag center trajectory
echo          +
echo     Euclidean movement
echo          +
echo     Speed px/s
echo          +
echo     Stationary duration
echo.
echo States:
echo     NORMAL
echo     SLOW
echo     WARNING
echo     JAM
echo     RECOVERING
echo.
echo Jam detection is independent from bag counting.
echo.
echo Physical bag-center crossing remains the counting trigger.
echo.
echo ----------------------------------------------------------
echo Controls
echo ----------------------------------------------------------
echo.
echo Press ESC inside the OpenCV window
echo or CTRL+C here to stop FillPac AI.
echo.
echo ==========================================================
echo.

REM ==========================================================
REM RUN MAIN APPLICATION
REM
REM Keep this process attached to the launcher.
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
REM
REM Backend does NOT need taskkill.
REM main.py owns and shuts down Uvicorn itself.
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
    echo             FillPac AI Closed Successfully
    echo ==========================================================

) else (

    echo ==========================================================
    echo        FillPac AI Closed With Error (%EXITCODE%)
    echo ==========================================================
)

echo.

REM ==========================================================
REM TESTING INFORMATION
REM ==========================================================

if not "%EXITCODE%"=="0" (

    echo Troubleshooting:
    echo.
    echo 1. Check the terminal traceback above.
    echo.
    echo 2. Check logs in:
    echo       logs\
    echo.
    echo 3. Verify:
    echo       config.yaml
    echo       src\pipeline.py
    echo       src\jam_detector.py
    echo       src\visualizer.py
    echo.
)

pause

endlocal
exit /b %EXITCODE%