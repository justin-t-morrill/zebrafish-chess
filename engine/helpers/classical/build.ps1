$ErrorActionPreference = 'Stop'
$root = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..\..'))
$output = Join-Path $root 'build\helpers'
$fathom = Join-Path $root 'third_party\fathom'
New-Item -ItemType Directory -Force -Path $output | Out-Null
$gcc = (Get-Command gcc.exe -ErrorAction Stop).Source
$object = Join-Path $output 'tbprobe.o'
& $gcc -std=c11 -O2 -DNDEBUG "-I$fathom" -c (Join-Path $fathom 'tbprobe.c') -o $object
if ($LASTEXITCODE -ne 0) { throw 'Fathom compilation failed.' }
$pending = Join-Path $output 'classical_breakdown.pending.exe'
& $gcc -std=c11 -O2 -DNDEBUG "-I$fathom" (Join-Path $PSScriptRoot 'classical_breakdown.c') $object -o $pending -lgdiplus -lgdi32 -luser32 -lcomctl32 -luxtheme -lm
if ($LASTEXITCODE -ne 0) { throw 'Classical helper compilation failed.' }
Move-Item -LiteralPath $pending -Destination (Join-Path $output 'classical_breakdown.exe') -Force
Write-Output "Built explanation helper in $output"
