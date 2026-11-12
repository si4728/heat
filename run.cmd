@echo off
cd c:\access\heat\iris2
rem run.ps1 checks the local MariaDB instance and starts it if needed.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0run.ps1" -ListenHost 0.0.0.0 -Port 4824 %*
exit /b %errorlevel%
