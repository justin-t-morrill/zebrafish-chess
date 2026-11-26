@echo off
title Zebrafish
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0start_zebrafish.ps1" %*
if errorlevel 1 pause
