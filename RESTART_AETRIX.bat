@echo off
setlocal
title Aetrix - RESTART
rem Stops only the processes this stack started (backend, tunnel, monitor, worker),
rem waits for them to exit, then starts the stack again and re-runs the health,
rem readiness and public-origin checks. Safe to run when nothing is running.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\aetrix-stack.ps1" restart
set AETRIX_EXIT=%ERRORLEVEL%
if not "%AETRIX_EXIT%"=="0" (
  echo.
  echo Aetrix did not restart cleanly. Read the failure above and the logs in .tmp\aetrix\stack.
)
exit /b %AETRIX_EXIT%
