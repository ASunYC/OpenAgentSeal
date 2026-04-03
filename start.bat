@echo off
REM Open Agent Launcher for Windows
REM This script checks Python and runs the application with auto-dependency management

setlocal EnableDelayedExpansion

echo ===================================================
echo Open Agent Launcher
echo ===================================================
echo.

REM Check Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python not found!
    echo Please install Python 3.9+ from https://www.python.org/downloads/
    echo Make sure to check "Add Python to PATH" during installation.
    echo.
    pause
    exit /b 1
)

REM Run the Python launcher
python run.py %*

REM If failed, pause to show error
if errorlevel 1 (
    echo.
    echo [ERROR] Failed to start Open Agent
    pause
    exit /b 1
)

endlocal