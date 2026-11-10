@echo off
setlocal
title Aetrix - START
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\aetrix-stack.ps1" start
set AETRIX_EXIT=%ERRORLEVEL%
if not "%AETRIX_EXIT%"=="0" (
  echo.
  echo Aetrix did not start. Read the failure above and the logs in .tmp\aetrix\stack.
)
exit /b %AETRIX_EXIT%
