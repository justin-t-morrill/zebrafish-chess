$ErrorActionPreference = "Stop"
$reviewVendor = Join-Path $PSScriptRoot "..\game_review\vendor_runtime"
$env:PYTHONPATH = $reviewVendor
python (Join-Path $PSScriptRoot "extract_candidate_features.py") @args
