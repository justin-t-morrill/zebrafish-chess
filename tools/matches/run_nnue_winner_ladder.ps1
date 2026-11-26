param(
    [int]$MaxGames = 10000,
    [string]$TimeControl = "1+0.1",
    [int]$Concurrency = 6
)

$ErrorActionPreference = "Continue"
. (Join-Path $PSScriptRoot "project_paths.ps1")
$root = Get-ChessProjectRoot
$results = Join-Path $root "local\results\sprt\v8"
$statePath = Join-Path $results "nnue-winner-ladder-state.json"
$ladderLog = Join-Path $results "nnue-winner-ladder.log"
$sprtScript = Join-Path $PSScriptRoot "run_version_sprt.ps1"

$candidates = [ordered]@{
    "full-plain128" = Join-Path $root "local\checkpoints\nnue\minimal-chess-768x128-lichessfull5ep-wdl000-40\quantised.bin"
    "full-plain256" = Join-Path $root "local\checkpoints\nnue\minimal-chess-768x256-lichessfull5ep-wdl000-40\quantised.bin"
    "full-king128" = Join-Path $root "local\checkpoints\nnue\minimal-chess-king10x128-lichessfull10ep-wdl000-40\quantised.bin"
    "full-king256" = Join-Path $root "local\checkpoints\nnue\minimal-chess-king10x256-lichessfull10ep-wdl000-40\quantised.bin"
}
foreach ($path in $candidates.Values) {
    if (-not (Test-Path -LiteralPath $path)) { throw "Missing candidate: $path" }
}

$state = [ordered]@{
    status = "running"
    round = 0
    current = ""
    champion = ""
    completed = @()
}
function Save-State {
    $state | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $statePath
}

# Keep ladder messages separate from the verbose per-game Cute Chess logs.
function Add-LadderMessage([string]$message) {
    $line = "[$(Get-Date -Format s)] $message"
    Add-Content -LiteralPath $ladderLog -Value $line
    Write-Host $line
}

function Run-Round([int]$number, [string]$challengerName, [string]$challengerPath,
                   [string]$championName, [string]$championPath) {
    $state.round = $number
    $state.current = "$challengerName vs $championName"
    $state.champion = $championName
    Save-State
    Add-LadderMessage "Round $number starting: $challengerName vs $championName"
    $started = Get-Date
    & $sprtScript -EngineA 8.2 -EngineB 8.2 `
        -EvalFileA $challengerPath -EvalFileB $championPath `
        -MaxGames $MaxGames -TimeControl $TimeControl -Concurrency $Concurrency `
        -ThreadsA 1 -ThreadsB 1 -Elo0 -5 -Elo1 5 2>&1 | Out-Host
    if ($LASTEXITCODE -ne 0) { throw "Round $number launcher failed with exit code $LASTEXITCODE" }

    $matchLog = Get-ChildItem -LiteralPath $results -File -Filter "8.2-vs-8.2-sprt-*.log" |
        Where-Object LastWriteTime -ge $started.AddSeconds(-2) |
        Sort-Object LastWriteTime -Descending | Select-Object -First 1
    if (-not $matchLog) { throw "Could not locate the Round $number match log" }
    $decision = Select-String -LiteralPath $matchLog.FullName -Pattern '^SPRT:.*H[01] was accepted' |
        Select-Object -Last 1 -ExpandProperty Line
    $elo = Select-String -LiteralPath $matchLog.FullName -Pattern '^Elo difference:' |
        Select-Object -Last 1 -ExpandProperty Line
    if (-not $decision) {
        $state.status = "undecided"
        $state.current = "$challengerName vs $championName reached the game limit"
        Save-State
        Add-LadderMessage "Round $number was undecided. $elo"
        throw "SPRT reached its game limit without accepting H0 or H1; ladder stopped."
    }
    $challengerWon = $decision -match 'H1 was accepted'
    $winnerName = if ($challengerWon) { $challengerName } else { $championName }
    $winnerPath = if ($challengerWon) { $challengerPath } else { $championPath }
    $state.completed += [ordered]@{
        round = $number
        matchup = "$challengerName vs $championName"
        winner = $winnerName
        elo = $elo
        decision = $decision
        log = $matchLog.FullName
    }
    $state.champion = $winnerName
    Save-State
    Add-LadderMessage "Round $number winner: $winnerName. $elo"
    return @($winnerName, $winnerPath)
}

try {
    $winner = Run-Round 1 "full-plain256" $candidates["full-plain256"] `
        "full-plain128" $candidates["full-plain128"]
    $winner = Run-Round 2 "full-king128" $candidates["full-king128"] `
        $winner[0] $winner[1]
    $winner = Run-Round 3 "full-king256" $candidates["full-king256"] `
        $winner[0] $winner[1]
    $state.status = "complete"
    $state.current = ""
    $state.champion = $winner[0]
    Save-State
    Add-LadderMessage "Ladder complete. Winner: $($winner[0])"
} catch {
    if ($state.status -eq "running") { $state.status = "failed" }
    Save-State
    Add-LadderMessage "Ladder stopped: $($_.Exception.Message)"
    throw
}
