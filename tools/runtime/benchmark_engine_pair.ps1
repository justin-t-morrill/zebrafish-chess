param(
    [Parameter(Mandatory = $true)][string]$EngineA,
    [Parameter(Mandatory = $true)][string]$EngineB,
    [ValidateRange(1, 20)][int]$Repetitions = 3,
    [ValidateRange(1, 4096)][int]$HashMB = 64,
    [ValidateRange(0, 6)][int]$DepthOffset = 0
)

$ErrorActionPreference = "Stop"
$root = Resolve-Path (Join-Path $PSScriptRoot "..\..")

function Resolve-Engine([string]$Name) {
    if (Test-Path -LiteralPath $Name) { return (Resolve-Path $Name).Path }
    $major = ($Name -split '\.')[0]
    $path = Join-Path $root "history\engines\v$major\$Name.exe"
    if (-not (Test-Path -LiteralPath $path)) {
        throw "Engine executable not found: $path"
    }
    return $path
}

$positions = @(
    @{ Fen = "r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq - 0 1"; Depth = 7 },
    @{ Fen = "4rrk1/pp1q1ppp/2p2n2/3p4/3P4/2PBPN2/PPQ2PPP/R3K2R w KQ - 4 12"; Depth = 7 },
    @{ Fen = "2r2rk1/1bqnbppp/p2ppn2/1p6/3NP3/P1N1B3/1PQ1BPPP/2RR2K1 w - - 2 15"; Depth = 7 },
    @{ Fen = "8/2p5/3p4/KP5r/1R3p1k/8/4P1P1/8 w - - 0 1"; Depth = 8 },
    @{ Fen = "rnbq1k1r/pp1Pbppp/2p2n2/8/2B5/8/PPP1NPPP/RNBQK2R w KQ - 1 8"; Depth = 8 },
    @{ Fen = "r4rk1/1pp1qppp/p1npbn2/8/2BPP3/P1N2N2/1P3PPP/R1BQR1K1 w - - 0 12"; Depth = 7 },
    @{ Fen = "2rq1rk1/pp2bppp/2npbn2/3p4/3P4/2NBPN2/PPQ1BPPP/2RR2K1 w - - 4 13"; Depth = 7 },
    @{ Fen = "4r1k1/1p3ppp/p1p2n2/3p4/3P4/2P1P3/PP3PPP/2R3K1 w - - 0 24"; Depth = 9 }
)

function Read-Until([System.Diagnostics.Process]$Process, [string]$Pattern) {
    while (-not $Process.StandardOutput.EndOfStream) {
        $line = $Process.StandardOutput.ReadLine()
        if ($line -match $Pattern) { return $line }
    }
    throw "Engine exited before producing '$Pattern'."
}

function Start-Engine([string]$Path) {
    $start = [System.Diagnostics.ProcessStartInfo]::new()
    $start.FileName = $Path
    $start.Arguments = "--uci"
    $start.UseShellExecute = $false
    $start.CreateNoWindow = $true
    $start.RedirectStandardInput = $true
    $start.RedirectStandardOutput = $true
    $process = [System.Diagnostics.Process]::new()
    $process.StartInfo = $start
    if (-not $process.Start()) { throw "Could not start $Path" }
    $process.StandardInput.WriteLine("uci")
    [void](Read-Until $process '^uciok$')
    $process.StandardInput.WriteLine("setoption name Threads value 1")
    $process.StandardInput.WriteLine("setoption name Hash value $HashMB")
    $process.StandardInput.WriteLine("setoption name OwnBook value false")
    $process.StandardInput.WriteLine("isready")
    [void](Read-Until $process '^readyok$')
    return $process
}

