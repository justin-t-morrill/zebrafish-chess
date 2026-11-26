param([int]$GamesPerHalf = 10000, [int]$Workers = 6, [int]$Nodes = 100000)
$ErrorActionPreference = "Stop"
$Here = $PSScriptRoot
$Python = "C:\Users\Justin\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
$Data = Join-Path $Here "data\ratingnet_evaluation"
$Output = Join-Path $Here "data\natural_fusion_20k"
New-Item -ItemType Directory -Force $Output | Out-Null
$selected = Join-Path $Output "selected_games.txt"
$moves = Join-Path $Output "move_features_100k.csv"
$features = Join-Path $Output "player_game_features.csv"

if (-not (Test-Path $selected)) {
    & $Python (Join-Path $Here "select_natural_fusion_games.py") `
      --data (Join-Path $Data "natural_2026-07.npz") `
      --indices (Join-Path $Data "split_indices.npz") `
      --manifest (Join-Path $Data "lichess_blitz_natural_2026-07.csv") `
      --output $selected --per-half $GamesPerHalf
    if ($LASTEXITCODE -ne 0) { throw "Natural-game selection failed." }
}
& $Python (Join-Path $Here "analyze_elo_games.py") `
  --pgn (Join-Path $Data "lichess_blitz_natural_2026-07.pgn") `
  --manifest (Join-Path $Data "lichess_blitz_natural_2026-07.csv") `
  --engine (Join-Path $Here "..\..\build\current\chess.exe") `
  --output $moves --nodes $Nodes --workers $Workers `
  --decisions-per-player 12 --minimum-ply 13 --selected-games $selected `
  --progress-every 100
if ($LASTEXITCODE -ne 0) { throw "Natural engine-feature extraction failed." }

& $Python (Join-Path $Here "build_player_game_features.py") --moves $moves --output $features
if ($LASTEXITCODE -ne 0) { throw "Natural game aggregation failed." }

& $Python (Join-Path $Here "train_ratingnet_catboost_fusion.py") `
  --features $features `
  --ratingnet-predictions (Join-Path $Here "validation\ratingnet_calibrated\finetuned_adapted_predictions.npz") `
  --balanced-data (Join-Path $Data "natural_2026-07.npz") `
  --indices (Join-Path $Data "split_indices.npz") `
  --production-metadata (Join-Path $Here "models\releases\performance_elo_v2_standard\metadata.json") `
  --output-dir (Join-Path $Here "models\experiments\ratingnet_catboost_fusion_natural") `
  --dataset-kind natural --threads $Workers
if ($LASTEXITCODE -ne 0) { throw "Natural RatingNet fusion training failed." }
