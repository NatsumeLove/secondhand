@echo off
chcp 65001 >nul
cd /d "%~dp0"
title Login with a Token

echo ============================================================
echo   Store a GitHub token, then push
echo ============================================================
echo.
echo  Use this only if the browser authorization page is stuck.
echo.
echo  1. Open  https://github.com/settings/tokens
echo  2. Generate new token -^> Generate new token (classic)
echo  3. Note: push    Expiration: 30 days    Scope: tick "repo"
echo  4. Generate token, copy the ghp_... string
echo.
echo  The token is NOT displayed while you paste. That is normal.
echo.
set /p TOK=Token: 

if not defined TOK (
  echo.
  echo [!] Empty token, exit.
  pause
  exit /b 1
)

echo.
echo  Storing token in Windows Credential Manager...
(echo protocol=https& echo host=github.com& echo username=NatsumeLove& echo password=%TOK%& echo.) | cat

echo.
echo  Pushing...
echo.
git push -u origin main

if errorlevel 1 (
  echo.
  echo [!] Push failed. Read the message above.
  echo     If it says Authentication failed, the token is wrong or expired.
  pause
  exit /b 1
)

echo.
echo [OK] Done. Token saved, next push will not ask again.
echo.
pause
