param(
    [int]$MaxGames = 0,
    [int]$MaxPlies = 100
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Python = "C:\Users\Justin\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
if (-not (Test-Path $Python)) { $Python = "python" }
$Data = Join-Path $PSScriptRoot "data"
$Output = Join-Path $Data "ratingnet_raw_multimonth.npz"
$Pgns = @(
    (Join-Path $Data "lichess_blitz_stacker_holdout_2026-04.pgn"),
    (Join-Path $Data "lichess_blitz_paired_2026-05.pgn"),
    (Join-Path $Data "lichess_blitz_fresh_2026-06.pgn"),
    (Join-Path $Data "lichess_blitz_balanced_2026-07.pgn")
)

& $Python (Join-Path $PSScriptRoot "prepare_ratingnet_dataset.py") @Pgns `
    --output $Output `
    --splits (Join-Path $Data "games_with_splits.csv") `
    --max-games $MaxGames `
    --max-plies $MaxPlies
if ($LASTEXITCODE -ne 0) { throw "RatingNet preparation failed." }

Write-Host "Prepared RatingNet data: $Output"
