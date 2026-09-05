$campaign = Join-Path $PSScriptRoot 'data\stockfish-8hour'
$pids = Get-Content (Join-Path $campaign 'worker-pids.txt')
$running = @(Get-Process -Id $pids -ErrorAction SilentlyContinue)
$outputs = Get-ChildItem (Join-Path $campaign 'labels\labels-*.csv') -ErrorAction SilentlyContinue
$logs = Get-ChildItem (Join-Path $campaign 'logs\worker-*.out.log') -ErrorAction SilentlyContinue
$errors = Get-ChildItem (Join-Path $campaign 'logs\worker-*.err.log') -ErrorAction SilentlyContinue

Write-Host "Workers running: $($running.Count) / $($pids.Count)"
foreach ($log in $logs) {
    $last = Get-Content $log.FullName -Tail 1
    if ($last) { Write-Host $last }
}
$errorBytes = ($errors | Measure-Object Length -Sum).Sum
$outputBytes = ($outputs | Measure-Object Length -Sum).Sum
Write-Host ("Label output: {0:N1} MB; error logs: {1} bytes" -f ($outputBytes / 1MB), $errorBytes)
