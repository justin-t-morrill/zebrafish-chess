@echo off
setlocal
set "python=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
set "dashboard=%~dp0..\..\history\experiments\9.1-rc2\local_scoreboard.py"
if exist "%python%" (
    "%python%" -B "%dashboard%" --pause
) else (
    py -3.12 -B "%dashboard%" --pause
)
if errorlevel 1 pause
