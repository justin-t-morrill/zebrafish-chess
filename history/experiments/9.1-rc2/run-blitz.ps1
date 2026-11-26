param([string]$TimeControl="180+1", [ValidateRange(1,16)][int]$Concurrency=6,
      [ValidateRange(2,10000)][int]$MaxGames=2000, [switch]$Preview, [switch]$Resume)
$ErrorActionPreference = "Stop"
$root = (Resolve-Path (Join-Path $PSScriptRoot "..\..\..")).Path
if ($Resume) {
    if ($TimeControl -ne "180+1" -or $PSBoundParameters.ContainsKey("MaxGames")) {
        throw "Resuming uses the original three-minute control and the 1,700-game cap."
    }
    $python = Join-Path $env:LOCALAPPDATA "Programs\Python\Python312\python.exe"
    $launcher = Get-Command py.exe -ErrorAction SilentlyContinue
    if (-not (Test-Path -LiteralPath $python) -and $launcher) {
        $installs = Split-Path -Parent (Split-Path -Parent $launcher.Source)
        $python = Join-Path $installs "Python312\python.exe"
    }
    if (-not (Test-Path -LiteralPath $python)) { $python = "python" }
    $script = Join-Path $root "engines\experiments\9.1-rc1\resume-blitz.py"
    $resumeArgs = @($script, "--challenger", "--concurrency", $Concurrency)
    if ($Preview) { $resumeArgs += "--status" }
    & $python @resumeArgs
    if ($LASTEXITCODE -ne 0) { throw "Blitz continuation exited with code $LASTEXITCODE." }
    return
}
$runner = Join-Path $root "testing\tools\run_version_sprt.ps1"
$baseline = Join-Path $root "engines\experiments\9.1-rc1\9.1-rc1.exe"
$candidate = Join-Path $PSScriptRoot "9.1-rc2.exe"
$config = @{
    EngineA = "9.1-rc2"; EngineB = "9.1-rc1"; BinaryA = $candidate; BinaryB = $baseline
    TimeControl = $TimeControl; ThreadsA = 1; ThreadsB = 1; Concurrency = $Concurrency
    MaxGames = $MaxGames; Elo0 = 0; Elo1 = 10; Alpha = 0.05; Beta = 0.05
    SearchOnly = $true; Preview = $Preview
}
& $runner @config
