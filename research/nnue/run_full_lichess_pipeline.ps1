param(
    [int]$ControlledCopies = 14
)

$ErrorActionPreference = "Continue"
$nnue = $PSScriptRoot
$root = Split-Path -Parent (Split-Path -Parent $nnue)
$data = Join-Path $nnue "data\lichess-evals"
$archive = Join-Path $data "lichess_db_eval.jsonl.zst"
$textData = Join-Path $data "lichess-full-filtered.txt"
$lichessData = Join-Path $data "lichess-full-filtered.data"
$mixedData = Join-Path $data "mixed-full-unshuffled.data"
$shuffledData = Join-Path $data "mixed-full-shuffled.data"
$controlled = Join-Path $nnue "data\stockfish-8hour\prepared\train-shuffled.data"
$controlledTest = Join-Path $nnue "data\stockfish-8hour\prepared\test.txt"
$lichessTest = Join-Path $data "lichess-holdout-250k.txt"
$validation = Join-Path $nnue "data\stockfish-8hour\prepared\validation.data"
$bulletUtils = "C:\Users\Justin\.cargo\git\checkouts\bullet-8a69ed9a26c6f599\629ee50\target\release\bullet-utils.exe"
$cargo = "C:\Users\Justin\.cargo\bin\cargo.exe"
$validator = Join-Path $nnue "validate_network_lichess.exe"
$log = Join-Path $data "full-pipeline.log"
$stage = Join-Path $data "full-pipeline.stage.txt"

function Set-Stage([string]$message) {
    Set-Content -LiteralPath $stage -Value $message
    Write-Host "[$(Get-Date -Format s)] $message" | Tee-Object -FilePath $log -Append
}
function Require-Success([string]$description) {
    if ($LASTEXITCODE -ne 0) { throw "$description failed with exit code $LASTEXITCODE" }
}

foreach ($required in @($archive, $controlled, $controlledTest, $lichessTest,
                         $validation, $bulletUtils, $cargo, $validator)) {
    if (-not (Test-Path -LiteralPath $required)) { throw "Missing required file: $required" }
}
foreach ($output in @($textData, $lichessData, $mixedData, $shuffledData)) {
    if (Test-Path -LiteralPath $output) { throw "Refusing to overwrite existing pipeline output: $output" }
}

Set-Stage "1/8 Filtering the complete Lichess archive (reserved hash range 0.07-0.08 excluded)"
python (Join-Path $nnue "convert_lichess_evals.py") $archive $textData `
    --target 1000000000 --sample-min 0.0 --sample-rate 1.0 `
    --exclude-min 0.07 --exclude-max 0.08 --min-knodes 10000 2>&1 |
    Tee-Object -FilePath $log -Append
Require-Success "Lichess filtering"

Set-Stage "2/8 Converting and validating the filtered Lichess data"
& $bulletUtils convert --from text --input $textData --output $lichessData --threads 2 2>&1 |
    Tee-Object -FilePath $log -Append
Require-Success "Bullet conversion"
& $bulletUtils validate --input $lichessData 2>&1 | Tee-Object -FilePath $log -Append
Require-Success "Filtered-data validation"
Remove-Item -LiteralPath $textData -Force

Set-Stage "3/8 Mixing controlled data at approximately 17 percent"
$inputs = @($lichessData)
for ($copy = 0; $copy -lt $ControlledCopies; ++$copy) { $inputs += $controlled }
& $bulletUtils interleave @inputs --output $mixedData 2>&1 | Tee-Object -FilePath $log -Append
Require-Success "Dataset mixing"

Set-Stage "4/8 Globally shuffling and validating the training mixture"
& $bulletUtils shuffle --input $mixedData --output $shuffledData --mem-used-mb 2048 2>&1 |
    Tee-Object -FilePath $log -Append
