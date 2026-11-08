@echo off
setlocal EnableExtensions EnableDelayedExpansion
title Aetrix full stack
rem ===========================================================================
rem  Starts the complete local stack for the deployed Aetrix frontend:
rem
rem    1. checks backend\.env and cloudflared
rem    2. starts the FastAPI engine on http://127.0.0.1:8000 (START_BACKEND.bat)
rem    3. waits for /health
rem    4. opens a free Cloudflare quick tunnel to that loopback address
rem    5. waits for the public https URL and verifies <url>/health
rem    6. prints the origin to compile into VITE_AETRIX_API_URL
rem
rem  Both processes are started through PowerShell and recorded under
rem  .tmp\aetrix\. STOP_AETRIX.bat stops only those recorded processes.
rem
rem  A quick tunnel gets a new hostname on every start. A stable hostname needs
rem  a named tunnel bound to a Cloudflare-managed domain; see README.md.
rem
rem  AETRIX_NO_PAUSE=1 suppresses the final pause for automated checks.
rem ===========================================================================

set "ROOT=%~dp0"
if "%ROOT:~-1%"=="\" set "ROOT=%ROOT:~0,-1%"
set "BACKEND=%ROOT%\backend"
set "STATE=%ROOT%\.tmp\aetrix"
set "CFERR=%STATE%\cloudflared.err"
set "CFOUT=%STATE%\cloudflared.out"
set "CFPID=%STATE%\tunnel.pid"
set "URLFILE=%STATE%\tunnel.url"
set "CF=%ProgramFiles(x86)%\cloudflared\cloudflared.exe"
if not exist "%CF%" set "CF=%ProgramFiles%\cloudflared\cloudflared.exe"
set "LOCAL=http://127.0.0.1:8000"
set "WAIT_SECONDS=45"
set "PUBLIC_URL="

echo Aetrix full stack: start
echo   project : %ROOT%
echo.

if not exist "%CF%" goto :no_cloudflared
if not exist "%BACKEND%\.env" goto :no_env
where curl.exe >nul 2>&1
if errorlevel 1 goto :no_curl
if not exist "%STATE%" mkdir "%STATE%"

rem --- 1. Backend ------------------------------------------------------------
set "AETRIX_BACKEND_HEADLESS=1"
set "AETRIX_NO_PAUSE=1"
call "%ROOT%\START_BACKEND.bat"
if errorlevel 1 goto :backend_failed

rem --- 2. Reuse an already-running tunnel ------------------------------------
call :tunnel_pid
if defined TUNNEL_PID (
  if exist "%URLFILE%" set /p PUBLIC_URL=<"%URLFILE%"
  if defined PUBLIC_URL (
    echo [OK] Tunnel already running with PID !TUNNEL_PID!.
    goto :verify
  )
  echo [ERROR] A tunnel process is running but no public URL was recorded.
  echo         Run STOP_AETRIX.bat, then start again.
  goto :fail
)

rem --- 3. Start the tunnel ---------------------------------------------------
echo Starting Cloudflare quick tunnel ...
if exist "%CFERR%" del /q "%CFERR%" >nul 2>&1
if exist "%CFOUT%" del /q "%CFOUT%" >nul 2>&1
powershell -NoProfile -ExecutionPolicy Bypass -Command "$p = Start-Process -FilePath '%CF%' -ArgumentList @('tunnel','--url','%LOCAL%','--no-autoupdate','--loglevel','info') -WorkingDirectory '%ROOT%' -WindowStyle Hidden -RedirectStandardOutput '%CFOUT%' -RedirectStandardError '%CFERR%' -PassThru; $p.Id | Out-File -Encoding ascii '%CFPID%'"
if errorlevel 1 goto :tunnel_failed

set /a TRIES=0
:tunnel_wait
set "PUBLIC_URL="
for /f "usebackq delims=" %%U in (`powershell -NoProfile -Command "$m = [regex]::Match((Get-Content -Raw '%CFERR%' -ErrorAction SilentlyContinue), 'https://[a-z0-9-]+\.trycloudflare\.com'); if ($m.Success) { $m.Value }"`) do set "PUBLIC_URL=%%U"
if defined PUBLIC_URL goto :tunnel_up
set /a TRIES+=1
if !TRIES! GEQ %WAIT_SECONDS% goto :tunnel_slow
ping -n 2 127.0.0.1 >nul
goto :tunnel_wait

