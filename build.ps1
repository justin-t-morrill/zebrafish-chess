$ErrorActionPreference = 'Stop'
& (Join-Path $PSScriptRoot 'tools\launchers\Start-Zebrafish.ps1') -Action build
exit $LASTEXITCODE
