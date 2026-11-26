$project = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..'))
$paths = Get-Content -LiteralPath (Join-Path $project 'config\paths.json') -Raw | ConvertFrom-Json
$stateDirectory = Join-Path (Join-Path $project $paths.tablebases) 'logs'
$pidPath = Join-Path $stateDirectory "download.pid"
$outPath = Join-Path $stateDirectory "download.out.log"
$errorPath = Join-Path $stateDirectory "download.error.log"

$running = $false
if (Test-Path -LiteralPath $pidPath) {
    $downloadPid = [int](Get-Content -LiteralPath $pidPath -Raw)
    $running = [bool](Get-Process -Id $downloadPid -ErrorAction SilentlyContinue)
}

if ($running) {
    Write-Host "Download is running (process $downloadPid)."
} else {
    Write-Host "Download is not currently running."
}

if (Test-Path -LiteralPath $outPath) {
    Write-Host ""
    Write-Host "Latest progress:"
    Get-Content -LiteralPath $outPath -Tail 15
}

if ((Test-Path -LiteralPath $errorPath) -and ((Get-Item -LiteralPath $errorPath).Length -gt 0)) {
    Write-Host ""
    Write-Host "Latest error output:"
    Get-Content -LiteralPath $errorPath -Tail 10
}
