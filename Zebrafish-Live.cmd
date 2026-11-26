@echo off
setlocal
title Zebrafish live tests
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\launchers\Start-Zebrafish.ps1" -Action live %*
if errorlevel 1 pause
