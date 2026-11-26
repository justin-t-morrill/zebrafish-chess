$archive = Join-Path $PSScriptRoot "data\lichess-evals\lichess_db_eval.jsonl.zst"
$expected = 21681515630L

if (-not (Test-Path -LiteralPath $archive)) {
    Write-Host "The archive has not started downloading yet."
    exit
}

$file = Get-Item -LiteralPath $archive
$percent = 100.0 * $file.Length / $expected
Write-Host ("Downloaded {0:N2} GiB / {1:N2} GiB ({2:N1}%)" -f `
    ($file.Length / 1GB), ($expected / 1GB), $percent)

$process = Get-Process -Name "curl" -ErrorAction SilentlyContinue
if ($process) {
    Write-Host "Download is running."
} elseif ($file.Length -eq $expected) {
    Write-Host "Download is complete."
} else {
    Write-Host "Download is paused. Run download_lichess_evals.ps1 to resume it."
}
