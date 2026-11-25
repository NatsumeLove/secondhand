@echo off
chcp 65001 >nul
cd /d "%~dp0"
title Push to GitHub

echo ============================================================
echo   Push this project to GitHub
echo ============================================================
echo.

rem step 1 - reuse the remote url if it is already configured
set "REPO="
for /f "delims=" %%i in ('git remote get-url origin 2^>nul') do set "REPO=%%i"
if not defined REPO goto ask

echo  Repo already set:
echo    %REPO%
echo.
echo  Press Enter to use it, or paste a different URL.
set /p NEWREPO=URL: 
if defined NEWREPO set "REPO=%NEWREPO%"
goto push

:ask
echo  Create an EMPTY repo on GitHub first:
echo    github.com -^> New repository -^> name "secondhand"
echo    Public -^> do NOT tick README / .gitignore / license
echo.
echo  Then paste the URL, e.g.
echo    https://github.com/NatsumeLove/secondhand.git
echo.
set /p REPO=URL: 

:push
if not defined REPO (
  echo.
  echo [!] No URL, exit.
  pause
  exit /b 1
)

git remote remove origin >nul 2>&1
git remote add origin %REPO%
git branch -M main

echo.
for /f "delims=" %%p in ('git config --get http.proxy 2^>nul') do echo  Proxy in use: %%p
echo ------------------------------------------------------------
echo  Pushing...
echo.
echo  A browser window may pop up - just sign in to GitHub.
echo  If the console asks for Username / Password instead:
echo    Username = your GitHub username
echo    Password = a Personal Access Token, NOT your login password
echo               create one at github.com/settings/tokens
echo               -^> classic -^> tick "repo" -^> generate
echo ------------------------------------------------------------
echo.

git push -u origin main

if errorlevel 1 (
  echo.
  echo [!] Push failed. Read the message above.
  echo     Common causes:
  echo       1. Connection was reset -^> you are behind a proxy, tell git to use it:
  echo            git config http.proxy http://127.0.0.1:7897
  echo          turn it off again with:
  echo            git config --unset http.proxy
  echo       2. The GitHub repo is NOT empty -^> delete it, create again, tick nothing
  echo       3. Wrong URL -^> it must end with .git
  echo       4. Typed login password instead of Token
  pause
  exit /b 1
)

echo.
echo [OK] Done. Opening your repo page...
start "" %REPO:.git=%
echo.
pause
