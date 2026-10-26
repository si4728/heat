@echo off
rem run.ps1 checks the local MariaDB instance and starts it if needed.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0run.ps1" %*
exit /b %errorlevel%
