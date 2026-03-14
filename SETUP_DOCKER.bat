@echo off
title PG Accountant — Docker Setup
color 0B

echo.
echo ============================================================
echo   PG Accountant — Docker Setup (n8n + Redis)
echo ============================================================
echo.

REM Check if Docker is installed
docker --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Docker Desktop is NOT installed.
    echo.
    echo  Please install Docker Desktop first:
    echo  ^> https://www.docker.com/products/docker-desktop/
    echo.
    echo  After install, restart your PC and run this script again.
    pause
    exit /b 1
)

echo [OK] Docker is installed.
echo.

REM Check if Docker daemon is running
docker info >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Docker Desktop is not running.
    echo  Please open Docker Desktop from the Start Menu and wait
    echo  for it to fully start, then run this script again.
    pause
    exit /b 1
)

echo [OK] Docker is running.
echo.

echo Starting n8n and Redis containers...
echo (This will download images on first run — may take a few minutes)
echo.

docker-compose up -d n8n redis

if %errorlevel% neq 0 (
    echo.
    echo [ERROR] docker-compose failed. Check the error above.
    pause
    exit /b 1
)

echo.
echo ============================================================
echo   Done! Services are starting...
echo ============================================================
echo.
echo   n8n dashboard  : http://localhost:5678
echo   Username       : admin
echo   Password       : pgaccountant2024
echo.
echo   Wait ~30 seconds for n8n to fully start, then open:
echo   http://localhost:5678
echo.
echo   Next steps:
echo   1. Login to n8n ^> Settings ^> API ^> Create API key
echo   2. Paste the key into .env as N8N_API_KEY
echo   3. Run: python -m cli.configure_workflow --deploy
echo.
pause
