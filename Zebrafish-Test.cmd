@echo off
title Zebrafish version tests
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\launchers\Start-Zebrafish.ps1" -Action test %*
if errorlevel 1 pause
