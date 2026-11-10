@echo off
setlocal
title Aetrix - STOP
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\aetrix-stack.ps1" stop
exit /b %ERRORLEVEL%
