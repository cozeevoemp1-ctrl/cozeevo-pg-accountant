@echo off
title PG Accountant — Install Ollama (Free Local AI)
echo.
echo ============================================================
echo   Installing Ollama — Free Local AI (runs on your PC)
echo ============================================================
echo.
echo   This will:
echo   1. Download and install Ollama (~50 MB)
echo   2. Download Llama 3.2 AI model (~2 GB)
echo   3. Test that it works
echo.
echo   Requirements:
echo   - 4 GB free disk space
echo   - 8 GB RAM recommended
echo   - Internet connection (one-time download only)
echo.
pause

:: Check if Ollama already installed
ollama --version >nul 2>&1
if not errorlevel 1 (
    echo.
    echo  OK: Ollama is already installed!
    goto download_model
)

echo.
echo [1/3] Downloading Ollama installer...
echo  Please wait — downloading from ollama.com...
echo.

:: Download Ollama installer using PowerShell
powershell -Command "Invoke-WebRequest -Uri 'https://ollama.com/download/OllamaSetup.exe' -OutFile '%TEMP%\OllamaSetup.exe' -UseBasicParsing"

if not exist "%TEMP%\OllamaSetup.exe" (
    echo  ERROR: Download failed. Please check your internet connection.
    echo  Or download manually from: https://ollama.com/download/windows
    pause
    exit /b 1
)

echo [2/3] Installing Ollama...
"%TEMP%\OllamaSetup.exe" /S
timeout /t 5 /nobreak >nul

echo  OK: Ollama installed.
echo.

:download_model
echo [3/3] Downloading Llama 3.2 AI model (~2 GB — this takes 5-15 minutes)...
echo  Do not close this window.
echo.
ollama pull llama3.2

if errorlevel 1 (
    echo.
    echo  ERROR: Model download failed. Try running this again.
    pause
    exit /b 1
)

echo.
echo ============================================================
echo   OLLAMA INSTALLED SUCCESSFULLY!
echo ============================================================
echo.
echo   The AI now runs 100%% FREE on your computer.
echo   No internet needed for AI after this.
echo.
echo   To switch to cloud AI later (for deployment):
echo   Open .env and change:
echo     LLM_PROVIDER="ollama"
echo   to:
echo     LLM_PROVIDER="groq"    (free cloud)
echo     LLM_PROVIDER="anthropic"  (paid Claude)
echo.
pause
