$ErrorActionPreference = "Stop"
$vendor = Join-Path $PSScriptRoot "vendor_runtime"
python -m pip install --target $vendor "zstandard==0.23.0"
Write-Host "Elo-estimator download dependency installed in $vendor"
