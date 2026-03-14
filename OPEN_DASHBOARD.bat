@echo off
title PG Accountant — Dashboard
echo.
echo ============================================================
echo   PG Accountant — Generating Dashboard
echo ============================================================
echo.
call venv\Scripts\activate.bat
python -m cli.generate_report --format dashboard --open
echo.
pause
