@echo off
title Zebrafish native engine
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\launchers\Start-Zebrafish.ps1" -Action native %*
if errorlevel 1 pause
