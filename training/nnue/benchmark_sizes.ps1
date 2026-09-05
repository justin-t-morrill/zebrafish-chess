param(
    [int[]]$Depths = @(8, 10, 12),
    [int]$Trials = 3,
    [string[]]$NetworkNames = @()
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$engine = Join-Path $PSScriptRoot 'sf8h_benchmark.exe'
$suite = Join-Path $root 'testing\runtime\profiles\benchmark_suite.txt'
$positions = Get-Content $suite | Where-Object { $_ -like 'position fen *' }
$networks = [ordered]@{
    'current-v8' = Join-Path $root 'engine\current\nnue-8.0.bin'
    'plain128' = Join-Path $PSScriptRoot 'checkpoints\minimal-chess-768x128-sf8h-wdl000-40\quantised.bin'
    'plain256' = Join-Path $PSScriptRoot 'checkpoints\minimal-chess-768x256-sf8h-wdl000-40\quantised.bin'
    'lichess128' = Join-Path $PSScriptRoot 'checkpoints\minimal-chess-768x128-lichess10m-wdl000-40\quantised.bin'
    'lichess256' = Join-Path $PSScriptRoot 'checkpoints\minimal-chess-768x256-lichess10m-wdl000-40\quantised.bin'
    'lichess-king128' = Join-Path $PSScriptRoot 'checkpoints\minimal-chess-king10x128-lichess10m-wdl000-40\quantised.bin'
    'lichess-king256' = Join-Path $PSScriptRoot 'checkpoints\minimal-chess-king10x256-lichess10m-wdl000-40\quantised.bin'
    'full128' = Join-Path $PSScriptRoot 'checkpoints\minimal-chess-768x128-lichessfull5ep-wdl000-40\quantised.bin'
    'full256' = Join-Path $PSScriptRoot 'checkpoints\minimal-chess-768x256-lichessfull5ep-wdl000-40\quantised.bin'
    'full-king128' = Join-Path $PSScriptRoot 'checkpoints\minimal-chess-king10x128-lichessfull10ep-wdl000-40\quantised.bin'
    'full-king256' = Join-Path $PSScriptRoot 'checkpoints\minimal-chess-king10x256-lichessfull10ep-wdl000-40\quantised.bin'
    'king128' = Join-Path $PSScriptRoot 'checkpoints\minimal-chess-king10x128-sf8h-wdl000-40\quantised.bin'
    'king256' = Join-Path $PSScriptRoot 'checkpoints\minimal-chess-king10x256-sf8h-wdl000-40\quantised.bin'
    'king128-wdl10' = Join-Path $PSScriptRoot 'checkpoints\minimal-chess-king10x128-sf8h-wdl010-40\quantised.bin'
}

$results = [System.Collections.Generic.List[object]]::new()
foreach ($depth in $Depths) {
    foreach ($network in $networks.GetEnumerator()) {
        if ($NetworkNames.Count -gt 0 -and $NetworkNames -notcontains $network.Key) { continue }
        for ($trial = 1; $trial -le $Trials; ++$trial) {
            $start = [System.Diagnostics.ProcessStartInfo]::new()
            $start.FileName = $engine
            $start.Arguments = '--uci'
            $start.UseShellExecute = $false
            $start.CreateNoWindow = $true
            $start.RedirectStandardInput = $true
            $start.RedirectStandardOutput = $true
            $process = [System.Diagnostics.Process]::Start($start)
            $process.StandardInput.WriteLine('uci')
            while ($process.StandardOutput.ReadLine() -ne 'uciok') {}
            $process.StandardInput.WriteLine('setoption name OwnBook value false')
            $process.StandardInput.WriteLine('setoption name SyzygyProbeLimit value 0')
            $process.StandardInput.WriteLine("setoption name EvalFile value $($network.Value)")
            $process.StandardInput.WriteLine('isready')
            while ($process.StandardOutput.ReadLine() -ne 'readyok') {}
            $index = 0
            foreach ($position in $positions) {
                $process.StandardInput.WriteLine('ucinewgame')
                $process.StandardInput.WriteLine($position)
                $process.StandardInput.WriteLine("go depth $depth")
                $searchLine = $null
                do {
                    $line = $process.StandardOutput.ReadLine()
                    if ($line -match '^info depth (\d+) score .* nodes (\d+) time (\d+) nps (\d+)') {
                        $searchLine = $line
                    }
                } while ($line -notlike 'bestmove *')
                if ($searchLine -match '^info depth (\d+) score .* nodes (\d+) time (\d+) nps (\d+)') {
                    $reportedNodes = [long]$Matches[2]
                    $reportedTime = [long]$Matches[3]
                    $reportedNps = [long]$Matches[4]
                    $results.Add([pscustomobject]@{
                        Network = $network.Key
                        Depth = $depth
                        Trial = $trial
                        Position = ++$index
                        Nodes = $reportedNodes
                        TimeMs = $reportedTime
                        Nps = $reportedNps
                    })
                } else { throw "missing search result for position $($index + 1)" }
            }
            $process.StandardInput.WriteLine('quit')
            $process.WaitForExit()
            if ($process.ExitCode -ne 0) { throw "engine exited with $($process.ExitCode)" }
            if ($index -ne $positions.Count) {
                throw "expected $($positions.Count) results, got $index for $($network.Key)/$depth/$trial"
            }
            Write-Host "finished network=$($network.Key) depth=$depth trial=$trial"
        }
    }
}

$rawPath = Join-Path $PSScriptRoot 'sf8h_benchmark_raw.csv'
$summaryPath = Join-Path $PSScriptRoot 'sf8h_benchmark_summary.csv'
$results | Export-Csv -LiteralPath $rawPath -NoTypeInformation
$summary = $results | Group-Object Network, Depth | ForEach-Object {
    $nodes = ($_.Group | Measure-Object Nodes -Sum).Sum
    $time = ($_.Group | Measure-Object TimeMs -Sum).Sum
    [pscustomobject]@{
        Network = $_.Group[0].Network
        Depth = $_.Group[0].Depth
        Searches = $_.Count
        Nodes = $nodes
        TimeMs = $time
        AggregateNps = if ($time) { [math]::Round(1000.0 * $nodes / $time) } else { 0 }
        MeanTimeMs = [math]::Round($time / [double]$_.Count, 2)
        MeanNodes = [math]::Round($nodes / [double]$_.Count, 2)
    }
}
$summary | Sort-Object Depth, Network | Export-Csv -LiteralPath $summaryPath -NoTypeInformation
$summary | Sort-Object Depth, Network | Format-Table -AutoSize