:tunnel_up
> "%URLFILE%" echo !PUBLIC_URL!
echo [OK] Tunnel URL: !PUBLIC_URL!

rem --- 4. Verify the public endpoint -----------------------------------------
:verify
set "READY=000"
set "CODE=000"
for /f "usebackq delims=" %%C in (`curl.exe -s -o NUL -w "%%{http_code}" --max-time 25 "!PUBLIC_URL!/health"`) do set "CODE=%%C"
if not "!CODE!"=="200" goto :public_down
for /f "usebackq delims=" %%C in (`curl.exe -s -o NUL -w "%%{http_code}" --max-time 30 "!PUBLIC_URL!/ready"`) do set "READY=%%C"

echo.
echo [OK] Aetrix is running.
echo   backend : %LOCAL%  (health 200)
echo   tunnel  : !PUBLIC_URL!
if "!READY!"=="200" (
  echo   ready   : !PUBLIC_URL!/ready  -^> 200, database reachable
) else (
  echo   ready   : !PUBLIC_URL!/ready  -^> HTTP !READY!
  echo             The API answers, but the database in backend\.env is not
  echo             reachable. No data request will succeed until it is.
)
echo   health  : !PUBLIC_URL!/health
echo.
echo Next step for the deployed frontend:
echo   set VITE_AETRIX_API_URL=!PUBLIC_URL! in frontend\.env, rebuild and
echo   redeploy. The URL is compiled into the bundle and changes on every
echo   tunnel restart.
echo.
echo Keep this window or close it: the servers run detached. Use
echo STOP_AETRIX.bat to stop the backend and the tunnel.
if /I not "%AETRIX_NO_PAUSE%"=="1" pause
endlocal & exit /b 0

rem --- Failure paths ---------------------------------------------------------
:public_down
echo [ERROR] The tunnel did not answer !PUBLIC_URL!/health (HTTP !CODE!).
goto :tunnel_failed_cleanup

:tunnel_slow
echo [ERROR] No public tunnel URL appeared within %WAIT_SECONDS% seconds.
if exist "%CFERR%" (
  echo         Last lines of %CFERR%:
  powershell -NoProfile -Command "Get-Content -Tail 15 '%CFERR%'"
)
goto :tunnel_failed_cleanup

:tunnel_failed_cleanup
call :stop_tunnel
goto :fail

:tunnel_failed
echo [ERROR] Could not start cloudflared.
goto :fail

:backend_failed
echo [ERROR] The backend did not start. See the message above.
goto :fail

:no_cloudflared
echo [ERROR] cloudflared.exe was not found.
echo         Install it once with:
echo           winget install --id Cloudflare.cloudflared
echo         or download it from https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/
goto :fail

:no_env
echo [ERROR] backend\.env is missing. Copy backend\.env.example and fill it in.
goto :fail

:no_curl
echo [ERROR] curl.exe was not found on PATH; the health checks need it.
goto :fail

rem --- Subroutines ----------------------------------------------------------
:tunnel_pid
set "TUNNEL_PID="
if not exist "%CFPID%" exit /b 0
set "CANDIDATE="
for /f "usebackq delims=" %%P in ("%CFPID%") do if not defined CANDIDATE set "CANDIDATE=%%P"
if not defined CANDIDATE exit /b 0
set "OURS=foreign"
for /f "usebackq delims=" %%R in (`powershell -NoProfile -Command "$p = Get-CimInstance Win32_Process -Filter 'ProcessId=%CANDIDATE%' -ErrorAction SilentlyContinue; if ($p -and $p.CommandLine -match 'cloudflared' -and $p.CommandLine -match '127\.0\.0\.1:8000') { 'ours' } else { 'foreign' }"`) do set "OURS=%%R"
if /I "!OURS!"=="ours" set "TUNNEL_PID=%CANDIDATE%"
exit /b 0

:stop_tunnel
call :tunnel_pid
if not defined TUNNEL_PID exit /b 0
echo         Stopping the tunnel this script started (PID !TUNNEL_PID!).
taskkill /PID !TUNNEL_PID! /T /F >nul 2>&1
call :clear_tunnel
exit /b 0

:clear_tunnel
if exist "%CFPID%" del /q "%CFPID%" >nul 2>&1
if exist "%URLFILE%" del /q "%URLFILE%" >nul 2>&1
exit /b 0

:fail
if /I not "%AETRIX_NO_PAUSE%"=="1" pause
endlocal & exit /b 1
