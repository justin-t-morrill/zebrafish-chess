$data = Join-Path $PSScriptRoot "data\lichess-evals"
$stage = Join-Path $data "full-pipeline.stage.txt"
$log = Join-Path $data "full-pipeline.log"
if (Test-Path -LiteralPath $stage) {
    Write-Host "Stage: $((Get-Content -LiteralPath $stage -Raw).Trim())"
} else {
    Write-Host "The full pipeline has not started."
}
$processes = Get-Process -Name python,zstd,minimal-chess-nnue,cutechess-cli -ErrorAction SilentlyContinue
if ($processes) {
    Write-Host "Active: $((($processes | Select-Object -ExpandProperty ProcessName -Unique) -join ', '))"
}
if (Test-Path -LiteralPath $log) {
    Write-Host "Recent output:"
    Get-Content -LiteralPath $log -Tail 12
}
