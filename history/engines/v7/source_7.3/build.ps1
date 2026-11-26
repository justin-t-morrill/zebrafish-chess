$ErrorActionPreference = "Stop"
$gcc = (Get-Command gcc.exe -ErrorAction Stop).Source
$source = $PSScriptRoot
$output = Join-Path (Split-Path $source -Parent) "7.3.exe"
$guiOutput = Join-Path (Split-Path $source -Parent) "7.3_gui.exe"
$fathomObject = Join-Path $source "fathom\tbprobe.o"

& $gcc -std=c11 -O3 -march=native -DNDEBUG -Wall -Wextra -pedantic `
    "-I$(Join-Path $source 'fathom')" `
    -c (Join-Path $source "fathom\tbprobe.c") -o $fathomObject
if ($LASTEXITCODE -ne 0) { throw "Fathom compilation failed." }

# Keep the chess engine's LTO unit separate from the much larger third-party
# probe library. Combining both changed hot-search code layout enough to cost
# roughly 2% NPS even in positions with zero probes.
& $gcc -std=c11 -O3 -march=native -flto -DNDEBUG -Wall -Wextra -pedantic `
    "-I$(Join-Path $source 'fathom')" (Join-Path $source "chess.c") `
    $fathomObject -o $output -lgdiplus -lgdi32 -luser32
if ($LASTEXITCODE -ne 0) { throw "7.3 engine compilation failed." }

# The dedicated GUI binary uses the same code but enters native GUI mode when
# launched without arguments. The normal binary remains text-first and still
# supports an explicit --gui switch.
& $gcc -std=c11 -O3 -march=native -flto -DNDEBUG -DCHESS_GUI_DEFAULT `
    -Wall -Wextra -pedantic "-I$(Join-Path $source 'fathom')" `
    (Join-Path $source "chess.c") $fathomObject -o $guiOutput `
    -lgdiplus -lgdi32 -luser32
if ($LASTEXITCODE -ne 0) { throw "7.3 GUI compilation failed." }
Write-Host "Built: $output"
Write-Host "Built: $guiOutput"
