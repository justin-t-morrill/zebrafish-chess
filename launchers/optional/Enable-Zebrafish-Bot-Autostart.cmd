@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0..\..\integrations\lichess\enable-autostart.ps1"
pause
