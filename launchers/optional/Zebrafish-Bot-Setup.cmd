@echo off
title Zebrafish local bot setup
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0..\..\integrations\lichess\setup-token.ps1"
pause
