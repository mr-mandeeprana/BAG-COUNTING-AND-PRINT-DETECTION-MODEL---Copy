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
REM PYTHON ENVIRONMENT + DEPENDENCY CHECK
REM
REM FIX: the old version only used the dependency check to
REM decide whether to LOOK for a venv -- it never re-checked
REM packages against the venv it found, and never aborted if
REM no venv existed either. It then printed "[OK] Required
REM packages available." unconditionally, even when they
REM weren't. That's fixed below: DEPS_OK is only set to 1 once
REM a python executable that actually has the packages is
REM found, and the script aborts with a clear message if none
REM of them do.
REM ==========================================================

set "PYTHON_CMD=python"
set "DEPS_OK=0"

echo Checking Python dependencies...

python -c "import cv2, ultralytics, torch, supervision, yaml, fastapi, socketio, uvicorn" >nul 2>nul
if not errorlevel 1 (
    set "DEPS_OK=1"
)

if "!DEPS_OK!"=="0" (

    if exist ".\venv\Scripts\python.exe" (

        ".\venv\Scripts\python.exe" -c "import cv2, ultralytics, torch, supervision, yaml, fastapi, socketio, uvicorn" >nul 2>nul

        if not errorlevel 1 (
            set "PYTHON_CMD=.\venv\Scripts\python.exe"
            set "DEPS_OK=1"
        )
    )
)

if "!DEPS_OK!"=="0" (

    if exist ".\.venv\Scripts\python.exe" (

        ".\.venv\Scripts\python.exe" -c "import cv2, ultralytics, torch, supervision, yaml, fastapi, socketio, uvicorn" >nul 2>nul

        if not errorlevel 1 (
            set "PYTHON_CMD=.\.venv\Scripts\python.exe"
            set "DEPS_OK=1"
        )
    )
)

REM ==========================================================
REM FIX: some setups keep the venv one directory above
REM FillPac_AI itself (e.g. "...\BAG-COUNTING...\venv" with
REM FillPac_AI as a subfolder), rather than inside it. The two
REM checks above only ever look in the current folder, so that
REM layout fell straight through to the "packages missing"
REM error even though a perfectly good venv existed one level
REM up. These two checks cover that layout the same way.
REM ==========================================================

if "!DEPS_OK!"=="0" (

    if exist "..\venv\Scripts\python.exe" (

        "..\venv\Scripts\python.exe" -c "import cv2, ultralytics, torch, supervision, yaml, fastapi, socketio, uvicorn" >nul 2>nul

        if not errorlevel 1 (
            set "PYTHON_CMD=..\venv\Scripts\python.exe"
            set "DEPS_OK=1"
        )
    )
)

if "!DEPS_OK!"=="0" (

    if exist "..\.venv\Scripts\python.exe" (

        "..\.venv\Scripts\python.exe" -c "import cv2, ultralytics, torch, supervision, yaml, fastapi, socketio, uvicorn" >nul 2>nul

        if not errorlevel 1 (
            set "PYTHON_CMD=..\.venv\Scripts\python.exe"
            set "DEPS_OK=1"
        )
    )
)

if "!DEPS_OK!"=="0" (

    echo.
    echo ==========================================================
    echo ERROR: Required Python packages are missing or broken
    echo ==========================================================
    echo.
    echo Checked:
    echo   - python                    (system / active venv)
    echo   - .\venv\Scripts\python.exe
    echo   - .\.venv\Scripts\python.exe
    echo   - ..\venv\Scripts\python.exe
    echo   - ..\.venv\Scripts\python.exe
    echo.
    echo Required packages:
    echo   cv2, ultralytics, torch, supervision, yaml,
    echo   fastapi, socketio, uvicorn
    echo.
    echo The actual error is shown below ^(run with
    echo %PYTHON_CMD% so it matches what main.py will use^):
    echo.

    %PYTHON_CMD% -c "import cv2, ultralytics, torch, supervision, yaml, fastapi, socketio, uvicorn"

    echo.
    echo If the error above is "No module named 'X'", install it,
    echo e.g.:
    echo   pip install -r requirements.txt
    echo.
    echo If the error above is a DLL / import error instead
    echo ^(common for torch/cv2 on Windows^), that package is
    echo installed but broken -- reinstalling requirements.txt
    echo alone may not fix it.
    echo.

    pause
    exit /b 1
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
REM VERIFY DATABASE MODULE (SQL SERVER LAYER)
REM
REM FIX: src\pipeline.py, src\dashboard.py, and
REM src\count_logger.py all import from database.repository at
REM module load time. If this package is missing, the app
REM doesn't fail with a clean message here -- it fails deep
REM inside the "SOURCE IMPORT TEST" below with a generic
REM traceback. Checking for it explicitly, with the same
REM pattern as the other required-file checks, gives a
REM specific, actionable error instead.
REM ==========================================================

if not exist "database\repository.py" (

    echo.
    echo ==========================================================
    echo ERROR: database\repository.py not found
    echo ==========================================================
    echo.

    echo src\pipeline.py, src\dashboard.py, and
    echo src\count_logger.py all import from database.repository
    echo -- FillPac AI cannot start without it.
    echo.

    pause
    exit /b 1
)

if not exist "database\models.py" (

    echo.
    echo ==========================================================
    echo ERROR: database\models.py not found
    echo ==========================================================
    echo.

    pause
    exit /b 1
)

if not exist "database\connection.py" (

    echo.
    echo ==========================================================
    echo ERROR: database\connection.py not found
    echo ==========================================================
    echo.

    pause
    exit /b 1
)

REM ==========================================================
REM FIX: database\repository.py now imports database\failsafe.py
REM at module load time (the local SQL-outage failover queue).
REM Same reasoning as the other database\*.py checks above --
REM catch a missing file here with a specific message instead of
REM a generic traceback during the source import test below.
REM ==========================================================

if not exist "database\failsafe.py" (

    echo.
    echo ==========================================================
    echo ERROR: database\failsafe.py not found
    echo ==========================================================
    echo.

    echo database\repository.py imports database\failsafe.py at
    echo module load time -- FillPac AI cannot start without it.
    echo.

    pause
    exit /b 1
)

echo [OK] Database module found.

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

REM database\failsafe.py also creates this on demand, but
REM creating it here too means it shows up immediately instead
REM of only appearing the first time SQL Server has an outage.
if not exist "logs\sql_failover" (
    mkdir "logs\sql_failover"
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
REM
REM FIX: the old command had no /T, so it only closed the
REM cmd.exe window ("start" always spawns cmd.exe as the
REM direct child) without killing the "python -m http.server"
REM process running inside it. That left the frontend server
REM running in the background, holding port 8080, so the very
REM next launch would fail the "port 8080 already in use"
REM check for no visible reason. /T kills the whole process
REM tree. The result is also checked now instead of always
REM printing "[OK]" regardless of whether it worked.
REM ==========================================================

echo Stopping Dashboard Frontend...

taskkill /FI "WINDOWTITLE eq FillPac AI - Dashboard Frontend*" /T /F >nul 2>nul

if errorlevel 1 (

    echo [WARN] Could not confirm the dashboard frontend process
    echo        was stopped. If port 8080 is still in use on the
    echo        next run, close it manually via Task Manager.

) else (

    echo [OK] Dashboard frontend stopped.
)

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