@echo off
title PG Accountant — API Server
echo.
echo ============================================================
echo   PG Accountant — Starting API Server
echo ============================================================
echo.
echo   The server will start at: http://localhost:8000
echo   Press Ctrl+C to stop the server.
echo.

call venv\Scripts\activate.bat
set TEST_MODE=1
python -m cli.start_api

pause
