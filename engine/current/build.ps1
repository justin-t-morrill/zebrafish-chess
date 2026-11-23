param([switch]$AdaptiveTime)
$ErrorActionPreference = "Stop"
$gcc = (Get-Command gcc.exe -ErrorAction Stop).Source
$source = $PSScriptRoot
$root = Split-Path -Parent (Split-Path -Parent $source)
$fathom = Join-Path $root "endgames\fathom"
$fathomObject = Join-Path $fathom "tbprobe.o"

& $gcc -std=c11 -O3 -march=native -DNDEBUG -Wall -Wextra -pedantic `
    "-I$fathom" -c (Join-Path $fathom "tbprobe.c") -o $fathomObject
if ($LASTEXITCODE -ne 0) { throw "Fathom compilation failed." }

$textName = "chess.exe"
$flags = @()
if ($AdaptiveTime) { $textName = "chess-adaptive.exe"; $flags += "-DADAPTIVE_TIME" }
& $gcc -std=c11 -O3 -march=native -flto -DNDEBUG -Wall -Wextra -pedantic `
    @flags "-I$fathom" (Join-Path $source "chess.c") $fathomObject `
    -o (Join-Path $source $textName) -lgdiplus -lgdi32 -luser32
if ($LASTEXITCODE -ne 0) { throw "Text engine compilation failed." }
if ($AdaptiveTime) {
    Write-Host "Built $textName in $source (supports --uci and --gui)"
    return
}

& $gcc -std=c11 -O3 -march=native -flto -DNDEBUG -DCHESS_GUI_DEFAULT `
    -Wall -Wextra -pedantic "-I$fathom" (Join-Path $source "chess.c") `
    $fathomObject -o (Join-Path $source "chess_gui.exe") `
    -lgdiplus -lgdi32 -luser32
if ($LASTEXITCODE -ne 0) { throw "GUI engine compilation failed." }
Write-Host "Built current text and GUI engines in $source"
