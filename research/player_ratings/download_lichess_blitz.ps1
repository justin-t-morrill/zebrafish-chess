$ErrorActionPreference = "Stop"
$vendor = Join-Path $PSScriptRoot "vendor_runtime"
$env:PYTHONPATH = $vendor
python (Join-Path $PSScriptRoot "download_lichess_blitz.py") @args
