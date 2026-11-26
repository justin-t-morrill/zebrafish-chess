@echo off
title Zebrafish
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0..\tools\launchers\Start-Zebrafish.ps1" -Action play %*
if errorlevel 1 pause
