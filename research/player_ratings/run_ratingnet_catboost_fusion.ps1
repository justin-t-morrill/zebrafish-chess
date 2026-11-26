$ErrorActionPreference = "Stop"
$Here = $PSScriptRoot
$Python = "C:\Users\Justin\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
& $Python (Join-Path $Here "train_ratingnet_catboost_fusion.py") `
  --features (Join-Path $Here "data\player_game_features_30000_clock_v2.csv") `
  --ratingnet-predictions (Join-Path $Here "validation\ratingnet_calibrated\finetuned_adapted_predictions.npz") `
  --balanced-data (Join-Path $Here "data\ratingnet_evaluation\balanced_2026-07.npz") `
  --indices (Join-Path $Here "data\ratingnet_evaluation\split_indices.npz") `
  --production-metadata (Join-Path $Here "models\releases\performance_elo_v2_standard\metadata.json") `
  --output-dir (Join-Path $Here "models\experiments\ratingnet_catboost_fusion") `
  --threads 6
if ($LASTEXITCODE -ne 0) { throw "RatingNet/CatBoost fusion training failed." }
