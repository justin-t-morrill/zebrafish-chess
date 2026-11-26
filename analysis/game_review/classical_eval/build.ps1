$ErrorActionPreference = "Stop"
& (Join-Path $PSScriptRoot "..\..\..\engine\helpers\classical\build.ps1")
exit $LASTEXITCODE
