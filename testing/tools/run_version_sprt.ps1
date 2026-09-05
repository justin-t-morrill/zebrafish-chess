param(
    [Parameter(Mandatory = $true)]
    [string]$EngineA,
    [Parameter(Mandatory = $true)]
    [string]$EngineB,
    [ValidateRange(2, 100000)]
    [int]$MaxGames = 10000,
    [string]$TimeControl = "1+0.1",
    [ValidateRange(1, 32)]
    [int]$Concurrency = 6,
    [ValidateRange(0, 16)]
    [int]$ThreadsA = 0,
    [ValidateRange(0, 16)]
    [int]$ThreadsB = 0,
    [string]$EvalFileA = "",
    [string]$EvalFileB = "",
    [double]$Elo0 = 0.0,
    [double]$Elo1 = 10.0,
    [ValidateRange(0.0001, 0.4999)]
    [double]$Alpha = 0.05,
    [ValidateRange(0.0001, 0.4999)]
    [double]$Beta = 0.05,
    [string]$OpeningFile = "openings\suites\8mvs_+90_+99.epd"
)

$ErrorActionPreference = "Stop"
if (($MaxGames % 2) -ne 0) {
    throw "MaxGames must be even so every opening is played with colors swapped."
}
if ($Elo1 -le $Elo0) { throw "Elo1 must be greater than Elo0." }
foreach ($name in @($EngineA, $EngineB)) {
    if ($name -notmatch '^[A-Za-z0-9._-]+$') {
        throw "Unsafe engine version name: $name"
    }
}

. (Join-Path $PSScriptRoot "project_paths.ps1")
$suite = $PSScriptRoot
$root = Get-ChessProjectRoot
$cute = (Get-ChildItem (Join-Path $suite "cutechess") -Recurse `
         -Filter "cutechess-cli.exe" | Select-Object -First 1).FullName
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
$results = Get-TestResultDirectory "sprt" $EngineA
foreach ($required in @($cute, $engineAPath, $engineBPath, $openings)) {
    if (-not $required -or -not (Test-Path -LiteralPath $required)) {
        throw "Required SPRT file is missing: $required"
    }
}

$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$safeA = $EngineA.ToLowerInvariant()
$safeB = $EngineB.ToLowerInvariant()
$prefix = "$safeA-vs-$safeB-sprt-$stamp"
$pgn = Join-Path $results "$prefix.pgn"
$log = Join-Path $results "$prefix.log"
$nameA = "Engine $EngineA"
$nameB = "Engine $EngineB"
if ($nameA -eq $nameB -and ($EvalFileA -or $EvalFileB)) {
    $labelA = if ($EvalFileA) { [System.IO.Path]::GetFileName((Split-Path -Parent $EvalFileA)) } else { "default" }
    $labelB = if ($EvalFileB) { [System.IO.Path]::GetFileName((Split-Path -Parent $EvalFileB)) } else { "default" }
    $nameA = "Engine $EngineA [$labelA]"
    $nameB = "Engine $EngineB [$labelB]"
}
$sprt = "elo0=$Elo0", "elo1=$Elo1", "alpha=$Alpha", "beta=$Beta"
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
    "-rounds", [string]($MaxGames / 2), "-games", "2", "-repeat",
    "-sprt", $sprt[0], $sprt[1], $sprt[2], $sprt[3],
    "-concurrency", [string]$Concurrency, "-recover",
    "-ratinginterval", "50", "-pgnout", $pgn
)

Write-Host "SPRT: $nameA vs $nameB at $TimeControl, concurrency $Concurrency, threads A/B $ThreadsA/$ThreadsB"
Write-Host "H0 <= $Elo0 Elo; H1 >= $Elo1 Elo; alpha=$Alpha beta=$Beta; maximum $MaxGames games"
Write-Host "PGN: $pgn"
Write-Host "Log: $log"
$savedPreference = $ErrorActionPreference
$ErrorActionPreference = "Continue"
try {
    & $cute @arguments 2>&1 | Tee-Object -FilePath $log | Out-Host
    $cuteExitCode = $LASTEXITCODE
} finally {
    $ErrorActionPreference = $savedPreference
}
if ($cuteExitCode -ne 0) {
    throw "Cute Chess exited with code $cuteExitCode. See $log"
}

# Report conventional W/D/L, confidence intervals, and Elo for however many
# games SPRT needed before accepting a hypothesis (or reaching MaxGames).
python (Join-Path $suite "summarize_pgn.py") $pgn $nameA
