param([switch]$Standby, [switch]$Check)
$ErrorActionPreference = 'Stop'
$root = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..'))
$checkout = Join-Path $root 'third_party\lichess-bot'
$config = Join-Path $root 'local\config\lichess\config.yml'
$python = @((Join-Path $checkout '.venv\Scripts\python.exe'),(Join-Path $checkout '.venv\bin\python.exe')) |
    Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
if (-not $python) { throw 'The bot environment is missing. See integrations/lichess/README.md.' }
if (-not (Test-Path -LiteralPath $config)) { throw 'Run launchers/optional/Zebrafish-Bot-Setup.cmd to save the token locally.' }
if (-not (Test-Path -LiteralPath (Join-Path $root 'build\current\chess.exe'))) { throw 'The current engine is missing.' }
if ($Check) {
    Write-Output 'Bot environment, local configuration and current engine are present. No Lichess connection was made.'
    exit 0
}
$logs = Join-Path $root 'integrations\logs'
New-Item -ItemType Directory -Force -Path $logs | Out-Null
while ($true) {
    try { $lock = [IO.File]::Open((Join-Path $logs 'lichess-supervisor.lock'),'OpenOrCreate','ReadWrite','None'); break }
    catch [IO.IOException] {
        if (($_.Exception.HResult -band 65535) -notin 32,33) { throw }
        if (-not $Standby) { Write-Output 'The Lichess supervisor is already running.'; exit 0 }
        Start-Sleep -Seconds 10
    }
}
Push-Location $checkout
try {
    while ($true) {
        $started = Get-Date
        & $python -B -u (Join-Path $checkout 'lichess-bot.py') --config $config
        $result = $LASTEXITCODE
        if ($result -eq -1073741510) { break }
        Add-Content -LiteralPath (Join-Path $logs 'lichess-supervisor.log') -Value "$(Get-Date -Format o) Bot exited ($result); restarting."
        $delay = if (((Get-Date)-$started).TotalSeconds -lt 60) { 60 } else { 10 }
        Start-Sleep -Seconds $delay
    }
} finally { Pop-Location; $lock.Dispose() }
