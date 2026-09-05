. (Join-Path $PSScriptRoot "project_paths.ps1")
$root = Get-ChessProjectRoot
$results = Join-Path $root "testing\results\calibration\v8.3"
$statePath = Join-Path $results "ccrl-calibration-state.json"
if (Test-Path -LiteralPath $statePath) {
    $state = Get-Content -LiteralPath $statePath -Raw | ConvertFrom-Json
    Write-Host "Status: $($state.status)"
    Write-Host "Current opponent: $($state.current)"
    $opponentCount = if ($state.opponent_count) { $state.opponent_count } else { 4 }
    Write-Host "Completed opponents: $($state.completed.Count)/$opponentCount"
}
$active = Get-Process -Name cutechess-cli -ErrorAction SilentlyContinue
Write-Host "Cute Chess: $(if ($active) {'running'} else {'not running'})"
$latest = Get-ChildItem -LiteralPath $results -Filter "*.log" -File -ErrorAction SilentlyContinue |
    Sort-Object LastWriteTime -Descending | Select-Object -First 1
if ($latest) {
    Write-Host "Latest match: $($latest.Name)"
    Select-String -LiteralPath $latest.FullName -Pattern '^Score of ','^Elo difference:' |
        Select-Object -Last 2 -ExpandProperty Line
}
