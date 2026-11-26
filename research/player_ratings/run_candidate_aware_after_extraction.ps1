param(
    [int]$ExpectedPositions = 93246,
    [int]$Threads = 6,
    [switch]$Wait
)
$ErrorActionPreference = "Stop"
$root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$data = Join-Path $PSScriptRoot "data"
$checkpoint = Join-Path $data "choice_candidate_features_new_100k.completed.txt"
$python = "C:\Users\Justin\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"

do {
    $completed = if (Test-Path $checkpoint) {
        (Get-Content $checkpoint | Measure-Object -Line).Lines
    } else { 0 }
    if ($completed -ge $ExpectedPositions) { break }
    if (-not $Wait) {
        throw "Candidate extraction is incomplete: $completed / $ExpectedPositions. Rerun with -Wait to queue training."
    }
    Write-Host ("Waiting for extraction: {0:N0} / {1:N0} ({2:N1}%)" -f `
        $completed, $ExpectedPositions, (100 * $completed / $ExpectedPositions))
    Start-Sleep -Seconds 30
} while ($true)

$experiment = Join-Path $PSScriptRoot "models\experiments\candidate_aware_v1"
& $python (Join-Path $PSScriptRoot "train_candidate_aware_distribution.py") `
    --moves `
        (Join-Path $data "move_features_100k.csv") `
        (Join-Path $data "move_features_fresh_2026-06_full_100k.csv") `
    --final-test-moves (Join-Path $data "move_features_fresh_2026-06_full_100k.csv") `
    --candidates `
        (Join-Path $data "candidate_features_errors_100k.csv") `
        (Join-Path $data "choice_candidate_features_new_100k.csv") `
    --game-features `
        (Join-Path $data "player_game_features_30000_clock_v2.csv") `
        (Join-Path $data "player_game_features_fresh_2026-06_full_100k.csv") `
    --baseline-model (Join-Path $PSScriptRoot "models\releases\performance_elo_v2_standard") `
    --output-dir $experiment --threads $Threads
if ($LASTEXITCODE -ne 0) { throw "Candidate-aware training failed." }

& $python (Join-Path $PSScriptRoot "compare_move_distribution.py") `
    (Join-Path $experiment "test_predictions.csv") `
    --output (Join-Path $experiment "promotion_report.json") --bootstrap 20000
if ($LASTEXITCODE -ne 0) { throw "Candidate-aware promotion report failed." }

Write-Host "Candidate-aware pipeline complete: $experiment"
