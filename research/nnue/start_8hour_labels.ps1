param([double]$Hours = 8.0)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$pythonPackages = Join-Path $PSScriptRoot 'python_packages'
$source = Join-Path $root 'tuning\texel_runs\5.0_native_selfplay_all\leaves.csv'
$campaign = Join-Path $PSScriptRoot 'data\stockfish-8hour'
$shards = Join-Path $campaign 'shards'
$labels = Join-Path $campaign 'labels'
$logs = Join-Path $campaign 'logs'
$stockfish = Join-Path $root 'reference_engines\stockfish\stockfish\stockfish-windows-x86-64.exe'
New-Item -ItemType Directory -Force -Path $campaign,$shards,$labels,$logs | Out-Null

if (-not (Test-Path (Join-Path $shards 'sample-00.csv'))) {
    python (Join-Path $PSScriptRoot 'prepare_label_shards.py') $source $shards --per-game 70 --shards 8
}

$oldPythonPath = $env:PYTHONPATH
$env:PYTHONPATH = $pythonPackages
$started = @()
try {
    for ($i = 0; $i -lt 8; ++$i) {
        $id = $i.ToString('00')
        $input = Join-Path $shards "sample-$id.csv"
        $output = Join-Path $labels "labels-$id.csv"
        $stdout = Join-Path $logs "worker-$id.out.log"
        $stderr = Join-Path $logs "worker-$id.err.log"
        $arguments = @(
            (Join-Path $PSScriptRoot 'label_stockfish_shard.py'),
            $stockfish, $input, $output, '--hours', $Hours,
            '--shallow-nodes', 5000, '--deep-nodes', 25000, '--max-delta', 80
        )
        $process = Start-Process -FilePath 'python' -ArgumentList $arguments `
            -RedirectStandardOutput $stdout -RedirectStandardError $stderr `
            -WindowStyle Hidden -PassThru
        $started += $process.Id
    }
} finally {
    $env:PYTHONPATH = $oldPythonPath
}
$started | Set-Content (Join-Path $campaign 'worker-pids.txt')
"Started Stockfish label workers: $($started -join ', ')" | Tee-Object (Join-Path $campaign 'launch.txt')
