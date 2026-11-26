@echo off
title Zebrafish local bot setup
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0integrations\lichess\setup-token.ps1"
pause
