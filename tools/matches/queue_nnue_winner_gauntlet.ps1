param(
    [int]$GamesPerOpponent = 120,
    [string]$TimeControl = "1+0.1",
    [int]$Concurrency = 1,
    [int]$Threads = 16
)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "project_paths.ps1")
$root = Get-ChessProjectRoot
$results = Join-Path $root "local\results\sprt\v8"
$statePath = Join-Path $results "nnue-winner-ladder-state.json"
$queueLog = Join-Path $results "nnue-winner-gauntlet-queue.log"

$candidates = @{
    "full-plain128" = Join-Path $root "local\checkpoints\nnue\minimal-chess-768x128-lichessfull5ep-wdl000-40\quantised.bin"
    "full-plain256" = Join-Path $root "local\checkpoints\nnue\minimal-chess-768x256-lichessfull5ep-wdl000-40\quantised.bin"
    "full-king128" = Join-Path $root "local\checkpoints\nnue\minimal-chess-king10x128-lichessfull10ep-wdl000-40\quantised.bin"
    "full-king256" = Join-Path $root "local\checkpoints\nnue\minimal-chess-king10x256-lichessfull10ep-wdl000-40\quantised.bin"
}

function Add-QueueMessage([string]$message) {
    $line = "[$(Get-Date -Format s)] $message"
    Add-Content -LiteralPath $queueLog -Value $line
    Write-Host $line
}

Add-QueueMessage "Waiting to run the practical 16-thread winner gauntlet."
while ($true) {
    if (Test-Path -LiteralPath $statePath) {
        try {
            $state = Get-Content -LiteralPath $statePath -Raw | ConvertFrom-Json
            if ($state.status -eq "complete") { break }
            if ($state.status -in @("failed", "undecided")) {
                throw "Ladder ended with status '$($state.status)'; no final winner was selected."
            }
        } catch [System.ArgumentException] {
            # The ladder may be replacing the small JSON state file; retry.
        }
    }
    Start-Sleep -Seconds 30
}

$winner = [string]$state.champion
if (-not $candidates.ContainsKey($winner)) { throw "Unknown ladder winner: $winner" }
$evalFile = $candidates[$winner]
Add-QueueMessage "Starting 360-game practical-strength gauntlet for $winner ($Threads threads per engine)."

& (Join-Path $PSScriptRoot "run_tournament.ps1") `
    -Opponent Gauntlet `
    -GauntletOpponents @("Stockfish2900", "Stockfish3000", "Stockfish3100") `
    -Games $GamesPerOpponent `
    -TimeControl $TimeControl `
    -Concurrency $Concurrency `
    -EngineThreads $Threads `
    -OpponentThreads $Threads `
    -EngineVersion 8.2 `
    -EvalFile $evalFile

Add-QueueMessage "Winner gauntlet completed for $winner."
