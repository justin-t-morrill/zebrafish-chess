param(
    [string]$TimeControl = "180+1",
    [ValidateRange(1,16)][int]$Concurrency = 6,
    [ValidateRange(2,10000)][int]$MaxGames = 2000,
    [switch]$Resume,
    [switch]$Promote,
    [switch]$SpeedTest,
    [switch]$Preview
)

$ErrorActionPreference = "Stop"
if ($Resume -or $Promote) {
    $originalClock = if ($SpeedTest) { "1+0.1" } else { "180+1" }
    if (($PSBoundParameters.ContainsKey("TimeControl") -and $TimeControl -ne $originalClock) -or $PSBoundParameters.ContainsKey("MaxGames")) {
        throw "Resuming uses the original $originalClock time control and recorded game cap."
    }
    $python = Join-Path $env:LOCALAPPDATA "Programs\Python\Python312\python.exe"
    $launcher = Get-Command py.exe -ErrorAction SilentlyContinue
    if (-not (Test-Path -LiteralPath $python) -and $launcher) {
        $installs = Split-Path -Parent (Split-Path -Parent $launcher.Source)
        $python = Join-Path $installs "Python312\python.exe"
    }
    if (-not (Test-Path -LiteralPath $python)) { $python = "python" }
    if ($Promote) {
        if ($Resume -or $SpeedTest) { throw "Choose -Promote as a separate action after the three-minute decision." }
        $promoter = Join-Path $PSScriptRoot "..\..\..\testing\results\overnight_9_0_20261124\promote_stable.py"
        $promotionArgs = @($promoter)
        if ($Preview) { $promotionArgs += "--preview" }
        & $python @promotionArgs
        if ($LASTEXITCODE -ne 0) { throw "9.1 promotion exited with status $LASTEXITCODE." }
        return
    }
    $resumeArgs = @((Join-Path $PSScriptRoot "resume-blitz.py"))
    if ($SpeedTest) { $resumeArgs += "--speed" }
    if ($PSBoundParameters.ContainsKey("Concurrency")) { $resumeArgs += @("--concurrency", $Concurrency) }
    if ($Preview) { $resumeArgs += "--status" }
    & $python @resumeArgs
    if ($LASTEXITCODE -ne 0) { throw "Continuation exited with status $LASTEXITCODE." }
    return
}
$root = (Resolve-Path (Join-Path $PSScriptRoot "..\..\..")).Path
$runner = Join-Path $root "testing\tools\run_version_sprt.ps1"
$baseline = Join-Path $root "engines\versions\v9\9.0.exe"
$candidate = Join-Path $PSScriptRoot "9.1-rc1.exe"
$config = @{
    EngineA = "9.1-rc1"; EngineB = "9.0"; BinaryA = $candidate; BinaryB = $baseline
    TimeControl = $TimeControl; ThreadsA = 1; ThreadsB = 1; Concurrency = $Concurrency
    MaxGames = $MaxGames; Elo0 = 0; Elo1 = 10; Alpha = 0.05; Beta = 0.05
    SearchOnly = $true; Preview = $Preview
}
if ($SpeedTest) {
    $run = Join-Path $root "testing\results\overnight_9_0_20261124"
    $config.EngineA = "lean"
    $config.EngineB = "trained"
    $config.BinaryA = Join-Path $run "lean\lean.exe"
    $config.BinaryB = Join-Path $run "trained\trained.exe"
}
& $runner @config
