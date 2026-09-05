param(
    [Parameter(Mandatory = $true)]
    [int]$WaitProcessId
)

$ErrorActionPreference = "Stop"
$running = Get-Process -Id $WaitProcessId -ErrorAction SilentlyContinue
if ($null -ne $running) {
    Write-Output "Waiting for current Cute Chess process $WaitProcessId to finish..."
    Wait-Process -Id $WaitProcessId
}

Write-Output "Current SPRT finished. Starting capture-history SPRT."
& (Join-Path $PSScriptRoot "run_version_sprt.ps1") `
    -EngineA 5.4_probcut_capture_history `
    -EngineB 5.4_probcut `
    -MaxGames 10000 `
    -TimeControl "3+0.03" `
    -Concurrency 6 `
    -Elo0 0 `
    -Elo1 10

exit $LASTEXITCODE
