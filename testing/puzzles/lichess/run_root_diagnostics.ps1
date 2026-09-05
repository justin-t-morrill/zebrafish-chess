param(
    [Parameter(Mandatory = $true)]
    [string]$Results,
    [string]$Engine = "6.2",
    [int[]]$Depths = @(6, 8, 10, 12),
    [switch]$OnlyFailed,
    [int]$MaximumPositions = 0,
    [int]$StockfishDepth = 22
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
if ($Engine -notmatch '^[A-Za-z0-9._-]+$') { throw "Unsafe engine version name." }
$sourceDirectory = Join-Path $root "engine_versions\source_$Engine"
if (-not (Test-Path -LiteralPath (Join-Path $sourceDirectory "chess.c"))) {
    throw "Saved source for Engine $Engine was not found."
}
$resultsPath = (Resolve-Path -LiteralPath $Results).Path
$diagnosticDirectory = Join-Path $PSScriptRoot "diagnostics"
New-Item -ItemType Directory -Force -Path $diagnosticDirectory | Out-Null
$header = Join-Path $diagnosticDirectory "diagnostic_engine_source.h"
$relativeSource = '../engine_versions/source_' + $Engine + '/chess.c'
Set-Content -LiteralPath $header -Encoding ascii `
    -Value ('#define DIAGNOSTIC_ENGINE_SOURCE "' + $relativeSource + '"')
$probe = Join-Path $diagnosticDirectory "root_move_probe_$Engine.exe"
$gcc = (Get-Command gcc.exe -ErrorAction Stop).Source
& $gcc -std=c11 -O3 -DNDEBUG -include $header -Wall -Wextra -pedantic `
    (Join-Path $PSScriptRoot "root_move_probe.c") -o $probe `
    -lgdiplus -lgdi32 -luser32
if ($LASTEXITCODE -ne 0) { throw "Root diagnostic probe compilation failed." }

$stockfish = (Get-ChildItem (Join-Path $root "reference_engines\stockfish") `
    -Recurse -File -Filter "stockfish-windows-x86-64.exe" | Select-Object -First 1).FullName
$arguments = @(
    (Join-Path $PSScriptRoot "analyze_root_moves.py"), $resultsPath,
    "--engine", $Engine, "--probe", $probe,
    "--depths"
) + ($Depths | ForEach-Object { [string]$_ }) + @(
    "--stockfish", $stockfish, "--stockfish-depth", [string]$StockfishDepth,
    "--maximum-positions", [string]$MaximumPositions
)
if ($OnlyFailed) { $arguments += "--only-failed" }
python -u @arguments
if ($LASTEXITCODE -ne 0) { throw "Root diagnostics failed." }
