@echo off
REM Wrapper for start-pilot.ps1. Pass -PilotHost <LAN-IP> as the first argument.
setlocal
if "%~1"=="" (
  echo Usage: scripts\start-pilot.cmd -PilotHost 192.168.x.x
  exit /b 1
)
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start-pilot.ps1" %*
exit /b %ERRORLEVEL%
