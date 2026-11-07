@echo off
setlocal EnableExtensions EnableDelayedExpansion
title Aetrix backend
rem ===========================================================================
rem  Starts the Aetrix correction engine - FastAPI via uvicorn - on
rem  http://127.0.0.1:8000
rem
rem  * Binds the loopback interface only. The laptop backend is not reachable
rem    from another machine, and this script opens no tunnel and no public port.
rem  * Configuration is read from backend\.env, which is git-ignored. Start from
rem    backend\.env.example. This script never writes or prints a secret.
rem  * Refuses to start a second instance: it probes the port first.
rem  * AETRIX_BACKEND_HEADLESS=1 runs without a console window and writes the
rem    server output to backend\.aetrix-backend.log. Automated checks use it.
rem    Without it, a console opens and stays open after the server stops, so a
rem    traceback or startup log can be read.
rem ===========================================================================

set "ROOT=%~dp0"
if "%ROOT:~-1%"=="\" set "ROOT=%ROOT:~0,-1%"
set "BACKEND=%ROOT%\backend"
set "PY=%BACKEND%\.venv\Scripts\python.exe"
set "ENVFILE=%BACKEND%\.env"
set "PIDFILE=%BACKEND%\.aetrix-backend.pid"
set "LOGFILE=%BACKEND%\.aetrix-backend.log"
set "HOST=127.0.0.1"
set "PORT=8000"
set "URL=http://%HOST%:%PORT%"
set "APP=app.main:app"
set "WAIT_SECONDS=45"

echo Aetrix backend: start
echo   project : %ROOT%
echo   address : %URL%
echo.

if not exist "%PY%" goto :no_venv
if not exist "%ENVFILE%" goto :no_env
where curl.exe >nul 2>&1
if errorlevel 1 goto :no_curl

rem Configuration keys must be present, but their values are never printed.
findstr /B /C:"AETRIX_DATABASE__URL=postgresql" "%ENVFILE%" >nul 2>&1
if errorlevel 1 goto :bad_database
findstr /R /B /C:"AETRIX_SECURITY__ENCRYPTION_KEY=..*" "%ENVFILE%" >nul 2>&1
if errorlevel 1 goto :bad_encryption

rem --- Is something already listening on the port? ---------------------------
call :listener_pid
if not defined LISTENER goto :launch

call :probe
if not "!CODE!"=="200" goto :port_foreign

echo [OK] Already running on %URL% with PID !LISTENER!; not starting a second copy.
call :write_pid !LISTENER!
call :report !LISTENER!
goto :success

:port_foreign
echo [ERROR] Port %PORT% is held by PID !LISTENER!, which does not answer /health.
echo         That is probably another program or a crashed backend. Nothing was started.
call :process_name !LISTENER!
goto :fail

rem --- Start ----------------------------------------------------------------
:launch
echo Starting uvicorn ...
if /I "%AETRIX_BACKEND_HEADLESS%"=="1" goto :launch_headless

start "Aetrix backend :%PORT%" /D "%BACKEND%" cmd /k ""%PY%" -m uvicorn %APP% --host %HOST% --port %PORT% --log-level info"
goto :wait

:launch_headless
if exist "%LOGFILE%" del /q "%LOGFILE%" >nul 2>&1
if exist "%LOGFILE%.err" del /q "%LOGFILE%.err" >nul 2>&1
powershell -NoProfile -ExecutionPolicy Bypass -Command "$ErrorActionPreference='Stop'; Start-Process -FilePath '%PY%' -ArgumentList '-m','uvicorn','%APP%','--host','%HOST%','--port','%PORT%','--log-level','info' -WorkingDirectory '%BACKEND%' -WindowStyle Hidden -RedirectStandardOutput '%LOGFILE%' -RedirectStandardError '%LOGFILE%.err' | Out-Null"
if errorlevel 1 (
  echo [ERROR] Could not launch the server process.
  goto :fail
)

rem --- Wait for /health -----------------------------------------------------
:wait
set /a TRIES=0
:wait_loop
call :probe
if "!CODE!"=="200" goto :started
set /a TRIES+=1
if !TRIES! GEQ %WAIT_SECONDS% goto :start_slow
ping -n 2 127.0.0.1 >nul
goto :wait_loop

:start_slow
echo [ERROR] The backend did not answer %URL%/health within %WAIT_SECONDS% seconds.
if /I "%AETRIX_BACKEND_HEADLESS%"=="1" goto :start_slow_logs
echo         The "Aetrix backend :%PORT%" window keeps the traceback on screen.
goto :start_slow_cleanup

:start_slow_logs
if exist "%LOGFILE%" (
  echo         Last lines of %LOGFILE%:
  powershell -NoProfile -Command "Get-Content -Tail 25 '%LOGFILE%'"
)
if exist "%LOGFILE%.err" (
  echo         Last lines of %LOGFILE%.err:
  powershell -NoProfile -Command "Get-Content -Tail 25 '%LOGFILE%.err'"
)

