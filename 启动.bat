@echo off
chcp 65001 >nul
cd /d "%~dp0"
title YuWuJi - Campus Second-hand Market

if exist "venv\Scripts\python.exe" goto run

echo [1/3] Creating virtual environment...
py -3 -m venv venv 2>nul || python -m venv venv

if not exist "venv\Scripts\python.exe" (
  echo.
  echo [!] Python not found.
  echo     Please install Python 3.10+ and check "Add Python to PATH".
  echo     Download: https://www.python.org/downloads/
  echo.
  pause
  exit /b 1
)

echo [2/3] Installing dependencies, please wait 1-2 minutes...
"venv\Scripts\python.exe" -m pip install --upgrade pip --quiet
"venv\Scripts\python.exe" -m pip install -r requirements.txt

:run
echo.
echo [3/3] Starting server... the browser will open automatically.
echo       Close this window to stop the server.
echo.
"venv\Scripts\python.exe" app.py
pause
