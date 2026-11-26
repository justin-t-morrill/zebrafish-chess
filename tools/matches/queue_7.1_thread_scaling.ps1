param(
    [Parameter(Mandatory = $true)]
    [int]$WaitForProcessId
)

$ErrorActionPreference = "Stop"
$root = Resolve-Path (Join-Path $PSScriptRoot "..")
$queueLog = Join-Path $PSScriptRoot "results\7.1-thread-scaling-queue.log"

function Write-QueueLog([string]$Message) {
    $line = "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] $Message"
    Add-Content -LiteralPath $queueLog -Value $line
}

Write-QueueLog "Waiting for Cute Chess process $WaitForProcessId."
while ($null -ne (Get-Process -Id $WaitForProcessId -ErrorAction SilentlyContinue)) {
    # Polling avoids Windows denying a SYNCHRONIZE handle to a process owned
    # by the interactive terminal session. The query itself is read-only.
    Start-Sleep -Seconds 10
}
Write-QueueLog "Process is absent; continuing."

Write-QueueLog "Building and promoting provisional Engine 7.1."
& (Join-Path $root "engine_versions\source_7.1\build.ps1") *>> $queueLog
if ($LASTEXITCODE -ne 0) { throw "Engine 7.1 build failed." }

$source = Join-Path $root "engine_versions\source_7.1"
$sourceFiles = @(
    "bitboard_movegen.c", "board_logic.c", "chess_engine.c", "chess_gui.c",
    "chess_main.c", "chess_types.c", "chess.c", "command_helpers.c",
    "game_helpers.c", "joint_tables_wdl.inc", "README.md", "syzygy.c",
    "tournament.c", "tuned_pst_wdl.inc", "uci.c"
)
foreach ($file in $sourceFiles) {
    Copy-Item -LiteralPath (Join-Path $source $file) `
              -Destination (Join-Path $root $file) -Force
}

$versionExe = Join-Path $root "engine_versions\7.1.exe"
$versionGui = Join-Path $root "engine_versions\7.1_gui.exe"
Copy-Item -LiteralPath $versionExe -Destination (Join-Path $root "chess.exe") -Force
Copy-Item -LiteralPath $versionExe -Destination (Join-Path $root "chess_text.exe") -Force
Copy-Item -LiteralPath $versionExe -Destination (Join-Path $root "chess_native.exe") -Force
Copy-Item -LiteralPath $versionGui -Destination (Join-Path $root "chess_gui.exe") -Force

# Separate filenames let Cute Chess assign distinct player identities while
# both sides execute byte-identical Engine 7.1 code with different UCI options.
Copy-Item -LiteralPath $versionExe `
          -Destination (Join-Path $root "engine_versions\7.1_threads16.exe") -Force
Copy-Item -LiteralPath $versionExe `
          -Destination (Join-Path $root "engine_versions\7.1_threads8.exe") -Force

Write-QueueLog "Starting 16-thread versus 8-thread SPRT."
& (Join-Path $PSScriptRoot "run_version_sprt.ps1") `
    -EngineA 7.1_threads16 `
    -EngineB 7.1_threads8 `
    -ThreadsA 16 `
    -ThreadsB 8 `
    -MaxGames 10000 `
    -TimeControl "3+0.03" `
    -Concurrency 1 `
    -Elo0 0 `
    -Elo1 10 *>> $queueLog

Write-QueueLog "Thread-scaling SPRT finished."
