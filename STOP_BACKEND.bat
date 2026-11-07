@echo off
setlocal EnableExtensions EnableDelayedExpansion
title Aetrix backend: stop
rem ===========================================================================
rem  Stops only the Aetrix engine started by START_BACKEND.bat.
rem
rem  A process is treated as ours only when all of these hold:
rem    * its id is the one recorded at start-up, or the current listener on the
rem      project's port when no record exists;
rem    * its command line runs uvicorn against app.main:app;
rem    * its command line serves port 8000, the port in this project's scripts.
rem  Nothing is ever killed by image name, so unrelated Python services are
rem  untouched. The interpreter path is not compared: this virtual environment
rem  launches the interpreter under .tools\python, so the image path is not the
rem  venv's Scripts\python.exe even when the venv is the one that was started.
rem
rem  AETRIX_NO_PAUSE=1 suppresses the final pause - used by automated checks.
rem ===========================================================================

set "ROOT=%~dp0"
if "%ROOT:~-1%"=="\" set "ROOT=%ROOT:~0,-1%"
set "BACKEND=%ROOT%\backend"
set "PY=%BACKEND%\.venv\Scripts\python.exe"
set "PIDFILE=%BACKEND%\.aetrix-backend.pid"
set "HOST=127.0.0.1"
set "PORT=8000"

echo Aetrix backend: stop
echo   project : %ROOT%
echo.

set "PID="
if exist "%PIDFILE%" goto :read_pid
goto :find_listener

:read_pid
for /f "usebackq delims= " %%P in ("%PIDFILE%") do if not defined PID set "PID=%%P"
if defined PID goto :have_pid
goto :find_listener

:find_listener
call :listener_pid
if defined LISTENER set "PID=!LISTENER!"
if defined PID (
  echo No pid file; checking the recorded port instead.
  goto :have_pid
)
echo [OK] Not running: nothing listens on port %PORT% and no pid file exists.
call :clear_pid
goto :success

:have_pid
call :classify !PID!
if /I "!VERDICT!"=="ours" goto :stop_it
if /I "!VERDICT!"=="gone" goto :already_gone
echo [WARN] PID !PID! is not this project's backend; leaving it alone.
echo        Its command line does not run uvicorn app.main:app on port %PORT%.
call :clear_pid
echo [OK] The Aetrix backend is not running.
goto :success

:already_gone
echo [INFO] PID !PID! has already exited.
call :clear_pid
echo [OK] The Aetrix backend is not running.
goto :success

:stop_it
echo Stopping PID !PID! ...
taskkill /PID !PID! /T /F >nul 2>&1
if errorlevel 1 (
  echo [ERROR] taskkill refused to end PID !PID!.
  echo         It may have exited between the check and the call, or it belongs
  echo         to another account. Run this script from the same account.
  call :clear_pid
  goto :fail
)

:wait_gone
set /a TRIES=0
:wait_gone_loop
powershell -NoProfile -Command "if (Get-Process -Id !PID! -ErrorAction SilentlyContinue) { exit 1 } else { exit 0 }"
if not errorlevel 1 goto :confirm_port
set /a TRIES+=1
if !TRIES! GEQ 20 goto :still_running
ping -n 2 127.0.0.1 >nul
goto :wait_gone_loop

:still_running
echo [ERROR] PID !PID! did not exit within 20 seconds.
goto :fail

:confirm_port
call :listener_pid
if defined LISTENER (
  echo [ERROR] Port %PORT% is still listening with PID !LISTENER! after the stop.
  goto :fail
)
call :clear_pid
echo [OK] Backend stopped; port %PORT% is free.
goto :success

rem --- Subroutines ----------------------------------------------------------
:listener_pid
set "LISTENER="
for /f "usebackq delims=" %%P in (`powershell -NoProfile -Command "@(Get-NetTCPConnection -LocalPort %PORT% -State Listen -ErrorAction SilentlyContinue)[0].OwningProcess"`) do set "LISTENER=%%P"
exit /b 0

:classify
set "VERDICT=foreign"
for /f "usebackq delims=" %%R in (`powershell -NoProfile -Command "$p = Get-CimInstance Win32_Process -Filter 'ProcessId=%~1' -ErrorAction SilentlyContinue; if (-not $p) { 'gone' } elseif ($p.CommandLine -match 'uvicorn' -and $p.CommandLine -match 'app\.main:app' -and $p.CommandLine -match '--port\s+%PORT%') { 'ours' } else { 'foreign' }"`) do set "VERDICT=%%R"
exit /b 0

:clear_pid
if exist "%PIDFILE%" del /q "%PIDFILE%" >nul 2>&1
exit /b 0

:success
if /I not "%AETRIX_NO_PAUSE%"=="1" pause
endlocal & exit /b 0

:fail
if /I not "%AETRIX_NO_PAUSE%"=="1" pause
endlocal & exit /b 1
