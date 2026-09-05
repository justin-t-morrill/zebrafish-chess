[CmdletBinding()]
param(
    [ValidateSet("small", "wdl6", "dtz6", "all")]
    [string]$Set = "all"
)

$ErrorActionPreference = "Stop"
$stateDirectory = Join-Path $PSScriptRoot "logs"
$pidPath = Join-Path $stateDirectory "download.pid"
$outPath = Join-Path $stateDirectory "download.out.log"
$errorPath = Join-Path $stateDirectory "download.error.log"
$downloader = Join-Path $PSScriptRoot "download_syzygy.ps1"
New-Item -ItemType Directory -Force -Path $stateDirectory | Out-Null

if (Test-Path -LiteralPath $pidPath) {
    $oldPid = [int](Get-Content -LiteralPath $pidPath -Raw)
    if (Get-Process -Id $oldPid -ErrorAction SilentlyContinue) {
        throw "A tablebase download is already running as process $oldPid."
    }
}

$arguments = @(
    "-NoProfile",
    "-ExecutionPolicy", "Bypass",
    "-File", ('"' + $downloader + '"'),
    "-Set", $Set
)

$process = Start-Process -FilePath "powershell.exe" -ArgumentList $arguments `
    -WindowStyle Hidden -RedirectStandardOutput $outPath -RedirectStandardError $errorPath -PassThru
Set-Content -LiteralPath $pidPath -Value $process.Id

Write-Host "Syzygy download started in the background (process $($process.Id))."
Write-Host "Progress log: $outPath"
Write-Host "Error log:    $errorPath"
