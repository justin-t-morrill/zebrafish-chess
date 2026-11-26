$ErrorActionPreference = 'Stop'
& (Join-Path $PSScriptRoot 'tools\launchers\Start-Zebrafish.ps1') -Action verify
exit $LASTEXITCODE
