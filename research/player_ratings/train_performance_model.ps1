$ErrorActionPreference = "Stop"
$root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$features = Join-Path $PSScriptRoot "data\player_game_features_5000.csv"
$output = Join-Path $PSScriptRoot "models\game_performance_v1"
$bundledPython = "C:\Users\Justin\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
$python = if (Test-Path -LiteralPath $bundledPython) { $bundledPython } else { "python" }

if (-not (Test-Path -LiteralPath $features)) {
    throw "Player-game features are not ready yet: $features"
}

& $python (Join-Path $PSScriptRoot "train_performance_model.py") $features `
    --output-dir $output --threads 6
if ($LASTEXITCODE -ne 0) { throw "Performance-model training failed." }