Require-Success "Dataset shuffle"
& $bulletUtils validate --input $shuffledData 2>&1 | Tee-Object -FilePath $log -Append
Require-Success "Mixed-data validation"
Remove-Item -LiteralPath $mixedData -Force

$positions = [int64](Get-Item -LiteralPath $shuffledData).Length / 32
$batches5 = [math]::Ceiling((5.0 * $positions) / (40.0 * 16384.0))
$batches10 = [math]::Ceiling((10.0 * $positions) / (40.0 * 16384.0))
$env:HIP_PATH = "C:\Program Files\AMD\ROCm\7.2"
$env:PATH = "$env:HIP_PATH\bin;C:\Users\Justin\.cargo\bin;$env:PATH"

Set-Location $nnue
Set-Stage "5/8 Training plain 128 and 256 networks for five passes"
& $cargo run --release -- $shuffledData $validation $batches5 0.0 128 lichessfull5ep plain 2>&1 |
    Tee-Object -FilePath $log -Append
Require-Success "Plain-128 training"
& $cargo run --release -- $shuffledData $validation $batches5 0.0 256 lichessfull5ep plain 2>&1 |
    Tee-Object -FilePath $log -Append
Require-Success "Plain-256 training"

Set-Stage "6/8 Training king-bucket 128 and 256 networks for ten passes"
& $cargo run --release -- $shuffledData $validation $batches10 0.0 128 lichessfull10ep king10 2>&1 |
    Tee-Object -FilePath $log -Append
Require-Success "King-128 training"
& $cargo run --release -- $shuffledData $validation $batches10 0.0 256 lichessfull10ep king10 2>&1 |
    Tee-Object -FilePath $log -Append
Require-Success "King-256 training"

$networks = [ordered]@{
    "full128" = Join-Path $nnue "checkpoints\minimal-chess-768x128-lichessfull5ep-wdl000-40\quantised.bin"
    "full256" = Join-Path $nnue "checkpoints\minimal-chess-768x256-lichessfull5ep-wdl000-40\quantised.bin"
    "full-king128" = Join-Path $nnue "checkpoints\minimal-chess-king10x128-lichessfull10ep-wdl000-40\quantised.bin"
    "full-king256" = Join-Path $nnue "checkpoints\minimal-chess-king10x256-lichessfull10ep-wdl000-40\quantised.bin"
}
Set-Stage "7/8 Running controlled/Lichess holdout analysis and search benchmarks"
foreach ($entry in $networks.GetEnumerator()) {
    Write-Host "NETWORK $($entry.Key) CONTROLLED" | Tee-Object -FilePath $log -Append
    & $validator $entry.Value $controlledTest 300000 2>&1 | Tee-Object -FilePath $log -Append
    Require-Success "$($entry.Key) controlled validation"
    Write-Host "NETWORK $($entry.Key) LICHESS" | Tee-Object -FilePath $log -Append
    & $validator $entry.Value $lichessTest 300000 2>&1 | Tee-Object -FilePath $log -Append
    Require-Success "$($entry.Key) Lichess validation"
}
& (Join-Path $nnue "benchmark_sizes.ps1") -Depths 10,12 -Trials 3 `
    -NetworkNames @($networks.Keys) 2>&1 | Tee-Object -FilePath $log -Append

Set-Stage "8/8 SPRT: full-data plain-128 versus Engine 8.2"
& (Join-Path $root "testing\tools\run_version_sprt.ps1") `
    -EngineA 8.2 -EngineB 8.2 `
    -EvalFileA $networks["full128"] `
    -EvalFileB (Join-Path $root "engines\versions\v8\nnue-8.2.bin") `
    -MaxGames 10000 -TimeControl "1+0.1" -Concurrency 6 `
    -ThreadsA 1 -ThreadsB 1 -Elo0 0 -Elo1 10 2>&1 |
    Tee-Object -FilePath $log -Append
Require-Success "Full-data SPRT"
Set-Stage "COMPLETE"
