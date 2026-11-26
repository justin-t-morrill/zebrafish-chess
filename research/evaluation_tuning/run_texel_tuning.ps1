param(
    [string]$BaseEngine = "2.3",
    [string]$RunName = "",
    [string]$ReuseDataFrom = "",
    [string]$ReusePositionsFrom = "",
    [string]$Manifest = ".\research\evaluation_tuning\texel_games_spsa.txt",
    [ValidateSet("core", "pst", "eval", "positional", "king_safety_fast", "threats", "pawn_details", "bishop_quality", "all")][string]$Group = "all",
    [int]$PositionsPerGame = 0,
    [int]$MinimumPly = 16,
    [double]$MinimumAgeMinutes = 10,
    [int]$MaxGames = 0,
    [int]$Iterations = 12,
    [int]$BatchSize = 4096,
    [double]$Regularization = 0.00003,
    [double]$MinimumImprovement = 0.000001,
    [int]$Patience = 3,
    [double]$MinimumStep = 0.0001,
    [switch]$Rebuild,
    [switch]$AllowConcurrent
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
Set-Location $root
if ($BaseEngine -notmatch '^[A-Za-z0-9._-]+$') { throw "Unsafe base engine name." }
if ($ReuseDataFrom -and $ReuseDataFrom -notmatch '^[A-Za-z0-9._-]+$') {
    throw "Unsafe reusable run name."
}
if ($ReusePositionsFrom -and $ReusePositionsFrom -notmatch '^[A-Za-z0-9._-]+$') {
    throw "Unsafe reusable positions run name."
}
if ($ReuseDataFrom -and $ReusePositionsFrom) {
    throw "Use either -ReuseDataFrom or -ReusePositionsFrom, not both."
}
if ($ReuseDataFrom -and $Rebuild) {
    throw "-Rebuild cannot be combined with -ReuseDataFrom because the shared cache is read-only input."
}
if (-not $RunName) { $RunName = "${BaseEngine}_texel_$Group" }
$major = if ($BaseEngine -match '^(\d+)') { "v$($Matches[1])" } else { "misc" }
$baseSourceDirectory = Join-Path $root "history\engines\$major\source_$BaseEngine"
$baseEngineSource = Join-Path $baseSourceDirectory "chess_engine.c"
if (-not (Test-Path -LiteralPath (Join-Path $baseSourceDirectory "chess.c"))) {
    throw "Saved source for base engine '$BaseEngine' was not found."
}

# Feature extraction and fitting can consume substantial CPU.  More
# importantly, this prevents a partially-written tournament PGN from entering
# the corpus while Cute Chess is still appending to it.
if (-not $AllowConcurrent) {
    $active = Get-Process -Name "cutechess-cli", "stockfish*" -ErrorAction SilentlyContinue
    if ($active) {
        throw "A Cute Chess/Stockfish test is active. Wait for it to finish, or use -AllowConcurrent if the CPU contention and completed-PGN age filter are intentional."
    }
}

$manifestPath = (Resolve-Path -LiteralPath $Manifest).Path
$runDirectory = Join-Path $PSScriptRoot "texel_runs\$RunName"
New-Item -ItemType Directory -Force -Path $runDirectory | Out-Null
$baseMarker = Join-Path $runDirectory "base_engine.txt"
if (Test-Path -LiteralPath $baseMarker) {
    $recordedBase = (Get-Content -LiteralPath $baseMarker -Raw).Trim()
    if ($recordedBase -ne $BaseEngine) {
        throw "Run '$RunName' belongs to base '$recordedBase', not '$BaseEngine'. Choose a new RunName."
    }
} else {
    Set-Content -LiteralPath $baseMarker -Value $BaseEngine
}
$fitOutput = Join-Path $runDirectory "fit.txt"

$dataDirectory = $runDirectory
if ($ReuseDataFrom) {
    $dataDirectory = Join-Path $PSScriptRoot "texel_runs\$ReuseDataFrom"
    $reuseBaseMarker = Join-Path $dataDirectory "base_engine.txt"
    if (-not (Test-Path -LiteralPath $reuseBaseMarker)) {
        throw "Reusable Texel run '$ReuseDataFrom' was not found."
    }
    $reuseBase = (Get-Content -LiteralPath $reuseBaseMarker -Raw).Trim()
    if ($reuseBase -ne $BaseEngine) {
        throw "Reusable run '$ReuseDataFrom' uses base '$reuseBase', not '$BaseEngine'."
    }
}
$positions = Join-Path $dataDirectory "positions.csv"
$qsearch = Join-Path $dataDirectory "qsearch.csv"
$leaves = Join-Path $dataDirectory "leaves.csv"
$pawnFeatures = Join-Path $dataDirectory "eval_features.bin"
$featureCache = Join-Path $dataDirectory "features.npz"
if ($ReusePositionsFrom) {
    $positionsDirectory = Join-Path $PSScriptRoot "texel_runs\$ReusePositionsFrom"
    $positions = Join-Path $positionsDirectory "positions.csv"
    if (-not (Test-Path -LiteralPath $positions)) {
        throw "Reusable positions from '$ReusePositionsFrom' were not found."
    }
    Write-Host "Reusing selected positions from '$ReusePositionsFrom'; qsearch and features will be rebuilt for '$BaseEngine'."
}
if ($ReuseDataFrom) {
    # A source run created with -ReusePositionsFrom intentionally has no local
    # positions.csv. Full-cache reuse starts at its completed qsearch/features,
    # so requiring that borrowed intermediate file would reject a valid run.
    foreach ($requiredData in @($qsearch, $leaves, $pawnFeatures, $featureCache)) {
        if (-not (Test-Path -LiteralPath $requiredData)) {
            throw "Reusable run '$ReuseDataFrom' is incomplete; missing '$requiredData'."
        }
    }
    Write-Host "Reusing prepared dataset and feature cache from '$ReuseDataFrom'."
}

$qsearchExtractor = Join-Path $runDirectory "extract_texel_qsearch_$BaseEngine.exe"
$pawnExtractor = Join-Path $runDirectory "extract_eval_features_$BaseEngine.exe"
$sourceHeader = Join-Path $runDirectory "texel_engine_source_$BaseEngine.h"
$sourceInclude = '../../history/engines/' + $major + '/source_' + $BaseEngine + '/chess.c'
# Keep the quoted include path in a generated header. Passing this definition
# directly to GCC is unreliable because PowerShell can strip its quote marks.
Set-Content -LiteralPath $sourceHeader -Encoding ascii `
    -Value ('#define TEXEL_ENGINE_SOURCE "' + $sourceInclude + '"')
$gcc = (Get-Command gcc.exe -ErrorAction Stop).Source
$engineInputs = @(Get-ChildItem -LiteralPath $baseSourceDirectory -File |
    Where-Object { $_.Extension -in @('.c', '.h', '.inc') } |
    Sort-Object FullName)
function Get-TexelFingerprint([string]$toolSource, [string]$kind) {
    $parts = @("native-texel-v2", $kind)
    foreach ($file in @($engineInputs + (Get-Item -LiteralPath $toolSource))) {
        $parts += (Get-FileHash -Algorithm SHA256 -LiteralPath $file.FullName).Hash
    }
    return $parts -join ':'
}
$qsearchSource = Join-Path $PSScriptRoot "extract_texel_qsearch.c"
$featureSource = Join-Path $PSScriptRoot "extract_eval_features.c"
$qsearchFingerprint = Get-TexelFingerprint $qsearchSource "qsearch"
$featureFingerprint = Get-TexelFingerprint $featureSource "features"
$qsearchMarker = Join-Path $runDirectory "qsearch_fingerprint.txt"
$featureMarker = Join-Path $runDirectory "feature_fingerprint.txt"
$oldQsearchFingerprint = if (Test-Path -LiteralPath $qsearchMarker) {
    (Get-Content -LiteralPath $qsearchMarker -Raw).Trim()
} else { "" }
$oldFeatureFingerprint = if (Test-Path -LiteralPath $featureMarker) {
    (Get-Content -LiteralPath $featureMarker -Raw).Trim()
} else { "" }
$rebuildQsearchExtractor = $Rebuild -or -not (Test-Path -LiteralPath $qsearchExtractor) -or
    $oldQsearchFingerprint -ne $qsearchFingerprint
$rebuildFeatureExtractor = $Rebuild -or -not (Test-Path -LiteralPath $pawnExtractor) -or
    $oldFeatureFingerprint -ne $featureFingerprint
if (-not $ReuseDataFrom -and $rebuildQsearchExtractor) {
    foreach ($stale in @($qsearch, $leaves, $pawnFeatures, $featureCache)) {
        if (Test-Path -LiteralPath $stale) { Remove-Item -LiteralPath $stale }
    }
} elseif (-not $ReuseDataFrom -and $rebuildFeatureExtractor) {
    foreach ($stale in @($pawnFeatures, $featureCache)) {
        if (Test-Path -LiteralPath $stale) { Remove-Item -LiteralPath $stale }
    }
}
if ($rebuildQsearchExtractor) {
    & $gcc -std=c11 -O3 -DNDEBUG -include $sourceHeader -Wall -Wextra -pedantic `
        $qsearchSource -o $qsearchExtractor `
        -lgdiplus -lgdi32 -luser32
    if ($LASTEXITCODE -ne 0) { throw "Qsearch extractor compilation failed." }
    Set-Content -LiteralPath $qsearchMarker -Value $qsearchFingerprint
}
if ($rebuildFeatureExtractor) {
    & $gcc -std=c11 -O3 -DNDEBUG -include $sourceHeader -Wall -Wextra -pedantic `
        $featureSource -o $pawnExtractor `
        -lgdiplus -lgdi32 -luser32
    if ($LASTEXITCODE -ne 0) { throw "Evaluation feature extractor compilation failed." }
    Set-Content -LiteralPath $featureMarker -Value $featureFingerprint
}

# python-chess lives in the project's lightweight venv; NumPy lives in the
# bundled workspace runtime.  Combining those read-only package locations
# avoids installing or changing the Lichess environment.
$sitePackages = Join-Path $root "integrations\lichess-bot\.venv\lib\python3.14\site-packages"
$runtimeRoot = Join-Path $env:USERPROFILE ".cache\codex-runtimes\codex-primary-runtime\dependencies\python"
$numpyPython = Join-Path $runtimeRoot "python.exe"
if (-not (Test-Path -LiteralPath $numpyPython)) {
    $numpyPython = (Get-Command python.exe -ErrorAction Stop).Source
}
$oldPythonPath = $env:PYTHONPATH
$env:PYTHONPATH = $sitePackages
try {
    if (-not $ReuseDataFrom -and -not $ReusePositionsFrom -and
        ($Rebuild -or -not (Test-Path -LiteralPath $positions))) {
        $arguments = @(
            (Join-Path $PSScriptRoot "prepare_texel_positions.py"), $manifestPath, $positions,
            "--positions-per-game", $PositionsPerGame,
            "--minimum-ply", $MinimumPly,
            "--minimum-age-minutes", $MinimumAgeMinutes,
            "--max-games", $MaxGames
        )
        & $numpyPython @arguments
        if ($LASTEXITCODE -ne 0) { throw "PGN position preparation failed." }
    }
    if ($Rebuild -or -not (Test-Path -LiteralPath $qsearch)) {
        & $qsearchExtractor $positions $qsearch
        if ($LASTEXITCODE -ne 0) { throw "Deterministic qsearch extraction failed." }
    }
    if ($Rebuild -or -not (Test-Path -LiteralPath $leaves)) {
        & $numpyPython (Join-Path $PSScriptRoot "prepare_texel_leaves.py") $positions $qsearch $leaves
        if ($LASTEXITCODE -ne 0) { throw "Qsearch leaf preparation failed." }
    }
    if ($Rebuild -or -not (Test-Path -LiteralPath $pawnFeatures)) {
        & $pawnExtractor $leaves $pawnFeatures
        if ($LASTEXITCODE -ne 0) { throw "Evaluation feature extraction failed." }
    }
    if ($Rebuild -and (Test-Path -LiteralPath $featureCache)) {
        Remove-Item -LiteralPath $featureCache
    }
    & $numpyPython (Join-Path $PSScriptRoot "fit_texel_gauss_newton.py") `
        $leaves $pawnFeatures $fitOutput --cache $featureCache --group $Group `
        --iterations $Iterations --batch-size $BatchSize --base-source $baseEngineSource `
        --regularization $Regularization --minimum-improvement $MinimumImprovement `
        --patience $Patience --minimum-step $MinimumStep
    if ($LASTEXITCODE -ne 0) { throw "Gauss-Newton fitting failed." }
} finally {
    $env:PYTHONPATH = $oldPythonPath
}

Write-Host "Texel fit complete: $fitOutput"
Write-Host "The run is resumable; existing preparation files and the feature cache are reused."
