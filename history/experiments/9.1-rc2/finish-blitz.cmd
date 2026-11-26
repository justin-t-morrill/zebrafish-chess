@echo off
setlocal
title Zebrafish 9.2 blitz match
echo Checking the saved 180+1 match and release status.
set "runner=%~dp0..\..\..\testing\results\overnight_9_0_20261124\watch_blitz_releases.py"
set "python=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
for %%P in (py.exe) do set "launcher=%%~$PATH:P"
if not exist "%python%" if defined launcher for %%P in ("%launcher%") do set "python=%%~dpP..\Python312\python.exe"
if exist "%python%" (
    "%python%" -u "%runner%"
) else (
    py -3.12 -u "%runner%"
)
set "result=%ERRORLEVEL%"
if not "%result%"=="0" pause
exit /b %result%
