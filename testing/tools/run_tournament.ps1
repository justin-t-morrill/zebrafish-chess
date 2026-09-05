param(
    [ValidateSet("Blunder", "Carballo", "Stockfish1320", "Stockfish1600",
                 "Stockfish1750", "Stockfish1800", "Stockfish1850",
                 "Stockfish2000", "Stockfish2100", "Stockfish2200",
                 "Stockfish2300", "Stockfish2400", "Stockfish2500",
                 "Stockfish2600", "Stockfish2700", "Stockfish2800",
                 "Stockfish2900", "Stockfish3000", "Stockfish3100",
                 "StockfishFull", "Gauntlet")]
    [string]$Opponent = "Stockfish1320",
    [ValidateRange(2, 100000)]
    [int]$Games = 100,
    [string]$TimeControl = "10+0.1",
    [ValidateRange(1, 32)]
    [int]$Concurrency = 6,
    [ValidateRange(0, 16)]
    [int]$EngineThreads = 0,
    [ValidateRange(0, 16)]
    [int]$OpponentThreads = 1,
    [string]$EngineVersion = "1.7.1",
    [string]$EvalFile = "",
    [string]$OpeningFile = "openings\suites\8moves_v3.epd",
    [string[]]$GauntletOpponents = @()
)

$ErrorActionPreference = "Stop"
if (($Games % 2) -ne 0) { throw "Games must be even so every opening is color-swapped." }
if ($EngineVersion -notmatch '^[A-Za-z0-9._-]+$') {
    throw "Unsafe engine version name: $EngineVersion"
}
$validGauntletOpponents = @(
    "Stockfish1320", "Stockfish1600", "Stockfish1750", "Stockfish1800",
    "Stockfish1850", "Stockfish2000", "Stockfish2100", "Stockfish2200",
    "Stockfish2300", "Stockfish2400", "Stockfish2500", "Stockfish2600",
    "Stockfish2700", "Stockfish2800", "Stockfish2900", "Stockfish3000",
    "Stockfish3100", "StockfishFull",
    "Blunder", "Carballo"
)
foreach ($name in $GauntletOpponents) {
    if ($name -notin $validGauntletOpponents) {
        throw "Unknown gauntlet opponent '$name'. Valid choices: $($validGauntletOpponents -join ', ')"
    }
}

. (Join-Path $PSScriptRoot "project_paths.ps1")
$suite = $PSScriptRoot
$root = Get-ChessProjectRoot
$cute = (Get-ChildItem (Join-Path $suite "cutechess") -Recurse -Filter "cutechess-cli.exe" |
         Select-Object -First 1).FullName
$blunder = (Get-ChildItem (Join-Path $suite "blunder") -Recurse -Filter "blunder-8.5.5-default.exe" |
            Select-Object -First 1).FullName
$stockfish = (Get-ChildItem (Join-Path $suite "stockfish") -Recurse -Filter "stockfish-windows-x86-64.exe" |
              Select-Object -First 1).FullName
$carballo = Join-Path $suite "carballo\carballo-1.8.jar"
$ourEngine = Get-EngineVersionPath $EngineVersion
$ourEngineName = "Engine $EngineVersion"
$resolvedEval = ""
if ($EvalFile) {
    $resolvedEval = (Resolve-Path -LiteralPath $EvalFile).Path
    $evalLabel = [System.IO.Path]::GetFileName((Split-Path -Parent $resolvedEval))
    $ourEngineName = "Engine $EngineVersion [$evalLabel]"
}
$openings = if ([System.IO.Path]::IsPathRooted($OpeningFile)) {
    $OpeningFile
} else {
    Join-Path $root $OpeningFile
}
$results = Get-TestResultDirectory "gauntlets" $EngineVersion

foreach ($required in @($cute, $blunder, $stockfish, $carballo, $ourEngine, $openings)) {
    if (-not $required -or -not (Test-Path -LiteralPath $required)) {
        throw "Required tournament file is missing: $required"
    }
}

