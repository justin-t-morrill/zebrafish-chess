param(
    [string]$OutputDirectory = "$PSScriptRoot\data\lichess-evals"
)

$ErrorActionPreference = "Stop"
$url = "https://database.lichess.org/lichess_db_eval.jsonl.zst"
$archive = Join-Path $OutputDirectory "lichess_db_eval.jsonl.zst"
$log = Join-Path $OutputDirectory "download.log"

New-Item -ItemType Directory -Force -Path $OutputDirectory | Out-Null
$arguments = @(
    "--fail", "--location", "--continue-at", "-",
    "--retry", "12", "--retry-delay", "10",
    "--speed-time", "60", "--speed-limit", "1024",
    "--output", $archive, $url
)
$process = Start-Process -FilePath "C:\Windows\System32\curl.exe" `
    -ArgumentList $arguments -WindowStyle Hidden -Wait -PassThru `
    -RedirectStandardError $log
if ($process.ExitCode -ne 0) {
    throw "Lichess download failed with exit code $($process.ExitCode). Re-run this script to resume."
}
