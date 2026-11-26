@echo off
title Zebrafish results
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0..\tools\launchers\Start-Zebrafish.ps1" -Action results %*
if errorlevel 1 pause
