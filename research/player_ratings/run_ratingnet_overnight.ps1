param([switch]$SkipDownloads)
$ErrorActionPreference = "Stop"
$Here = $PSScriptRoot
$Data = Join-Path $Here "data\ratingnet_overnight"
$Runs = Join-Path $Here "models\experiments\ratingnet_overnight"
$Python = "C:\Users\Justin\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
New-Item -ItemType Directory -Force $Data,$Runs | Out-Null

if (-not $SkipDownloads) {
    foreach ($month in @("01","02","03","04","05")) {
        $pgn = Join-Path $Data "lichess_2026-$month.pgn"
        if (-not (Test-Path $pgn)) {
            & $Python (Join-Path $Here "download_lichess_blitz.py") `
                --url "https://database.lichess.org/standard/lichess_db_standard_rated_2026-$month.pgn.zst" `
                --output $pgn --target-games 40000 --max-games-per-player 10
            if ($LASTEXITCODE -ne 0) { throw "Download failed for 2026-$month" }
        }
    }
    $june = Join-Path $Data "lichess_2026-06.pgn"
    if (-not (Test-Path $june)) {
        & $Python (Join-Path $Here "download_lichess_blitz.py") `
            --url "https://database.lichess.org/standard/lichess_db_standard_rated_2026-06.pgn.zst" `
            --output $june --target-games 25000 --max-games-per-player 10
        if ($LASTEXITCODE -ne 0) { throw "Download failed for 2026-06" }
    }
}

$dataset = Join-Path $Data "ratingnet_250k.npz"
if (-not (Test-Path $dataset)) {
    $pgns = @("01","02","03","04","05","06") | ForEach-Object {
        Join-Path $Data "lichess_2026-$_.pgn"
    }
    $pgns += Join-Path $Here "data\lichess_blitz_balanced_2026-07.pgn"
    & $Python (Join-Path $Here "prepare_ratingnet_dataset.py") @pgns --output $dataset
    if ($LASTEXITCODE -ne 0) { throw "Compact dataset preparation failed" }
}

$linux = "/mnt/" + $Here.Substring(0,1).ToLower() + $Here.Substring(2).Replace('\','/')
$linuxData = "$linux/data/ratingnet_overnight/ratingnet_250k.npz"
$trainer = "$linux/train_ratingnet_compact.py"
$checkpoint = "$linux/external/RatingNet/published_models/model/model_55.pth"
$common = "--batch-size 128 --eval-batch-size 128 --train-through 2026.05 --validation-month 2026.06 --test-month 2026.07"

function Run-Model([string]$Name, [string]$Arguments) {
    $report = Join-Path $Runs "$Name\report.json"
    if (Test-Path $report) { Write-Host "Skipping completed $Name"; return }
    $out = "$linux/models/experiments/ratingnet_overnight/$Name"
    $command = "export HSA_ENABLE_DXG_DETECTION=1; /opt/ratingnet-venv/bin/python '$trainer' '$linuxData' --output-dir '$out' $common $Arguments"
    wsl -d Ubuntu-24.04 -- bash -lc $command
    if ($LASTEXITCODE -ne 0) { throw "Experiment failed: $Name" }
}

Run-Model "published" "--pretrained '$checkpoint' --original-inputs --evaluate-only"
Run-Model "finetuned_original" "--pretrained '$checkpoint' --original-inputs --epochs 60 --learning-rate 0.00003 --patience 10"
Run-Model "finetuned_adapted" "--pretrained '$checkpoint' --epochs 60 --learning-rate 0.00003 --patience 10"
Run-Model "scratch_adapted" "--epochs 100 --learning-rate 0.0003 --patience 12"

& $Python (Join-Path $Here "summarize_ratingnet_overnight.py")
if ($LASTEXITCODE -ne 0) { throw "Final comparison failed" }
Write-Host "Overnight RatingNet experiment complete: $Runs\COMPARISON.md"