function Get-OpponentArguments([string]$Name) {
    switch ($Name) {
        "Blunder" {
            return @("name=Blunder 8.5.5", "cmd=$blunder", "proto=uci",
                     "option.Hash=64", "option.UseBook=false")
        }
        "Carballo" {
            return @("name=Carballo 1.8", "cmd=java", "arg=-jar", "arg=$carballo",
                     "proto=uci", "option.Hash=64",
                     "option.OwnBook=false")
        }
        "StockfishFull" {
            return @("name=Stockfish 18 Full", "cmd=$stockfish", "proto=uci",
                     "option.Threads=$OpponentThreads", "option.Hash=64")
        }
        default {
            $elo = [int]$Name.Replace("Stockfish", "")
            return @("name=Stockfish 18 Elo $elo", "cmd=$stockfish", "proto=uci",
                     "option.Threads=$OpponentThreads", "option.Hash=64",
                     "option.UCI_LimitStrength=true", "option.UCI_Elo=$elo")
        }
    }
}

function Start-Match([string]$Name) {
    $stamp = Get-Date -Format "yyyyMMdd-HHmmss"
    $safeName = $Name.ToLowerInvariant()
    $safeVersion = $EngineVersion.ToLowerInvariant()
    $pgn = Join-Path $results "engine-$safeVersion-vs-$safeName-$stamp.pgn"
    $log = Join-Path $results "engine-$safeVersion-vs-$safeName-$stamp.log"
    $opponentArguments = Get-OpponentArguments $Name
    $ourEngineOptions = @("option.Move Overhead=0")
    if ($EngineThreads -gt 0) {
        $ourEngineOptions += "option.Threads=$EngineThreads"
    }
    if ($resolvedEval) {
        $ourEngineOptions += "option.EvalFile=$resolvedEval"
    }
    $arguments = @(
        "-engine", "name=$ourEngineName", "cmd=$ourEngine", "arg=--uci", "proto=uci",
        $ourEngineOptions,
        "-engine"
    ) + $opponentArguments + @(
        "-each", "tc=$TimeControl",
        "-openings", "file=$openings", "format=epd", "order=random", "policy=round",
        "-rounds", [string]($Games / 2), "-games", "2", "-repeat",
        "-concurrency", [string]$Concurrency, "-recover", "-ratinginterval", "10",
        "-pgnout", $pgn
    )

    Write-Host "Running $ourEngineName vs ${Name}: $Games games at $TimeControl, concurrency $Concurrency, threads $EngineThreads/$OpponentThreads"
    $savedPreference = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        & $cute @arguments 2>&1 | Tee-Object -FilePath $log | Out-Host
        $cuteExitCode = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $savedPreference
    }
    if ($cuteExitCode -ne 0) { throw "Cute Chess exited with code $cuteExitCode. See $log" }
    python (Join-Path $suite "summarize_pgn.py") $pgn $ourEngineName | Out-Host
    return [PSCustomObject]@{ Opponent = $Name; Pgn = $pgn }
}

if ($Opponent -eq "Gauntlet") {
    $completedMatches = @()
    $selectedOpponents = if ($GauntletOpponents.Count -gt 0) {
        $GauntletOpponents
    } else {
        @("Stockfish1320", "Stockfish1600", "Stockfish1750",
          "Stockfish1800", "Stockfish1850", "Stockfish2000",
          "Stockfish2400", "Blunder", "Carballo")
    }
    Write-Host "Gauntlet opponents: $($selectedOpponents -join ', ')"
    foreach ($name in $selectedOpponents) {
        $completedMatches += Start-Match $name
    }
    $summaryArguments = @("--gauntlet", $ourEngineName)
    foreach ($match in $completedMatches) {
        $summaryArguments += @($match.Opponent, $match.Pgn)
    }
    python (Join-Path $suite "summarize_pgn.py") @summaryArguments
} else {
    Start-Match $Opponent | Out-Null
}
