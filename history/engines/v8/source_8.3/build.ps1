$ErrorActionPreference = "Stop"
$gcc = (Get-Command gcc.exe -ErrorAction Stop).Source
$source = $PSScriptRoot
$root = Split-Path -Parent (Split-Path -Parent (Split-Path -Parent (Split-Path -Parent $source)))
$fathom = Join-Path $root "endgames\fathom"
$fathomObject = Join-Path $fathom "tbprobe.o"
$outputDirectory = Split-Path -Parent $source

& $gcc -std=c11 -O3 -march=native -DNDEBUG -Wall -Wextra -pedantic `
    "-I$fathom" -c (Join-Path $fathom "tbprobe.c") -o $fathomObject
if ($LASTEXITCODE -ne 0) { throw "Fathom compilation failed." }

& $gcc -std=c11 -O3 -march=native -flto -DNDEBUG -Wall -Wextra -pedantic `
    "-I$fathom" (Join-Path $source "chess.c") $fathomObject `
    -o (Join-Path $outputDirectory "8.3.exe") -lgdiplus -lgdi32 -luser32
if ($LASTEXITCODE -ne 0) { throw "Text engine compilation failed." }

& $gcc -std=c11 -O3 -march=native -flto -DNDEBUG -DCHESS_GUI_DEFAULT `
    -Wall -Wextra -pedantic "-I$fathom" (Join-Path $source "chess.c") `
    $fathomObject -o (Join-Path $outputDirectory "8.3_gui.exe") `
    -lgdiplus -lgdi32 -luser32
if ($LASTEXITCODE -ne 0) { throw "GUI engine compilation failed." }
Write-Host "Built Engine 8.3 text and GUI binaries in $outputDirectory"
