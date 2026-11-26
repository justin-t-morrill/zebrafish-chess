$ErrorActionPreference = "Stop"
$Here = $PSScriptRoot
$linux = "/mnt/" + $Here.Substring(0,1).ToLower() + $Here.Substring(2).Replace('\','/')
$command = @"
export HSA_ENABLE_DXG_DETECTION=1
/opt/ratingnet-venv/bin/python '$linux/evaluate_ratingnet_candidates.py' \
  --data-dir '$linux/data/ratingnet_evaluation' \
  --model-dir '$linux/models/experiments/ratingnet_overnight' \
  --published '$linux/external/RatingNet/published_models/model/model_55.pth' \
  --output-dir '$linux/validation/ratingnet_calibrated' \
  --batch-size 128
"@
wsl -d Ubuntu-24.04 -- bash -lc $command
if ($LASTEXITCODE -ne 0) { throw "Calibrated RatingNet evaluation failed." }
Write-Host "Report: $Here\validation\ratingnet_calibrated\REPORT.md"
