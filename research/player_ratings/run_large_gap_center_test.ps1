param([int]$MinimumGap=150,[int]$Workers=6,[int]$Nodes=100000)
$ErrorActionPreference='Stop';$Here=$PSScriptRoot
$Python='C:\Users\Justin\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
$env:PYTHONPATH=((Join-Path $Here 'model_runtime'),(Join-Path $Here '..\game_review\vendor_runtime') -join ';')
$Eval=Join-Path $Here 'data\ratingnet_evaluation';$Out=Join-Path $Here "data\large_gap_center_$MinimumGap"
New-Item -ItemType Directory -Force $Out|Out-Null
$manifest=Join-Path $Eval 'lichess_blitz_natural_2026-07.csv';$pgn=Join-Path $Eval 'lichess_blitz_natural_2026-07.pgn'
$selected=Join-Path $Out 'selected_games.txt';$rn=Join-Path $Out 'ratingnet.csv';$moves=Join-Path $Out 'moves.csv';$features=Join-Path $Out 'player_games.csv';$stack=Join-Path $Out 'stack.csv'
& $Python (Join-Path $Here 'prepare_large_gap_center_test.py') --manifest $manifest --dataset (Join-Path $Eval 'natural_2026-07.npz') --predictions (Join-Path $Here 'validation\ratingnet_calibrated\finetuned_adapted_predictions.npz') --minimum-gap $MinimumGap --selected $selected --ratingnet-csv $rn
if($LASTEXITCODE){throw 'Large-gap selection failed'}
& $Python (Join-Path $Here 'analyze_elo_games.py') --pgn $pgn --manifest $manifest --engine (Join-Path $Here '..\..\build\current\chess.exe') --output $moves --nodes $Nodes --workers $Workers --decisions-per-player 12 --minimum-ply 13 --selected-games $selected --progress-every 25
if($LASTEXITCODE){throw 'Large-gap engine analysis failed'}
& $Python (Join-Path $Here 'build_player_game_features.py') --moves $moves --output $features
if($LASTEXITCODE){throw 'Large-gap aggregation failed'}
& $Python (Join-Path $Here 'build_stacking_features.py') --moves $moves --game-features $features --experiment (Join-Path $Here 'models\experiments\candidate_aware_v1') --baseline-model (Join-Path $Here 'models\releases\performance_elo_v2_standard') --source july_large_gap --output $stack --weighting unweighted
if($LASTEXITCODE){throw 'Large-gap move stack failed'}
& $Python (Join-Path $Here 'test_centered_final_stack.py') --stack $stack --ratingnet $rn --output-dir (Join-Path $Here "models\experiments\centered_final_stack_gap_$MinimumGap")
if($LASTEXITCODE){throw 'Large-gap center test failed'}
