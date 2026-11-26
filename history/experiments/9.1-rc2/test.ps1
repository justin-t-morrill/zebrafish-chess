param([string]$Network = (Join-Path $PSScriptRoot "nnue-material.bin"))

$ErrorActionPreference = "Stop"
$root = (Resolve-Path (Join-Path $PSScriptRoot "..\..\..")).Path
$fathom = Join-Path $root "endgames\fathom"
$index = [guid]::NewGuid().ToString()
$temp = [System.IO.Path]::GetTempPath()
$object = Join-Path $temp "zebrafish-verify-$index.o"
$test = Join-Path $temp "zebrafish-verify-$index.exe"
$gcc = (Get-Command gcc.exe -ErrorAction Stop).Source
$flags = @("-std=c11", "-O3", "-march=native", "-I$fathom")
try {
    & $gcc @flags -c (Join-Path $fathom "tbprobe.c") -o $object
    if ($LASTEXITCODE) { throw "Fathom compilation failed." }
    & $gcc @flags (Join-Path $PSScriptRoot "verify.c") $object -o $test -lgdiplus -lgdi32 -luser32
    if ($LASTEXITCODE) { throw "Verification build failed." }
    $arguments = @($Network)
    $tablebases = Join-Path $root "endgames\syzygy\3-4-5"
    if (Test-Path -LiteralPath (Join-Path $tablebases "KQvK.rtbw")) { $arguments += $tablebases }
    & $test @arguments
    if ($LASTEXITCODE) { throw "Move, evaluator or tablebase verification failed." }
    $engine = Join-Path $PSScriptRoot "9.1-rc2.exe"
    $selftest = @("selftest","quit") | & $engine
    if ($LASTEXITCODE -or -not ($selftest -match "Selftest: PASS")) { throw "Perft or clock selftest failed." }
    Write-Output "Perft and adaptive-clock selftests passed."
} finally {
    foreach ($path in @($test,$object)) {
        if (Test-Path -LiteralPath $path) { Remove-Item -LiteralPath $path }
    }
}
