@echo off
setlocal
set "ROOT=%~dp0"
powershell -ExecutionPolicy Bypass -File "%ROOT%start_vidnorm.ps1"
exit /b %errorlevel%
