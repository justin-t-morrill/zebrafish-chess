param([switch]$Preview, [switch]$Resume)

$ErrorActionPreference = "Stop"
$root = (Resolve-Path (Join-Path $PSScriptRoot "..\..\..")).Path
$runner = Join-Path $root "testing\tools\run_8.3_ccrl_calibration.ps1"
$binary = Join-Path $PSScriptRoot "9.1-rc1.exe"
$python = "python"
$launcher = Get-Command py.exe -ErrorAction SilentlyContinue
if ($launcher) {
    $installs = Split-Path -Parent (Split-Path -Parent $launcher.Source)
    $local = Join-Path $installs "Python312\python.exe"
    if (Test-Path -LiteralPath $local) { $python = $local }
}
if ($Resume) {
    $arguments = @((Join-Path $PSScriptRoot "resume-calibration.py"))
    if ($Preview) { $arguments += "--status" }
    & $python @arguments
    if ($LASTEXITCODE -ne 0) { throw "Calibration continuation exited with code $LASTEXITCODE." }
} else {
    & $runner -CandidateName "9.1-rc1" -CandidateBinary $binary -PythonExecutable $python -Preview:$Preview
}
