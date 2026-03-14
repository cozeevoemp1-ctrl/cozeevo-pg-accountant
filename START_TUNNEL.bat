@echo off
title PG Accountant — Public Tunnel (Cloudflare)
color 0E

echo.
echo ============================================================
echo   Starting Cloudflare Tunnel (FREE — no account needed)
echo ============================================================
echo.
echo Starting FastAPI first...
start "PG Accountant API" /min cmd /c "cd /d %~dp0 && venv\Scripts\python -m uvicorn main:app --host 0.0.0.0 --port 8000"
timeout /t 3 /nobreak >nul

echo Starting tunnel...
echo.
echo IMPORTANT: Copy the https://xxxx.trycloudflare.com URL shown below.
echo Then go to Meta Developer Dashboard and set:
echo   Webhook URL  : https://xxxx.trycloudflare.com/webhook/whatsapp
echo   Verify Token : pg-accountant-verify
echo.
echo ============================================================

cloudflared tunnel --url http://localhost:8000 --no-autoupdate