function Search-One([System.Diagnostics.Process]$Process, $Position) {
    $Process.StandardInput.WriteLine("setoption name Clear Hash")
    $Process.StandardInput.WriteLine("position fen $($Position.Fen)")
    $watch = [System.Diagnostics.Stopwatch]::StartNew()
    $searchDepth = $Position.Depth + $DepthOffset
    $Process.StandardInput.WriteLine("go depth $searchDepth")
    $info = $null
    $best = $null
    $ttEvalHits = 0
    while (-not $Process.StandardOutput.EndOfStream) {
        $line = $Process.StandardOutput.ReadLine()
        if ($line -match '^info string tt-static-eval-hits (\d+)$') {
            $ttEvalHits = [uint64]$Matches[1]
        } elseif ($line -match '^info depth (\d+) score cp (-?\d+) nodes (\d+) time (\d+) nps (\d+)') {
            $info = [pscustomobject]@{
                Depth = [int]$Matches[1]; Score = [int]$Matches[2]
                Nodes = [uint64]$Matches[3]; EngineMs = [int]$Matches[4]
                Nps = [uint64]$Matches[5]
            }
        } elseif ($line -match '^bestmove (\S+)') {
            $best = $Matches[1]
            break
        }
    }
    $watch.Stop()
    if ($null -eq $info -or $null -eq $best) { throw "Incomplete UCI result" }
    return [pscustomobject]@{
        Depth = $info.Depth; Score = $info.Score; Nodes = $info.Nodes
        EngineMs = $info.EngineMs; WallMs = $watch.Elapsed.TotalMilliseconds
        Nps = $info.Nps; BestMove = $best; TtEvalHits = $ttEvalHits
    }
}

$paths = @{ A = Resolve-Engine $EngineA; B = Resolve-Engine $EngineB }
$processes = @{ A = Start-Engine $paths.A; B = Start-Engine $paths.B }
$rows = [System.Collections.Generic.List[object]]::new()
try {
    for ($rep = 1; $rep -le $Repetitions; ++$rep) {
        $order = if (($rep % 2) -eq 1) { @('A', 'B') } else { @('B', 'A') }
        for ($index = 0; $index -lt $positions.Count; ++$index) {
            foreach ($label in $order) {
                $result = Search-One $processes[$label] $positions[$index]
                $rows.Add([pscustomobject]@{
                    Engine = $label; Repetition = $rep; Position = $index + 1
                    Depth = $result.Depth; Score = $result.Score
                    Nodes = $result.Nodes; EngineMs = $result.EngineMs
                    WallMs = [math]::Round($result.WallMs, 2); Nps = $result.Nps
                    BestMove = $result.BestMove; TtEvalHits = $result.TtEvalHits
                })
            }
        }
    }
} finally {
    foreach ($process in $processes.Values) {
        if (-not $process.HasExited) {
            $process.StandardInput.WriteLine("quit")
            [void]$process.WaitForExit(5000)
        }
        $process.Dispose()
    }
}

$summary = $rows | Group-Object Engine | ForEach-Object {
    [pscustomobject]@{
        Engine = $_.Name
        Searches = $_.Count
        TotalNodes = [uint64](($_.Group | Measure-Object Nodes -Sum).Sum)
        TotalEngineMs = [uint64](($_.Group | Measure-Object EngineMs -Sum).Sum)
        TotalWallMs = [math]::Round(($_.Group | Measure-Object WallMs -Sum).Sum, 2)
        AvgNps = [uint64](($_.Group | Measure-Object Nps -Average).Average)
        TtEvalHits = [uint64](($_.Group | Measure-Object TtEvalHits -Sum).Sum)
    }
} | Sort-Object Engine

$mismatches = for ($rep = 1; $rep -le $Repetitions; ++$rep) {
    for ($position = 1; $position -le $positions.Count; ++$position) {
        $a = $rows | Where-Object { $_.Engine -eq 'A' -and $_.Repetition -eq $rep -and $_.Position -eq $position }
        $b = $rows | Where-Object { $_.Engine -eq 'B' -and $_.Repetition -eq $rep -and $_.Position -eq $position }
        if ($a.BestMove -ne $b.BestMove -or $a.Score -ne $b.Score -or $a.Nodes -ne $b.Nodes) {
            [pscustomobject]@{ Repetition = $rep; Position = $position; A = "$($a.BestMove)/$($a.Score)/$($a.Nodes)"; B = "$($b.BestMove)/$($b.Score)/$($b.Nodes)" }
        }
    }
}

$summary | Format-Table -AutoSize
Write-Host "Deterministic move/score/node mismatches: $(@($mismatches).Count)"
if ($mismatches) { $mismatches | Format-Table -AutoSize }
