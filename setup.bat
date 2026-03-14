@echo off
setlocal enabledelayedexpansion
title PG Accountant — One-Click Setup

echo.
echo ============================================================
echo   PG Accountant — Automated Setup
echo ============================================================
echo.

:: ── Step 1: Check Python ─────────────────────────────────────
echo [1/7] Checking Python installation...
python --version >nul 2>&1
if errorlevel 1 (
    echo.
    echo  ERROR: Python is not installed!
    echo  Please download and install Python 3.11+ from:
    echo  https://www.python.org/downloads/
    echo  IMPORTANT: Check "Add Python to PATH" during install!
    echo.
    pause
    exit /b 1
)
for /f "tokens=2" %%v in ('python --version 2^>^&1') do set PYVER=%%v
echo  OK: Python %PYVER% found
echo.

:: ── Step 2: Create virtual environment ───────────────────────
echo [2/7] Creating Python virtual environment...
if exist venv (
    echo  OK: Virtual environment already exists, skipping.
) else (
    python -m venv venv
    if errorlevel 1 (
        echo  ERROR: Failed to create virtual environment
        pause
        exit /b 1
    )
    echo  OK: Virtual environment created.
)
echo.

:: ── Step 3: Activate and install packages ────────────────────
echo [3/7] Installing Python packages (this may take 2-5 minutes)...
call venv\Scripts\activate.bat
pip install --upgrade pip --quiet
pip install -r requirements.txt --quiet
if errorlevel 1 (
    echo  ERROR: Failed to install packages. Check your internet connection.
    pause
    exit /b 1
)
echo  OK: All packages installed.
echo.

:: ── Step 4: Create .env if missing ───────────────────────────
echo [4/7] Setting up configuration file...
if exist .env (
    echo  OK: .env already exists, skipping.
) else (
    copy .env.template .env >nul
    echo  OK: .env created from template.
    echo.
    echo  *** IMPORTANT: You must edit .env and fill in your API keys ***
    echo  See QUICKSTART.md for instructions on getting API keys.
)
echo.

:: ── Step 5: Create data directories ──────────────────────────
echo [5/7] Creating data directories...
if not exist data\raw mkdir data\raw
if not exist data\processed mkdir data\processed
if not exist data\exports mkdir data\exports
if not exist data\reports mkdir data\reports
if not exist data\uploads\csv mkdir data\uploads\csv
if not exist data\uploads\pdf mkdir data\uploads\pdf
if not exist dashboards mkdir dashboards
if not exist logs mkdir logs
if not exist workflows\n8n mkdir workflows\n8n
echo  OK: All directories ready.
echo.

:: ── Step 6: Initialize database ──────────────────────────────
echo [6/7] Initializing database...
python -c "
import asyncio
import sys
sys.path.insert(0, '.')
async def init():
    from src.database.db_manager import init_db
    await init_db()
    print('  OK: Database initialized successfully.')
asyncio.run(init())
" 2>nul
if errorlevel 1 (
    echo  WARNING: Could not auto-initialize database.
    echo  It will be created automatically when you start the API.
)
echo.

:: ── Step 7: Check Node.js (optional, for n8n) ────────────────
echo [7/7] Checking Node.js (needed for n8n automation)...
node --version >nul 2>&1
if errorlevel 1 (
    echo  WARNING: Node.js not found.
    echo  You can install it later from https://nodejs.org/
    echo  Required only if you want WhatsApp automation via n8n.
) else (
    for /f "tokens=1" %%v in ('node --version 2^>^&1') do set NODEVER=%%v
    echo  OK: Node.js %NODEVER% found.
)
echo.

:: ── Done ──────────────────────────────────────────────────────
echo ============================================================
echo   SETUP COMPLETE!
echo ============================================================
echo.
echo   Next steps:
echo.
echo   1. Edit the .env file with your API keys
echo      (Open QUICKSTART.md to see exactly what to fill in)
echo.
echo   2. Start the app:
echo      Double-click  START_API.bat
echo.
echo   3. Test with sample data:
echo      Double-click  TEST_SAMPLE.bat
echo.
echo ============================================================
echo.
pause
