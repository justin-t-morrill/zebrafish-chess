param(
    [int]$Port = 8765,
    [switch]$NoBrowser,
    [switch]$Check
)
$ErrorActionPreference = "Stop"
& (Join-Path $PSScriptRoot 'tools\launchers\Start-Zebrafish.ps1') -Action play -Port $Port -NoBrowser:$NoBrowser -Check:$Check
exit $LASTEXITCODE
