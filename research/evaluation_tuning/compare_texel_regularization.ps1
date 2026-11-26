param(
    [string]$RunName = "2.2_texel_eval_spsa_all_positions",
    [string]$BaseEngine = "2.2",
    [ValidateSet("pst", "eval", "all")][string]$Group = "eval",
    [double[]]$Regularization = @(0.00001, 0.0001, 0.001, 0.01),
    [int]$Iterations = 30,
    [int]$BatchSize = 4096
)

$ErrorActionPreference = "Stop"
$root = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..'))
if ($BaseEngine -notmatch '^[A-Za-z0-9._-]+$') { throw "Unsafe base engine name." }
$run = Join-Path $PSScriptRoot "texel_runs\$RunName"
$baseSource = Join-Path $root ("history\engines\v{0}\source_{1}\chess_engine.c" -f $BaseEngine.Split('.')[0], $BaseEngine)
$baseMarker = Join-Path $run "base_engine.txt"
if (Test-Path -LiteralPath $baseMarker) {
    $recordedBase = (Get-Content -LiteralPath $baseMarker -Raw).Trim()
    if ($recordedBase -ne $BaseEngine) { throw "Cached run uses base '$recordedBase', not '$BaseEngine'." }
} elseif ($BaseEngine -ne "2.2") {
    throw "Legacy unmarked caches are Engine 2.2 only. Build a new run for '$BaseEngine'."
}
$leaves = Join-Path $run "leaves.csv"
$pawns = Join-Path $run "pawn_features.csv"
$cache = Join-Path $run "features.npz"
foreach ($required in @($leaves, $pawns, $cache)) {
    if (-not (Test-Path -LiteralPath $required)) { throw "Missing cached input: $required" }
}
$python = Join-Path $env:USERPROFILE ".cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
$sitePackages = Join-Path $root "third_party\lichess-bot\.venv\lib\python3.14\site-packages"
$oldPythonPath = $env:PYTHONPATH
$env:PYTHONPATH = $sitePackages
try {
    foreach ($lambda in $Regularization) {
        $tag = $lambda.ToString("0.########", [Globalization.CultureInfo]::InvariantCulture).Replace(".", "p")
        $output = Join-Path $run "fit_${Group}_l2_$tag.txt"
        Write-Host "Fitting group=$Group lambda=$lambda"
        & $python (Join-Path $PSScriptRoot "fit_texel_gauss_newton.py") `
            $leaves $pawns $output --cache $cache --group $Group `
            --iterations $Iterations --batch-size $BatchSize `
            --regularization $lambda --minimum-improvement 0.000001 `
            --patience 3 --minimum-step 0.0001 --base-source $baseSource
        if ($LASTEXITCODE -ne 0) { throw "Fit failed for lambda=$lambda" }
    }
} finally {
    $env:PYTHONPATH = $oldPythonPath
}

$report = Join-Path $run "regularization_comparison_${Group}.txt"
$lines = foreach ($file in Get-ChildItem $run -Filter "fit_${Group}_l2_*.txt" | Sort-Object Name) {
    $content = Get-Content -LiteralPath $file
    $lambda = ($content | Where-Object { $_ -like "regularization=*" }) -replace '^regularization=', ''
    $validation = $content | Where-Object { $_ -like "validation:*" }
    $test = $content | Where-Object { $_ -like "test:*" }
    $size = ($content | Where-Object { $_ -like "maximum_normalized_delta=*" }) -replace '^maximum_normalized_delta=', ''
    $stop = ($content | Where-Object { $_ -like "stop_reason=*" }) -replace '^stop_reason=', ''
    "lambda=$lambda | max_normalized_delta=$size | stop=$stop`n  $validation`n  $test"
}
$lines | Set-Content -LiteralPath $report
Get-Content -LiteralPath $report
Write-Host "Comparison: $report"
