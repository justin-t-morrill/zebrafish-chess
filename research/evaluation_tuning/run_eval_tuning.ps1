param(
    [string]$Tag = "custom",
    [string]$PgnDirectory = ".\local\results",
    [string[]]$Include = @("*.pgn"),
    [int]$Positions = 50000,
    [int]$PositionsPerGame = 8,
    [int]$Workers = 8,
    [int]$ShallowNodes = 5000,
    [int]$DeepNodes = 20000,
    [int]$StabilityCp = 80,
    [string[]]$CalibrationSourcePrefix = @()
)

$ErrorActionPreference = "Stop"
$root = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..'))
$python = Join-Path $root "third_party\lichess-bot\.venv\bin\python.exe"
$data = Join-Path $PSScriptRoot "data"
$selector = Join-Path $PSScriptRoot "select_positions.py"
$labeler = Join-Path $PSScriptRoot "label_positions.py"
$extractorSource = Join-Path $PSScriptRoot "extract_eval_features.c"
$extractor = Join-Path $PSScriptRoot "extract_eval_features.exe"
$fitter = Join-Path $PSScriptRoot "fit_eval.py"

if (-not (Test-Path -LiteralPath $python)) { throw "Python environment not found: $python" }
$stockfish = Get-ChildItem (Join-Path $root "reference_engines\stockfish") -Recurse -File `
    -Filter "stockfish-windows-x86-64.exe" | Select-Object -First 1
if (-not $stockfish) { throw "Stockfish executable was not found." }
$gcc = (Get-Command gcc.exe -ErrorAction Stop).Source
New-Item -ItemType Directory -Force -Path $data | Out-Null

$positionsCsv = Join-Path $data "positions_$Tag.csv"
$allLabelsCsv = Join-Path $data "labels_${Tag}_all.csv"
$quietLabelsCsv = Join-Path $data "labels_${Tag}_quiet.csv"
$featuresCsv = Join-Path $data "features_${Tag}_quiet.csv"
$fitOutput = Join-Path $data "pawn_fit_$Tag.txt"

$selectArguments = @(
    $selector, $PgnDirectory, $positionsCsv,
    "--positions", $Positions,
    "--positions-per-game", $PositionsPerGame,
    "--sample-every", 4
)
foreach ($pattern in $Include) { $selectArguments += @("--include", $pattern) }
& $python @selectArguments
if ($LASTEXITCODE -ne 0) { throw "Position selection failed." }

& $python $labeler $positionsCsv $allLabelsCsv `
    --quiet-output $quietLabelsCsv --stockfish $stockfish.FullName `
    --workers $Workers --shallow-nodes $ShallowNodes --deep-nodes $DeepNodes `
    --stability-cp $StabilityCp
if ($LASTEXITCODE -ne 0) { throw "Stockfish labeling failed." }

& $gcc -std=c11 -O2 -Wall -Wextra -pedantic $extractorSource -o $extractor `
    -lgdiplus -lgdi32 -luser32
if ($LASTEXITCODE -ne 0) { throw "Feature extractor compilation failed." }
& $extractor $quietLabelsCsv $featuresCsv
if ($LASTEXITCODE -ne 0) { throw "Feature extraction failed." }

$fitArguments = @($fitter, $quietLabelsCsv, $featuresCsv, $fitOutput)
foreach ($prefix in $CalibrationSourcePrefix) {
    $fitArguments += @("--calibration-source-prefix", $prefix)
}
& $python @fitArguments
if ($LASTEXITCODE -ne 0) { throw "Parameter fitting failed." }

Write-Host "Finished. Proposed weights and metrics: $fitOutput"
