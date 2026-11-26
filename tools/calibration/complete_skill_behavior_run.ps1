param(
    [Parameter(Mandatory=$true)][int]$ProcessId,
    [Parameter(Mandatory=$true)][string]$BehaviorDirectory
)
$ErrorActionPreference="Stop"
Wait-Process -Id $ProcessId -ErrorAction SilentlyContinue
$features=Join-Path $BehaviorDirectory "move_features_100k.csv"
$errors=Join-Path $BehaviorDirectory "behavior-extraction.err.log"
if((Test-Path $errors)-and(Get-Item $errors).Length){
    throw "Behavior extraction reported errors; see $errors"
}
$root=(Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$python=(Get-Command python).Source
&$python (Join-Path $PSScriptRoot "score_play_aspects.py") $features `
  --targets (Join-Path $PSScriptRoot "human_aspect_targets.json") `
  --output (Join-Path $BehaviorDirectory "overall_aspects.json")
if($LASTEXITCODE-ne 0){throw "Overall aspect scoring failed"}
&$python (Join-Path $PSScriptRoot "summarize_skill_behavior.py") $features `
  --targets (Join-Path $PSScriptRoot "human_aspect_targets.json") `
  --output (Join-Path $BehaviorDirectory "profile_aspects.json")
if($LASTEXITCODE-ne 0){throw "Profile aspect scoring failed"}
"complete"|Set-Content (Join-Path $BehaviorDirectory "behavior_pipeline.status.txt")
