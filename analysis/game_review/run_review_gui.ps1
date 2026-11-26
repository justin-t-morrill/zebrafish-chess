param([switch]$Native)
$ErrorActionPreference = "Stop"
if (-not $Native) {
    & (Join-Path $PSScriptRoot "..\..\start_zebrafish.ps1")
    exit $LASTEXITCODE
}
$source = Join-Path $PSScriptRoot "review_gui.py"
$bundledPython = "C:\Users\Justin\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
if (Test-Path -LiteralPath $bundledPython) {
    & $bundledPython $source
} else {
    python $source
}
