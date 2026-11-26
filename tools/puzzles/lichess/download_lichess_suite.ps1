param(
    [ValidateRange(1, 100000)]
    [int]$PerTheme = 2000,
    [string]$OutputName = "lichess_themed_30k.csv"
)

$ErrorActionPreference = "Stop"
$directory = $PSScriptRoot
$database = Join-Path $directory "data\lichess_db_puzzle.csv.zst"
$output = Join-Path $directory "data\$OutputName"
New-Item -ItemType Directory -Force (Split-Path $database) | Out-Null

if (-not (Test-Path -LiteralPath $database)) {
    Write-Host "Downloading the official Lichess puzzle database..."
    curl.exe -L --fail --retry 3 --output $database `
        "https://database.lichess.org/lichess_db_puzzle.csv.zst"
    if ($LASTEXITCODE -ne 0) { throw "Puzzle database download failed." }
} else {
    Write-Host "Reusing downloaded database: $database"
}

$zstd = (Get-Command zstd.exe -ErrorAction Stop).Source
python (Join-Path $directory "prepare_lichess_puzzles.py") `
    $database $output --per-theme $PerTheme --zstd $zstd
if ($LASTEXITCODE -ne 0) { throw "Puzzle selection failed." }
Write-Host "Puzzle suite ready: $output"
