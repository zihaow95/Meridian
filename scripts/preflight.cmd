@echo off
REM Project Meridian environment preflight launcher.
REM Delegates to preflight.ps1 and passes through its exit code so PowerShell
REM execution policy cannot silently swallow the result.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0preflight.ps1"
exit /b %ERRORLEVEL%
