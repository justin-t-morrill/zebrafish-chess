param(
    [string]$EngineA = "1.3_history",
    [string]$EngineB = "1.3",
    [ValidateRange(2, 100000)]
    [int]$Games = 1000,
    [string]$TimeControl = "1+0.1",
    [ValidateRange(1, 32)]
    [int]$Concurrency = 4,
    [ValidateRange(0, 16)]
    [int]$ThreadsA = 0,
    [ValidateRange(0, 16)]
    [int]$ThreadsB = 0,
    [string]$EvalFileA = "",
    [string]$EvalFileB = "",
    [string]$OpeningFile = "openings\suites\8mvs_+90_+99.epd"
)

$ErrorActionPreference = "Stop"
if (($Games % 2) -ne 0) { throw "Games must be even for color-swapped opening pairs." }
foreach ($name in @($EngineA, $EngineB)) {
    if ($name -notmatch '^[A-Za-z0-9._-]+$') { throw "Unsafe engine version name: $name" }
}

. (Join-Path $PSScriptRoot "project_paths.ps1")
$suite = $PSScriptRoot
$root = Get-ChessProjectRoot
$cute = (Get-ChildItem (Join-Path $suite "cutechess") -Recurse -Filter "cutechess-cli.exe" |
         Select-Object -First 1).FullName
function Resolve-TournamentEngine([string]$name) {
    return Get-EngineVersionPath $name
}
$engineAPath = Resolve-TournamentEngine $EngineA
$engineBPath = Resolve-TournamentEngine $EngineB
$openings = if ([System.IO.Path]::IsPathRooted($OpeningFile)) {
    $OpeningFile
} else {
    Join-Path $root $OpeningFile
}
$results = Get-TestResultDirectory "tournaments" $EngineA

foreach ($required in @($cute, $engineAPath, $engineBPath, $openings)) {
    if (-not $required -or -not (Test-Path -LiteralPath $required)) {
        throw "Required tournament file is missing: $required"
    }
}

$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$safeA = $EngineA.ToLowerInvariant()
$safeB = $EngineB.ToLowerInvariant()
$pgn = Join-Path $results "$safeA-vs-$safeB-$stamp.pgn"
$log = Join-Path $results "$safeA-vs-$safeB-$stamp.log"
$nameA = "Engine $EngineA"
$nameB = "Engine $EngineB"
if ($nameA -eq $nameB -and ($EvalFileA -or $EvalFileB)) {
    $labelA = if ($EvalFileA) { [System.IO.Path]::GetFileName((Split-Path -Parent $EvalFileA)) } else { "default" }
    $labelB = if ($EvalFileB) { [System.IO.Path]::GetFileName((Split-Path -Parent $EvalFileB)) } else { "default" }
    $nameA = "Engine $EngineA [$labelA]"
    $nameB = "Engine $EngineB [$labelB]"
}
$engineAOptions = @("option.Move Overhead=0")
$engineBOptions = @("option.Move Overhead=0")
if ($ThreadsA -gt 0) { $engineAOptions += "option.Threads=$ThreadsA" }
if ($ThreadsB -gt 0) { $engineBOptions += "option.Threads=$ThreadsB" }
if ($EvalFileA) {
    $resolvedEvalA = (Resolve-Path -LiteralPath $EvalFileA).Path
    $engineAOptions += "option.EvalFile=$resolvedEvalA"
}
if ($EvalFileB) {
    $resolvedEvalB = (Resolve-Path -LiteralPath $EvalFileB).Path
    $engineBOptions += "option.EvalFile=$resolvedEvalB"
}
$arguments = @(
    "-engine", "name=$nameA", "cmd=$engineAPath", "arg=--uci", "proto=uci",
        $engineAOptions,
    "-engine", "name=$nameB", "cmd=$engineBPath", "arg=--uci", "proto=uci",
        $engineBOptions,
    "-each", "tc=$TimeControl",
    "-openings", "file=$openings", "format=epd", "order=random", "policy=round",
    "-rounds", [string]($Games / 2), "-games", "2", "-repeat",
    "-concurrency", [string]$Concurrency, "-recover", "-ratinginterval", "50",
    "-pgnout", $pgn
)

Write-Host "Running $nameA vs ${nameB}: $Games games at $TimeControl, concurrency $Concurrency, threads A/B $ThreadsA/$ThreadsB"
$savedPreference = $ErrorActionPreference
$ErrorActionPreference = "Continue"
try {
    & $cute @arguments 2>&1 | Tee-Object -FilePath $log | Out-Host
    $cuteExitCode = $LASTEXITCODE
} finally {
    $ErrorActionPreference = $savedPreference
}
if ($cuteExitCode -ne 0) { throw "Cute Chess exited with code $cuteExitCode. See $log" }
python (Join-Path $suite "summarize_pgn.py") $pgn $nameA
