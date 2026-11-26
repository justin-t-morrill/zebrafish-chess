param(
    [string]$RunName = "ratingnet_33k",
    [int]$MaxGames = 0,
    [int]$Epochs = 30,
    [int]$BatchSize = 64
)
$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$LinuxRoot = "/mnt/" + $Root.Substring(0,1).ToLower() + $Root.Substring(2).Replace('\','/')
$Command = "export HSA_ENABLE_DXG_DETECTION=1; /opt/ratingnet-venv/bin/python " +
    "'$LinuxRoot/analysis/elo_estimator/train_ratingnet_compact.py' " +
    "'$LinuxRoot/analysis/elo_estimator/data/ratingnet_raw_multimonth.npz' " +
    "--output-dir '$LinuxRoot/analysis/elo_estimator/models/experiments/$RunName' " +
    "--epochs $Epochs --batch-size $BatchSize --max-games $MaxGames"
wsl -d Ubuntu-24.04 -- bash -lc $Command
if ($LASTEXITCODE -ne 0) { throw "RatingNet WSL training failed." }
