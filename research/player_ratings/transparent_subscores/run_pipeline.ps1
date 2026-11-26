param(
    [Parameter(Mandatory=$true)][string]$Moves,
    [string]$Candidates = "",
    [string]$RunName = "transparent_subscores_v1"
)
$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
$python = "C:\Users\Justin\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
if (-not (Test-Path -LiteralPath $python)) { $python = "python" }
$run = Join-Path $root ("runs\" + $RunName)
New-Item -ItemType Directory -Force -Path $run | Out-Null
$features = Join-Path $run "subscore_features.csv"
$audit = Join-Path $run "move_classification_audit.csv"
$model = Join-Path $run "model.json"
$report = Join-Path $run "test_report.json"
$predictions = Join-Path $run "test_predictions.csv"
$build = @((Join-Path $root "build_subscore_features.py"), "--moves", $Moves,
           "--output", $features, "--move-audit", $audit)
if ($Candidates) { $build += @("--candidates", $Candidates) }
& $python @build
if ($LASTEXITCODE -ne 0) { throw "Subscore feature extraction failed." }
& $python (Join-Path $root "train_subscore_model.py") --features $features --output $model
if ($LASTEXITCODE -ne 0) { throw "Subscore training failed." }
& $python (Join-Path $root "validate_subscore_model.py") --features $features --model $model `
    --split test --output $report --predictions $predictions
if ($LASTEXITCODE -ne 0) { throw "Subscore validation failed." }
Write-Host "Transparent subscore experiment complete: $run"
