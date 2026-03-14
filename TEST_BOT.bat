@echo off
title PG Accountant — Bot Tests
echo.
echo ============================================================
echo   PG Bot Regression Tests
echo ============================================================
echo.

call venv\Scripts\activate.bat
python -m cli.test_bot %*

echo.
pause
