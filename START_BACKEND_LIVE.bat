@echo off
setlocal
title Aetrix - backend live

rem ===========================================================================
rem  Starts the backend so the deployed frontend can use it.
rem
rem  A backend bound only to 127.0.0.1 is not reachable from
rem  https://aetrix.pages.dev. The managed stack therefore starts the engine,
rem  the correction worker, the supervisor and the configured public route,
rem  then verifies:
rem    * local /health and /ready
rem    * public /health and /ready
rem    * CORS preflight from the live frontend origin
rem    * protected-route 401 behaviour
rem    * the live frontend's compiled API origin
rem
rem  This is the production-oriented launcher. START_BACKEND.bat remains the
rem  loopback-only local-development launcher.
rem ===========================================================================

set "ROOT=%~dp0"
if "%ROOT:~-1%"=="\" set "ROOT=%ROOT:~0,-1%"
set "STACK=%ROOT%\scripts\aetrix-stack.ps1"

echo Aetrix backend: live start
echo   project : %ROOT%
echo.

if not exist "%STACK%" (
  echo [ERROR] Missing %STACK%.
  exit /b 1
)

pushd "%ROOT%"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%STACK%" start
set "AETRIX_EXIT=%ERRORLEVEL%"
popd

if not "%AETRIX_EXIT%"=="0" (
  echo.
  echo Aetrix did not connect to the live frontend. Read the failure above and
  echo the logs in .tmp\aetrix\stack.
  exit /b %AETRIX_EXIT%
)

echo.
echo [OK] Backend is live for the deployed frontend.
echo      Live frontend : https://aetrix.pages.dev
echo      Stop          : STOP_AETRIX.bat
exit /b 0
