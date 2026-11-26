param([string]$OutputPath = (Join-Path $PSScriptRoot "9.1-rc2.exe"))

$ErrorActionPreference = "Stop"
$root = (Resolve-Path (Join-Path $PSScriptRoot "..\..\..")).Path
$fathom = Join-Path $root "endgames\fathom"
$gcc = (Get-Command gcc.exe -ErrorAction Stop).Source
$source = Join-Path $PSScriptRoot "source\chess.c"
$object = Join-Path ([System.IO.Path]::GetTempPath()) ("zebrafish-fathom-" + [guid]::NewGuid() + ".o")
$flags = @("-std=c11", "-O3", "-march=native", "-DNDEBUG", "-Wall", "-Wextra", "-pedantic", "-I$fathom")
try {
    & $gcc @flags -c (Join-Path $fathom "tbprobe.c") -o $object
    if ($LASTEXITCODE) { throw "Fathom build failed." }
    & $gcc @flags -flto $source $object -o $OutputPath -lgdiplus -lgdi32 -luser32
    if ($LASTEXITCODE) { throw "Engine build failed." }
} finally {
    if (Test-Path -LiteralPath $object) { Remove-Item -LiteralPath $object }
}
