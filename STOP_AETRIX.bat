@echo off
setlocal EnableExtensions EnableDelayedExpansion
title Aetrix full stack: stop
rem ===========================================================================
rem  Stops the tunnel and backend that START_AETRIX.bat started.
rem
rem  The tunnel is stopped only when the recorded PID's command line still runs
rem  cloudflared against 127.0.0.1:8000. STOP_BACKEND.bat applies the same
rem  command-line check to uvicorn app.main:app on port 8000. Nothing is killed
rem  by image name, so unrelated cloudflared or Python processes survive.
rem ===========================================================================

set "ROOT=%~dp0"
if "%ROOT:~-1%"=="\" set "ROOT=%ROOT:~0,-1%"
set "STATE=%ROOT%\.tmp\aetrix"
set "CFPID=%STATE%\tunnel.pid"
set "URLFILE=%STATE%\tunnel.url"
set "TUNNEL_PID="

echo Aetrix full stack: stop
echo   project : %ROOT%
echo.

call :read_tunnel
if not defined TUNNEL_PID goto :no_tunnel

echo Stopping tunnel PID !TUNNEL_PID! ...
taskkill /PID !TUNNEL_PID! /T /F >nul 2>&1
if errorlevel 1 (
  echo [ERROR] taskkill refused to end PID !TUNNEL_PID!.
  goto :fail
)

set /a TRIES=0
:wait_gone
powershell -NoProfile -Command "if (Get-Process -Id !TUNNEL_PID! -ErrorAction SilentlyContinue) { exit 1 } else { exit 0 }"
if not errorlevel 1 goto :tunnel_stopped
set /a TRIES+=1
if !TRIES! GEQ 20 goto :tunnel_stuck
ping -n 2 127.0.0.1 >nul
goto :wait_gone

:tunnel_stuck
echo [ERROR] Tunnel PID !TUNNEL_PID! did not exit within 20 seconds.
goto :fail

:tunnel_stopped
if exist "%CFPID%" del /q "%CFPID%" >nul 2>&1
if exist "%URLFILE%" del /q "%URLFILE%" >nul 2>&1
echo [OK] Tunnel stopped.
goto :stop_backend

:no_tunnel
echo [INFO] No tunnel recorded under .tmp\aetrix.

:stop_backend
set "AETRIX_NO_PAUSE=1"
call "%ROOT%\STOP_BACKEND.bat"
if errorlevel 1 goto :fail
echo.
echo [OK] Aetrix full stack stopped.
endlocal & exit /b 0

:read_tunnel
if not exist "%CFPID%" exit /b 0
set "CANDIDATE="
for /f "usebackq delims=" %%P in ("%CFPID%") do if not defined CANDIDATE set "CANDIDATE=%%P"
if not defined CANDIDATE exit /b 0
set "OURS=foreign"
for /f "usebackq delims=" %%R in (`powershell -NoProfile -Command "$p = Get-CimInstance Win32_Process -Filter 'ProcessId=%CANDIDATE%' -ErrorAction SilentlyContinue; if (-not $p) { 'gone' } elseif ($p.CommandLine -match 'cloudflared' -and $p.CommandLine -match '127\.0\.0\.1:8000') { 'ours' } else { 'foreign' }"`) do set "OURS=%%R"
if /I "!OURS!"=="ours" (
  set "TUNNEL_PID=%CANDIDATE%"
  exit /b 0
)
if /I "!OURS!"=="gone" (
  echo [INFO] Recorded tunnel PID %CANDIDATE% already exited.
  if exist "%CFPID%" del /q "%CFPID%" >nul 2>&1
  if exist "%URLFILE%" del /q "%URLFILE%" >nul 2>&1
  exit /b 0
)
echo [WARN] PID %CANDIDATE% is not this project's tunnel; leaving it alone.
if exist "%CFPID%" del /q "%CFPID%" >nul 2>&1
exit /b 0

:fail
echo [ERROR] The full stack did not stop cleanly.
endlocal & exit /b 1
