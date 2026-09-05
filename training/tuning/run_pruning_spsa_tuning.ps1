param(
    [ValidatePattern("^[A-Za-z0-9._-]+$")] [string]$BaseEngine = "7.2",
    [ValidatePattern("^[A-Za-z0-9._-]+$")] [string]$RunName = "7.2_pruning",
    [ValidateRange(1, 10000)] [int]$Iterations = 60,
    [ValidateRange(2, 100000)] [int]$GamesPerIteration = 240,
    [string]$TimeControl = "0.2+0.02",
    [ValidateRange(1, 16)] [int]$Concurrency = 6,
    [switch]$PrepareOnly
)

$ErrorActionPreference = "Stop"
if (($GamesPerIteration % 2) -ne 0) {
    throw "GamesPerIteration must be even for paired colors."
}
$root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$python = Join-Path $root "integrations\lichess-bot\.venv\bin\python.exe"
$script = Join-Path $PSScriptRoot "spsa_pruning_tuner.py"
if (-not (Test-Path -LiteralPath $python)) {
    throw "The lichess-bot Python environment is missing: $python"
}
$arguments = @(
    $script,
    "--base-engine", $BaseEngine,
    "--run-name", $RunName,
    "--iterations", $Iterations,
    "--games", $GamesPerIteration,
    "--tc", $TimeControl,
    "--concurrency", $Concurrency
)
if ($PrepareOnly) { $arguments += "--prepare-only" }
& $python @arguments
if ($LASTEXITCODE -ne 0) {
    throw "Pruning SPSA tuning failed with exit code $LASTEXITCODE."
}
