param(
    [Parameter(Mandatory = $true)]
    [string[]]$Engine,
    [string]$Suite = "data\lichess_themed_30k.csv",
    [ValidateRange(1, 3600000)]
    [int]$MoveTime = 100,
    [ValidateRange(0, 10000000)]
    [int]$MaximumPuzzles = 0
)

$ErrorActionPreference = "Stop"
$suitePath = if ([System.IO.Path]::IsPathRooted($Suite)) {
    $Suite
} else {
    Join-Path $PSScriptRoot $Suite
}
$arguments = @((Join-Path $PSScriptRoot "run_puzzles.py"), $suitePath)
foreach ($name in $Engine) { $arguments += @("--engine", $name) }
$arguments += @("--movetime", [string]$MoveTime,
                "--maximum-puzzles", [string]$MaximumPuzzles)
python @arguments
if ($LASTEXITCODE -ne 0) { throw "Puzzle test failed." }
