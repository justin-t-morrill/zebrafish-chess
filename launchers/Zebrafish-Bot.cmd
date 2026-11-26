@echo off
setlocal
title Zebrafish Lichess bot
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0..\integrations\lichess\run-bot.ps1" %*
if errorlevel 1 pause
