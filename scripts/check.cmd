@echo off
REM Project Meridian unified quality gate launcher.
REM Delegates to check.ps1 and passes through its exit code.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0check.ps1"
exit /b %ERRORLEVEL%
