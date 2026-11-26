param([int]$Workers=6,[int]$MoveTimeMs=100,[int]$ReferenceNodes=100000)
$ErrorActionPreference="Stop";$root=(Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path;$run=Join-Path $root "testing\results\strength_calibration\fixed-skill-$(Get-Date -Format 'yyyyMMdd-HHmmss')";New-Item -ItemType Directory -Force $run|Out-Null
$python=(Get-Command python).Source;$source=Join-Path $root "analysis\elo_estimator\data\move_features_detailed_5000_100k.csv"
&$python (Join-Path $PSScriptRoot "build_fixed_skill_suites.py") $source --output (Join-Path $run "suites") --per-skill 1200;if($LASTEXITCODE){throw "suite build failed"}
&$python (Join-Path $PSScriptRoot "sample_fixed_skill_moves.py") (Join-Path $run "suites") --output (Join-Path $run "choice_parts") --engine (Join-Path $root "build\current\chess.exe") --adapter (Join-Path $PSScriptRoot "limited_strength_uci.py") --workers $Workers --movetime-ms $MoveTimeMs;if($LASTEXITCODE){throw "move sampling failed"}
&$python (Join-Path $PSScriptRoot "score_fixed_skill_moves.py") (Join-Path $run "choice_parts.csv") --engine (Join-Path $root "build\current\chess.exe") --output (Join-Path $run "scored_moves.csv") --nodes $ReferenceNodes --workers $Workers;if($LASTEXITCODE){throw "reference scoring failed"}
&$python (Join-Path $PSScriptRoot "fit_fixed_skill_model.py") (Join-Path $run "scored_moves.csv") --output (Join-Path $run "fit.json") *> (Join-Path $run "fit.log");if($LASTEXITCODE){throw "model fitting failed"}
"complete"|Set-Content (Join-Path $run "status.txt");Write-Output "Complete: $run"
