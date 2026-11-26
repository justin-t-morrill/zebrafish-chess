param([int]$Workers = 6)
$ErrorActionPreference = "Stop"
$Here = $PSScriptRoot
$Python = "C:\Users\Justin\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
$env:PYTHONPATH = ((Join-Path $Here "..\game_review\vendor_runtime"), `
                   (Join-Path $Here "model_runtime"), `
                   (Join-Path $Here "external\ratingnet_runtime") -join ";")
$Data = Join-Path $Here "data"
$Eval = Join-Path $Data "ratingnet_evaluation"
$Out = Join-Path $Data "node_budget_1m_5000"
New-Item -ItemType Directory -Force $Out | Out-Null
$moves1m = Join-Path $Out "move_features_1m.csv"
$moves100k = Join-Path $Out "move_features_100k_matched.csv"
$features1m = Join-Path $Out "player_game_features_1m.csv"
$features100k = Join-Path $Out "player_game_features_100k_matched.csv"

& $Python (Join-Path $Here "analyze_elo_games.py") `
  --pgn (Join-Path $Data "lichess_blitz_balanced_2026-07.pgn") `
  --manifest (Join-Path $Data "lichess_blitz_balanced_2026-07.csv") `
  --engine (Join-Path $Here "..\..\build\current\chess.exe") `
  --output $moves1m --nodes 1000000 --workers $Workers `
  --decisions-per-player 12 --minimum-ply 13 `
  --selected-games (Join-Path $Data "detailed_5000_game_indices.txt") --progress-every 25
if ($LASTEXITCODE -ne 0) { throw "One-million-node extraction failed." }

& $Python (Join-Path $Here "compare_node_budgets.py") `
  --baseline (Join-Path $Data "move_features_100k.csv") --candidate $moves1m `
  --output-dir $Out --baseline-subset $moves100k
if ($LASTEXITCODE -ne 0) { throw "Node-budget comparison failed." }

& $Python (Join-Path $Here "build_player_game_features.py") --moves $moves100k --output $features100k
if ($LASTEXITCODE -ne 0) { throw "Matched 100k aggregation failed." }
& $Python (Join-Path $Here "build_player_game_features.py") --moves $moves1m --output $features1m
if ($LASTEXITCODE -ne 0) { throw "One-million-node aggregation failed." }

$common = @(
  "--ratingnet-predictions", (Join-Path $Here "validation\ratingnet_calibrated\finetuned_adapted_predictions.npz"),
  "--balanced-data", (Join-Path $Eval "balanced_2026-07.npz"),
  "--indices", (Join-Path $Eval "split_indices.npz"),
  "--production-metadata", (Join-Path $Here "models\releases\performance_elo_v2_standard\metadata.json"),
  "--dataset-kind", "balanced", "--threads", "$Workers"
)
& $Python (Join-Path $Here "train_ratingnet_catboost_fusion.py") --features $features100k @common `
  --output-dir (Join-Path $Here "models\experiments\ratingnet_catboost_fusion_100k_matched")
if ($LASTEXITCODE -ne 0) { throw "Matched 100k fusion training failed." }
& $Python (Join-Path $Here "train_ratingnet_catboost_fusion.py") --features $features1m @common `
  --output-dir (Join-Path $Here "models\experiments\ratingnet_catboost_fusion_1m")
if ($LASTEXITCODE -ne 0) { throw "One-million-node fusion training failed." }

Write-Host "Experiment complete. Report: $(Join-Path $Out 'REPORT.md')"
