@echo off
title Zebrafish candidate build
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0..\tools\launchers\Start-Zebrafish.ps1" -Action build %*
pause
