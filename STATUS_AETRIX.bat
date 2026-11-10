@echo off
setlocal
title Aetrix - STATUS
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\aetrix-stack.ps1" status
exit /b %ERRORLEVEL%
