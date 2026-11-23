# Manual desktop run. Preview prints the exact tournament arguments without
# compiling either engine or starting a match.
param(
    [ValidateRange(1, 32)][int]$Concurrency = 8,
    [switch]$Preview
)
$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "project_paths.ps1")
$root = Get-ChessProjectRoot
$candidate = Join-Path $root "engine/current"
$frozen = Join-Path $root "engines/versions/v8"
$network = Join-Path $candidate "nnue-8.3.bin"
if (-not $Preview) {
    & (Join-Path $frozen "source_8.3/build.ps1")
    & (Join-Path $candidate "build.ps1") -AdaptiveTime
}
& (Join-Path $PSScriptRoot "run_version_sprt.ps1") `
    -EngineA "8.3-adaptive" -BinaryA (Join-Path $candidate "chess-adaptive.exe") `
    -EngineB "8.3" -BinaryB (Join-Path $frozen "8.3.exe") `
    -EvalFileA $network -EvalFileB $network -ThreadsA 1 -ThreadsB 1 -SearchOnly `
    -TimeControl "1+0.1" -Concurrency $Concurrency -MaxGames 10000 `
    -Elo0 0 -Elo1 10 -Alpha 0.05 -Beta 0.05 -Preview:$Preview
