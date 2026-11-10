@echo off
setlocal
title Aetrix - AUTOSTART
rem Registers the Windows logon task that runs START_AETRIX.bat's entry point
rem after a reboot, so the backend and its public HTTPS route come back without
rem a manual start.
rem
rem   AUTOSTART_AETRIX.bat install     register the logon task
rem   AUTOSTART_AETRIX.bat show        print the registered task (default)
rem   AUTOSTART_AETRIX.bat uninstall   remove it
rem
rem Registering needs an elevated prompt; this script never elevates itself.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\install-aetrix-autostart.ps1" %*
exit /b %ERRORLEVEL%
