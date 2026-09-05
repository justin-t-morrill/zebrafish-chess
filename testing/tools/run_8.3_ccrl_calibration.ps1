param(
    [ValidateSet("Short", "Full")]
    [string]$Profile = "Short",
    [string]$TimeControl = "68.2+0.57",
    [ValidateRange(1, 16)]
    [int]$Concurrency = 1
)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "project_paths.ps1")
$root = Get-ChessProjectRoot
$cute = (Get-ChildItem (Join-Path $PSScriptRoot "cutechess") -Recurse `
    -Filter "cutechess-cli.exe" | Select-Object -First 1).FullName
$ourEngine = Join-Path $root "engines\versions\v8\8.3.exe"
$openings = Join-Path $root "openings\suites\8moves_v3.epd"
$pool = Join-Path $PSScriptRoot "ccrl_engines"
$results = Join-Path $root "testing\results\calibration\v8.3"
$statePath = Join-Path $results "ccrl-calibration-state.json"
New-Item -ItemType Directory -Force -Path $results | Out-Null

$opponents = @(
    [pscustomobject]@{
        Key = "jackal-1.0.0"; Name = "Jackal 1.0.0"; Rating = 2949; Games = 100
        Path = Join-Path $pool "jackal-1.0.0-x86-64-v3.exe"
        Options = @("option.Hash=128", "option.Threads=1")
    },
    [pscustomobject]@{
        Key = "pesto-2.210"; Name = "PeSTO 2.210"; Rating = 2989; Games = 100
        Path = Join-Path $pool "pesto-2.210\PeSTO_bmi2.exe"
        Options = @("option.Hash=128", "option.Threads=1", "option.SyzygyProbeDepth=0")
    },
    [pscustomobject]@{
        Key = "peacekeeper-1.60"; Name = "Peacekeeper v1.60"; Rating = 3043; Games = 70
        Path = Join-Path $pool "peacekeeper-1.60.exe"
        Options = @("option.Hash=128", "option.Threads=1")
    }
)

foreach ($required in @($cute, $ourEngine, $openings) + $opponents.Path) {
    if (-not (Test-Path -LiteralPath $required)) { throw "Missing required file: $required" }
}

$state = [ordered]@{
    status = "running"
    engine = "8.3"
    time_control = $TimeControl
    ccrl_reference_time_control = "120+1"
    stockfish_10_reference_ms = 2054
    stockfish_10_local_median_ms = 1167
    hardware_time_factor = 0.5682
    engine_hash_mb = 512
    opponent_hash_mb = 128
    ponder = $false
    tablebases = "disabled for both sides"
    threads = 8
    concurrency = $Concurrency
    profile = "Centered near 2950; excludes 20 completed Blunder and 10 completed Black Marlin games"
    total_games = ($opponents | Measure-Object -Property Games -Sum).Sum
    opponent_count = $opponents.Count
    games_by_opponent = [ordered]@{
        "jackal-1.0.0" = $opponents[0].Games
        "pesto-2.210" = $opponents[1].Games
        "peacekeeper-1.60" = $opponents[2].Games
    }
    current = ""
    completed = @()
}
function Save-State {
    $state | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $statePath
}

try {
    foreach ($opponent in $opponents) {
        $games = [int]$opponent.Games
        if (($games % 2) -ne 0) { throw "Game count for $($opponent.Key) must be even." }
        $state.current = $opponent.Key
        Save-State
        $stamp = Get-Date -Format "yyyyMMdd-HHmmss"
        $prefix = "8.3-vs-$($opponent.Key)-$stamp"
        $pgn = Join-Path $results "$prefix.pgn"
        $log = Join-Path $results "$prefix.log"
        $ourOptions = @(
            "option.Threads=8", "option.Hash=512", "option.OwnBook=false",
            "option.SyzygyProbeLimit=0", "option.Move Overhead=0"
        )
        $arguments = @(
            "-engine", "name=Engine 8.3 64-bit 8CPU", "cmd=$ourEngine", "arg=--uci", "proto=uci",
                $ourOptions,
            "-engine", "name=$($opponent.Name)", "cmd=$($opponent.Path)", "proto=uci",
                $opponent.Options,
            "-each", "tc=$TimeControl",
            "-openings", "file=$openings", "format=epd", "order=random", "policy=round",
            "-rounds", [string]($games / 2), "-games", "2", "-repeat",
            "-concurrency", [string]$Concurrency, "-recover", "-ratinginterval", "10",
            "-pgnout", $pgn
        )
        Write-Host "Running Engine 8.3 8CPU vs $($opponent.Name) ($($opponent.Rating) CCRL): $games games"
        $savedPreference = $ErrorActionPreference
        $ErrorActionPreference = "Continue"
        try {
            & $cute @arguments 2>&1 | Tee-Object -FilePath $log | Out-Host
            $exitCode = $LASTEXITCODE
        } finally {
            $ErrorActionPreference = $savedPreference
        }
        if ($exitCode -ne 0) { throw "Cute Chess exited with $exitCode; see $log" }
        python (Join-Path $PSScriptRoot "summarize_pgn.py") $pgn "Engine 8.3 64-bit 8CPU" | Out-Host
        $state.completed += [ordered]@{
            opponent = $opponent.Key; ccrl_rating = $opponent.Rating
            pgn = $pgn; log = $log
        }
        Save-State
    }
    $state.status = "complete"
    $state.current = ""
    Save-State
} catch {
    $state.status = "failed"
    $state.error = $_.Exception.Message
    Save-State
    throw
}
