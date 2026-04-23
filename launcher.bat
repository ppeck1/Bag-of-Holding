@echo off
REM Bag of Holding v2 — Windows Launcher
REM Double-click this file to start the application.
REM Requires Python 3.11+ in PATH.

title Bag of Holding v2

echo.
echo  ==========================================
echo   Bag of Holding v2 - Local Knowledge Workbench
echo  ==========================================
echo.

REM Check Python is available
python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python not found in PATH.
    echo Please install Python 3.11+ from https://python.org
    pause
    exit /b 1
)

REM Check uvicorn is installed
python -c "import uvicorn" >nul 2>&1
if errorlevel 1 (
    echo Installing dependencies...
    pip install -r requirements.txt
    if errorlevel 1 (
        echo ERROR: Failed to install dependencies.
        pause
        exit /b 1
    )
)

REM Run launcher
python launcher.py %*

pause
