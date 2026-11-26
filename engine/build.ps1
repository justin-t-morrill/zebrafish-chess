param([string]$OutputDirectory = '')
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$paths = Get-Content -LiteralPath (Join-Path $root 'config\paths.json') -Raw | ConvertFrom-Json
$source = Join-Path $root $paths.engine_source
$networks = Join-Path $root $paths.engine_networks
$fathom = Join-Path $root $paths.fathom
$output = if ($OutputDirectory) { [IO.Path]::GetFullPath($OutputDirectory) } else { Join-Path $root 'build\current' }
New-Item -ItemType Directory -Force -Path $output | Out-Null
$gcc = (Get-Command gcc.exe -ErrorAction Stop).Source
$object = Join-Path $output 'tbprobe.o'
& $gcc -std=c11 -O3 -march=native -DNDEBUG "-I$fathom" -c (Join-Path $fathom 'tbprobe.c') -o $object
if ($LASTEXITCODE -ne 0) { throw 'Fathom compilation failed.' }
Get-ChildItem -LiteralPath $networks -Filter '*.bin' -File | Copy-Item -Destination $output
foreach ($mode in @('text','gui')) {
    $arguments = @('-std=c11','-O3','-march=native','-flto','-DNDEBUG','-Wall','-Wextra','-pedantic',"-I$fathom")
    if ($mode -eq 'gui') { $arguments += '-DCHESS_GUI_DEFAULT' }
    $name = if ($mode -eq 'gui') { 'chess_gui.exe' } else { 'chess.exe' }
    $pending = Join-Path $output ($name + '.pending.exe')
    $arguments += @((Join-Path $source 'chess.c'),$object,'-o',$pending,'-lgdiplus','-lgdi32','-luser32','-lcomctl32','-luxtheme','-lm')
    & $gcc @arguments
    if ($LASTEXITCODE -ne 0) { throw "$mode engine compilation failed." }
    Move-Item -LiteralPath $pending -Destination (Join-Path $output $name) -Force
}
Get-ChildItem -LiteralPath $networks -Filter '*.bin' -File | Copy-Item -Destination $output
Write-Output "Built text and native GUI engines in $output"
