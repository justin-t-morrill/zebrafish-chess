param(
    [ValidateSet('play', 'test', 'live', 'results', 'build', 'setup', 'verify', 'desktop', 'native')]
    [string]$Action = 'play',
    [int]$Port = 0,
    [switch]$NoBrowser,
    [switch]$Check,
    [switch]$RepairPaths,
    [switch]$Current
)
$ErrorActionPreference = 'Stop'
$root = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..'))
$candidates = @()
if ($env:ZEBRAFISH_PYTHON) { $candidates += $env:ZEBRAFISH_PYTHON }
$candidates += (Join-Path $root '.venv\Scripts\python.exe')
$candidates += (Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe')
$candidates += (Join-Path $env:LOCALAPPDATA 'Programs\Python\Python312\python.exe')
$onPath = Get-Command python.exe -ErrorAction SilentlyContinue
if ($onPath -and $onPath.Source -notmatch 'WindowsApps') { $candidates += $onPath.Source }
$runtime = $null
foreach ($candidate in ($candidates | Select-Object -Unique)) {
    if (-not (Test-Path -LiteralPath $candidate)) { continue }
    & $candidate -B -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' 2>$null
    if ($LASTEXITCODE -eq 0) { $runtime = $candidate; break }
}
if (-not $runtime) { throw 'Python 3.11 or later is required. Install Python or set ZEBRAFISH_PYTHON to python.exe.' }
$previousPath = $env:PYTHONPATH
$previousBytecode = $env:PYTHONDONTWRITEBYTECODE
$env:PYTHONPATH = (Join-Path $root 'src') + [IO.Path]::PathSeparator + (Join-Path $root 'analysis\game_review\vendor_runtime')
if ($previousPath) { $env:PYTHONPATH += [IO.Path]::PathSeparator + $previousPath }
$env:PYTHONDONTWRITEBYTECODE = '1'
try {
    $arguments = @('-B', '-m', 'zebrafish.launcher', $Action)
    if ($Port) { $arguments += @('--port', "$Port") }
    if ($NoBrowser) { $arguments += '--no-browser' }
    if ($Check) { $arguments += '--check' }
    if ($RepairPaths) { $arguments += '--repair-paths' }
    if ($Current) { $arguments += '--current' }
    & $runtime @arguments
    $result = $LASTEXITCODE
} finally {
    $env:PYTHONPATH = $previousPath
    $env:PYTHONDONTWRITEBYTECODE = $previousBytecode
}
exit $result
