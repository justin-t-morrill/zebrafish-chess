param(
    [ValidateRange(1, 10000)] [int]$Iterations = 50,
    [ValidateRange(2, 100000)] [int]$GamesPerIteration = 200,
    [string]$TimeControl = "0.1+0.01",
    [ValidateRange(1, 16)] [int]$Concurrency = 8,
    [ValidateSet("core", "all")] [string]$Group = "core",
    [ValidatePattern("^[A-Za-z0-9._-]+$")] [string]$BaseEngine = "2.2"
)

$ErrorActionPreference = "Stop"
if (($GamesPerIteration % 2) -ne 0) {
    throw "GamesPerIteration must be even for paired colors."
}
$root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$python = Join-Path $root "integrations\lichess-bot\.venv\bin\python.exe"
$script = Join-Path $PSScriptRoot "spsa_eval_tuner.py"
$state = Join-Path $PSScriptRoot "spsa_work\state_$BaseEngine-$Group.json"
if (-not (Test-Path -LiteralPath $python)) {
    throw "The lichess-bot Python environment is missing: $python"
}

& $python $script `
    --iterations $Iterations `
    --games $GamesPerIteration `
    --tc $TimeControl `
    --concurrency $Concurrency `
    --group $Group `
    --base-engine $BaseEngine `
    --state $state
if ($LASTEXITCODE -ne 0) {
    throw "SPSA tuning failed with exit code $LASTEXITCODE."
}
