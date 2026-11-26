param([int]$NaturalGames = 60000)
$ErrorActionPreference = "Stop"
$Here = $PSScriptRoot
$Python = "C:\Users\Justin\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
$Data = Join-Path $Here "data\ratingnet_evaluation"
$NaturalPgn = Join-Path $Data "lichess_blitz_natural_2026-07.pgn"
$NaturalNpz = Join-Path $Data "natural_2026-07.npz"
$BalancedPgn = Join-Path $Here "data\lichess_blitz_balanced_2026-07.pgn"
$BalancedNpz = Join-Path $Data "balanced_2026-07.npz"
$Training = Join-Path $Here "data\ratingnet_overnight\ratingnet_250k.npz"
New-Item -ItemType Directory -Force $Data | Out-Null

if (-not (Test-Path $NaturalPgn)) {
    & $Python (Join-Path $Here "download_lichess_blitz.py") `
        --url "https://database.lichess.org/standard/lichess_db_standard_rated_2026-07.pgn.zst" `
        --output $NaturalPgn --target-games $NaturalGames --max-games-per-player 5
    if ($LASTEXITCODE -ne 0) { throw "Natural July sample download failed." }
}
if (-not (Test-Path $NaturalNpz)) {
    & $Python (Join-Path $Here "prepare_ratingnet_dataset.py") $NaturalPgn --output $NaturalNpz
    if ($LASTEXITCODE -ne 0) { throw "Natural evaluation preparation failed." }
}
if (-not (Test-Path $BalancedNpz)) {
    & $Python (Join-Path $Here "prepare_ratingnet_dataset.py") $BalancedPgn --output $BalancedNpz
    if ($LASTEXITCODE -ne 0) { throw "Balanced evaluation preparation failed." }
}

& $Python (Join-Path $Here "build_ratingnet_evaluation_sets.py") `
    --training $Training --natural $NaturalNpz --balanced $BalancedNpz `
    --output-dir $Data --train-through 2026.05
if ($LASTEXITCODE -ne 0) { throw "Evaluation-set splitting failed." }
Write-Host "RatingNet evaluation sets are ready in $Data"
