@echo off
title PG Accountant — Test with Sample Data
echo.
echo ============================================================
echo   PG Accountant — Testing with Sample PhonePe Data
echo ============================================================
echo.

call venv\Scripts\activate.bat

echo [1/3] Running dry-run (preview without saving)...
echo.
python -m cli.ingest_file data\raw\sample_phonepe.csv --dry-run
echo.

echo [2/3] Press any key to SAVE the sample data to database...
pause

echo.
python -m cli.ingest_file data\raw\sample_phonepe.csv
echo.

echo [3/3] Generating monthly report...
echo.
python -m cli.run_reconciliation --period monthly
echo.

echo ============================================================
echo   Done! You can also generate a visual dashboard:
echo   python -m cli.generate_report --format dashboard --open
echo ============================================================
echo.
pause
