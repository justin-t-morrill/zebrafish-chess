$ErrorActionPreference = "Stop"
$suite = $PSScriptRoot

# Ninety CCRL-style games centered on Engine 7.1's current estimate. Each
# opponent receives 30 games, with every selected opening played once per
# color. Sixteen engine threads and concurrency one maximize playing strength
# without oversubscribing the host's 16 logical processors.
& (Join-Path $suite "run_tournament.ps1") `
    -Opponent Gauntlet `
    -GauntletOpponents @("Stockfish2900", "Stockfish3000", "Stockfish3100") `
    -Games 30 `
    -TimeControl "120+1" `
    -Concurrency 1 `
    -EngineThreads 16 `
    -EngineVersion 7.1
