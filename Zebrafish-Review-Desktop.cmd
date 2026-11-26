@echo off
title Zebrafish desktop reviewer
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\launchers\Start-Zebrafish.ps1" -Action desktop %*
if errorlevel 1 pause