:start_slow_cleanup
rem A start that failed must not leave a half-started server behind.
call :listener_pid
if not defined LISTENER goto :fail
call :is_ours !LISTENER!
if /I not "!OURS!"=="ours" goto :fail
echo         The process this script started is still listening; stopping PID !LISTENER!.
taskkill /PID !LISTENER! /T /F >nul 2>&1
goto :fail

:started
call :listener_pid
if defined LISTENER call :write_pid !LISTENER!
echo [OK] Backend started.
call :report !LISTENER!
goto :success

rem --- Subroutines ----------------------------------------------------------
:listener_pid
set "LISTENER="
for /f "usebackq delims=" %%P in (`powershell -NoProfile -Command "@(Get-NetTCPConnection -LocalPort %PORT% -State Listen -ErrorAction SilentlyContinue)[0].OwningProcess"`) do set "LISTENER=%%P"
exit /b 0

:probe
set "CODE=000"
for /f "usebackq delims=" %%C in (`curl.exe -s -o NUL -w "%%{http_code}" --max-time 3 "%URL%/health"`) do set "CODE=%%C"
exit /b 0

:write_pid
if "%~1"=="" exit /b 0
> "%PIDFILE%" echo %~1
exit /b 0

:process_name
for /f "usebackq delims=" %%N in (`powershell -NoProfile -Command "(Get-Process -Id %~1 -ErrorAction SilentlyContinue).ProcessName"`) do echo         process: %%N
exit /b 0

:is_ours
set "OURS=foreign"
for /f "usebackq delims=" %%R in (`powershell -NoProfile -Command "$p = Get-CimInstance Win32_Process -Filter 'ProcessId=%~1' -ErrorAction SilentlyContinue; if ($p -and $p.CommandLine -match 'uvicorn' -and $p.CommandLine -match 'app\.main:app' -and $p.CommandLine -match '--port\s+%PORT%') { 'ours' } else { 'foreign' }"`) do set "OURS=%%R"
exit /b 0

:report
set "READY_CODE=000"
rem /ready runs a real query, so a dead host is reported by the engine itself
rem after its connect timeout; the probe waits longer than the health check.
for /f "usebackq delims=" %%R in (`curl.exe -s -o NUL -w "%%{http_code}" --max-time 20 "%URL%/ready"`) do set "READY_CODE=%%R"
echo   PID     : %~1
echo   health  : %URL%/health -^> 200
echo   ready   : %URL%/ready
if "%READY_CODE%"=="200" goto :report_ready_ok
if "%READY_CODE%"=="503" goto :report_db_down
echo           no answer from /ready within 20s -^> database unreachable or hung
echo            The API answers, but no data request can succeed until the
echo            database configured in backend\.env is reachable.
goto :report_tail

:report_ready_ok
echo           200 -^> database reachable
goto :report_tail

:report_db_down
echo           503 -^> DATABASE NOT REACHABLE
echo            The API answers, but no data request can succeed until the
echo            database configured in backend\.env is reachable.

:report_tail
echo   API     : %URL%/api/v1
echo   docs    : %URL%/docs
exit /b 0

:no_venv
echo [ERROR] No virtual environment at:
echo         %PY%
echo         Create it once, from the backend directory:
echo           python -m venv .venv
echo           .venv\Scripts\python.exe -m pip install -e ".[dev]"
goto :fail

:no_curl
echo [ERROR] curl.exe was not found on PATH.
echo         The health check needs it; it ships with Windows 10 1803 and later.
goto :fail

:no_env
echo [ERROR] backend\.env is missing, so the engine has no configuration.
echo         Copy backend\.env.example to backend\.env and fill in:
echo           AETRIX_DATABASE__URL             PostgreSQL connection string
echo           AETRIX_AUTH__JWKS_URL            Supabase JWKS URL, or AETRIX_AUTH__JWT_SECRET
echo           AETRIX_SECURITY__ENCRYPTION_KEY  Fernet key for provider secrets
echo         backend\.env is git-ignored and must never be committed.
goto :fail

:bad_database
echo [ERROR] AETRIX_DATABASE__URL in backend\.env is missing or not a postgresql URL.
echo         SQLite is not a supported dialect; see backend\.env.example.
goto :fail

:bad_encryption
echo [ERROR] AETRIX_SECURITY__ENCRYPTION_KEY is empty in backend\.env.
echo         Generate one with:
echo           backend\.venv\Scripts\python.exe -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
goto :fail

:success
if /I not "%AETRIX_BACKEND_HEADLESS%"=="1" (
  echo.
  echo The server window stays open for logs. Run STOP_BACKEND.bat to stop it.
  if /I not "%AETRIX_NO_PAUSE%"=="1" pause
)
endlocal & exit /b 0

:fail
if /I not "%AETRIX_NO_PAUSE%"=="1" pause
endlocal & exit /b 1
