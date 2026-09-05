$ErrorActionPreference = "Stop"
$gcc = (Get-Command gcc.exe -ErrorAction Stop).Source
$review = $PSScriptRoot
$root = Resolve-Path (Join-Path $review "..\..\..")
$fathom = Join-Path $root "endgames\fathom"
$fathomObject = Join-Path $fathom "tbprobe.o"

if (-not (Test-Path -LiteralPath $fathomObject)) {
    & $gcc -std=c11 -O2 -DNDEBUG -Wall -Wextra -pedantic `
        "-I$fathom" -c (Join-Path $fathom "tbprobe.c") -o $fathomObject
    if ($LASTEXITCODE -ne 0) { throw "Fathom compilation failed." }
}

& $gcc -std=c11 -O2 -DNDEBUG -Wall -Wextra -pedantic `
    "-I$fathom" (Join-Path $review "classical_breakdown.c") $fathomObject `
    -o (Join-Path $review "classical_breakdown.exe") `
    -lgdiplus -lgdi32 -luser32
if ($LASTEXITCODE -ne 0) { throw "Classical breakdown helper compilation failed." }
Write-Host "Built game-review classical evaluation helper."
