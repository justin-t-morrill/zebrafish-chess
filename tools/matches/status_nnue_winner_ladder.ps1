. (Join-Path $PSScriptRoot "project_paths.ps1")
$root = Get-ChessProjectRoot
$results = Join-Path $root "local\results\sprt\v8"
$statePath = Join-Path $results "nnue-winner-ladder-state.json"
$ladderLog = Join-Path $results "nnue-winner-ladder.log"
$queueLog = Join-Path $results "nnue-winner-gauntlet-queue.log"
if (Test-Path -LiteralPath $statePath) {
    $state = Get-Content -LiteralPath $statePath -Raw | ConvertFrom-Json
    Write-Host "Status: $($state.status)"
    Write-Host "Round: $($state.round)/3"
    if ($state.current) { Write-Host "Current: $($state.current)" }
    if ($state.champion) { Write-Host "Champion: $($state.champion)" }
}
$active = Get-Process -Name cutechess-cli -ErrorAction SilentlyContinue
Write-Host "Cute Chess: $(if ($active) { 'running' } else { 'not running' })"
if (Test-Path -LiteralPath $ladderLog) {
    Write-Host "Recent ladder results:"
    Get-Content -LiteralPath $ladderLog -Tail 8
}
if (Test-Path -LiteralPath $queueLog) {
    Write-Host "Winner gauntlet queue:"
    Get-Content -LiteralPath $queueLog -Tail 3
}
$match = Get-ChildItem -LiteralPath $results -File -Filter "8.2-vs-8.2-sprt-*.log" |
    Sort-Object LastWriteTime -Descending | Select-Object -First 1
if ($match) {
    Write-Host "Current match statistics:"
    Select-String -LiteralPath $match.FullName -Pattern '^Score of |^Elo difference:|^SPRT:' |
        Select-Object -Last 3 -ExpandProperty Line
}
