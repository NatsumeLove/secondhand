@echo off
chcp 65001 >nul
cd /d "%~dp0"
title Push to GitHub

echo ============================================================
echo   Push this project to GitHub
echo ============================================================
echo.
echo  Before running this, create an EMPTY repo on GitHub:
echo    github.com -^> New repository -^> name "secondhand"
echo    -^> Public -^> do NOT tick README / .gitignore / license
echo.
echo  Your repo URL looks like:
echo    https://github.com/NatsumeLove/secondhand.git
echo.
set /p REPO=Paste the URL here, then press Enter: 

if "%REPO%"=="" (
  echo.
  echo [!] Nothing entered, exit.
  pause
  exit /b 1
)

git remote remove origin >nul 2>&1
git remote add origin %REPO%
git branch -M main

echo.
echo ------------------------------------------------------------
echo  Pushing...
echo  If a browser window pops up, just sign in to GitHub.
echo  If it asks for username / password:
echo    username = your GitHub username
echo    password = a Personal Access Token, NOT your login password
echo               create one at github.com/settings/tokens
echo ------------------------------------------------------------
echo.

git push -u origin main

if errorlevel 1 (
  echo.
  echo [!] Push failed. Read the message above.
  echo     Most common causes:
  echo       1. The GitHub repo is not empty -^> delete it and create again
  echo       2. Wrong URL -^> it must end with .git
  echo       3. Password typed instead of Token
  pause
  exit /b 1
)

echo.
echo [OK] Done. Refresh your GitHub page, the code should be there.
echo.
pause
