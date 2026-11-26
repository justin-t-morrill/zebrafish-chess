@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0integrations\lichess\enable-autostart.ps1"
pause
