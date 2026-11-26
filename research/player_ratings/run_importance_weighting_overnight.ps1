param(
    [int]$Threads = 6,
    [int]$Bootstrap = 20000
)
$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
$data = Join-Path $root "data"
$output = Join-Path $root "models\experiments\importance_weighting_overnight"
$python = "C:\Users\Justin\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
$candidate = Join-Path $root "models\experiments\candidate_aware_v1"
$baseline = Join-Path $root "models\releases\performance_elo_v2_standard"
$schemes = @("unweighted", "criticality", "informativeness", "consequence", "combined", "combined_capped")
$sets = @(
    @{ Name="may"; Source="may_full_paired"; Moves="move_features_paired_2026-05_full_100k.csv"; Features="player_game_features_paired_2026-05_full_100k.csv" },
    @{ Name="june"; Source="june_full_test"; Moves="move_features_fresh_2026-06_full_100k.csv"; Features="player_game_features_fresh_2026-06_full_100k.csv" },
    @{ Name="july"; Source="july_sparse_test"; Moves="move_features_detailed_5000_100k.csv"; Features="player_game_features_5000_clock_v2.csv" },
    @{ Name="april"; Source="april_frozen_holdout"; Moves="move_features_stacker_holdout_2026-04_full_100k.csv"; Features="player_game_features_stacker_holdout_2026-04_full_100k.csv" }
)
New-Item -ItemType Directory -Force -Path $output | Out-Null
$log = Join-Path $output "progress.log"
"Started $(Get-Date -Format o)" | Set-Content $log

foreach ($scheme in $schemes) {
    Add-Content $log "[$(Get-Date -Format T)] Building $scheme"
    $schemeRoot = Join-Path $output $scheme
    New-Item -ItemType Directory -Force -Path $schemeRoot | Out-Null
    foreach ($set in $sets) {
        & $python (Join-Path $root "build_stacking_features.py") `
            --moves (Join-Path $data $set.Moves) `
            --game-features (Join-Path $data $set.Features) `
            --experiment $candidate --baseline-model $baseline `
            --source $set.Source --output (Join-Path $schemeRoot ($set.Name + ".csv")) `
            --weighting $scheme
        if ($LASTEXITCODE -ne 0) { throw "Feature build failed for $scheme/$($set.Name)" }
    }
    $stage = Join-Path $schemeRoot "stage1"
    & $python (Join-Path $root "train_elo_stacker.py") `
        --inputs (Join-Path $schemeRoot "may.csv") `
        --output-dir $stage --threads $Threads
    if ($LASTEXITCODE -ne 0) { throw "Stage-one stacker failed for $scheme" }
    $validations = @(
        @{ Name="may_test"; File="may.csv"; Split="test" },
        @{ Name="june"; File="june.csv"; Split="all" },
        @{ Name="july"; File="july.csv"; Split="all" },
        @{ Name="april_validation"; File="april.csv"; Split="validation" }
    )
    foreach ($validation in $validations) {
        & $python (Join-Path $root "validate_elo_stacker.py") `
            --features (Join-Path $schemeRoot $validation.File) --model-dir $stage `
            --output (Join-Path $stage ($validation.Name + ".json")) `
            --bootstrap $Bootstrap --split $validation.Split
        if ($LASTEXITCODE -ne 0) { throw "Validation failed for $scheme/$($validation.Name)" }
    }
    Add-Content $log "[$(Get-Date -Format T)] Completed $scheme"
}

& $python (Join-Path $root "summarize_importance_experiment.py") $output
if ($LASTEXITCODE -ne 0) { throw "Experiment summary failed" }
$summary = Get-Content (Join-Path $output "summary.json") | ConvertFrom-Json
$winner = $summary.winner
Add-Content $log "[$(Get-Date -Format T)] Selected $winner"

if ($winner -ne "unweighted") {
    $winnerRoot = Join-Path $output $winner
    $final = Join-Path $winnerRoot "final"
    & $python (Join-Path $root "train_elo_stacker.py") `
        --inputs (Join-Path $winnerRoot "may.csv") (Join-Path $winnerRoot "june.csv") (Join-Path $winnerRoot "july.csv") `
        --output-dir $final --threads $Threads
    if ($LASTEXITCODE -ne 0) { throw "Final stacker failed for $winner" }
    & $python (Join-Path $root "validate_elo_stacker.py") `
        --features (Join-Path $winnerRoot "april.csv") --model-dir $final `
        --output (Join-Path $final "april_test.json") --bootstrap $Bootstrap --split test
    if ($LASTEXITCODE -ne 0) { throw "Final untouched test failed for $winner" }
}
Add-Content $log "Finished $(Get-Date -Format o)"
Write-Host "Overnight experiment complete: $output"
