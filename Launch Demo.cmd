@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0run.ps1" launch-demo
if errorlevel 1 pause
