$ErrorActionPreference = 'Stop'
& (Join-Path $PSScriptRoot '..\launchers\Start-Zebrafish.ps1') -Action verify
exit $LASTEXITCODE
