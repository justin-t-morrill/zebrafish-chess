@echo off
setlocal
title Zebrafish saved release match
set "python=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
set "dashboard=%~dp0..\..\history\experiments\9.1-rc2\local_scoreboard.py"
if exist "%python%" (
    "%python%" -B -u "%dashboard%" --desktop --resume --open
) else (
    py -3.12 -B -u "%dashboard%" --desktop --resume --open
)
if errorlevel 1 pause
