param(
    [int]$TrainingPositions = 96,
    [int]$BenchmarkRuns = 15
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$source = Join-Path $root 'engine_versions\source_3.4\chess.c'
$suite = Join-Path $root 'tuning\runtime_profile\benchmark_suite.txt'
$epd = Join-Path $root '8moves_v3.epd'
$output = Join-Path $PSScriptRoot 'build_3.4'
$profile = Join-Path $output 'profile_data_v3'

New-Item -ItemType Directory -Force -Path $output, $profile | Out-Null

$libraries = @('-lgdiplus', '-lgdi32', '-luser32')
function Build-Engine([string]$name, [string[]]$flags) {
    $target = Join-Path $output "$name.exe"
    & gcc '-std=c11' @flags $source '-o' $target @libraries
    if ($LASTEXITCODE -ne 0) { throw "Compilation failed for $name" }
    return $target
}

$builds = [ordered]@{}
$builds.O2 = Build-Engine '3.4_O2' @('-O2')
$builds.O3 = Build-Engine '3.4_O3' @('-O3')
$builds.Native = Build-Engine '3.4_O3_native' @('-O3', '-march=native')
$builds.LTO = Build-Engine '3.4_O3_native_lto' @('-O3', '-march=native', '-flto')

# Use the same object/output basename for profile generation and profile use so
# GCC can associate the collected .gcda counters with the final compilation.
$pgoWork = Join-Path $output 'pgo_engine.exe'
Push-Location $output
& gcc '-std=c11' '-O3' '-march=native' '-flto' '-fprofile-generate=profile_data_v3' `
    $source '-o' 'pgo_engine.exe' @libraries
if ($LASTEXITCODE -ne 0) { throw 'PGO training build failed' }

$training = [Text.StringBuilder]::new()
[void]$training.AppendLine('uci')
Get-Content -LiteralPath $epd -TotalCount $TrainingPositions | ForEach-Object {
    [void]$training.AppendLine("position fen $_")
    [void]$training.AppendLine('go depth 4')
}
[void]$training.AppendLine('quit')
$training.ToString() | & $pgoWork '--uci' | Out-Null
if ($LASTEXITCODE -ne 0) { throw 'PGO training run failed' }

& gcc '-std=c11' '-O3' '-march=native' '-flto' '-fprofile-use=profile_data_v3' `
    '-fprofile-correction' $source '-o' 'pgo_engine.exe' @libraries
if ($LASTEXITCODE -ne 0) { throw 'PGO optimized build failed' }
Pop-Location
$pgoFinal = Join-Path $output '3.4_O3_native_lto_pgo.exe'
Copy-Item -LiteralPath $pgoWork -Destination $pgoFinal -Force
$builds.PGO = $pgoFinal

$benchmarkInput = [IO.File]::ReadAllText($suite)
function Measure-Engine([string]$executable) {
    $start = [Diagnostics.ProcessStartInfo]::new()
    $start.FileName = $executable
    $start.Arguments = '--uci'
    $start.UseShellExecute = $false
    $start.RedirectStandardInput = $true
    $start.RedirectStandardOutput = $true
    $start.RedirectStandardError = $true
    $process = [Diagnostics.Process]::new()
    $process.StartInfo = $start
    $timer = [Diagnostics.Stopwatch]::StartNew()
    [void]$process.Start()
    $process.StandardInput.Write($script:benchmarkInput)
    $process.StandardInput.Close()
    $null = $process.StandardOutput.ReadToEnd()
    $errorText = $process.StandardError.ReadToEnd()
    $process.WaitForExit()
    $timer.Stop()
    if ($process.ExitCode -ne 0) { throw "$executable failed: $errorText" }
    return $timer.Elapsed.TotalMilliseconds
}

$times = @{}
foreach ($name in $builds.Keys) {
    $times[$name] = @()
    [void](Measure-Engine $builds[$name])
}
1..$BenchmarkRuns | ForEach-Object {
    $order = if ($_ % 2) { @($builds.Keys) } else { @($builds.Keys)[-1..-5] }
    foreach ($name in $order) {
        $times[$name] += Measure-Engine $builds[$name]
    }
}

$results = foreach ($name in $builds.Keys) {
    $sorted = @($times[$name] | Sort-Object)
    $middle = [int][Math]::Floor($sorted.Count / 2)
    $median = if ($sorted.Count % 2) { $sorted[$middle] } else {
        ($sorted[$middle - 1] + $sorted[$middle]) / 2
    }
    [pscustomobject]@{
        Build = $name
        MedianMs = [Math]::Round($median, 2)
        MeanMs = [Math]::Round(($times[$name] | Measure-Object -Average).Average, 2)
        MinimumMs = [Math]::Round($sorted[0], 2)
        MaximumMs = [Math]::Round($sorted[-1], 2)
    }
}
$results | Format-Table -AutoSize
$results | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $output 'results.json')
