function Get-ChessProjectRoot {
    $candidate = (Resolve-Path -LiteralPath $PSScriptRoot).Path
    while ($candidate) {
        if (Test-Path -LiteralPath (Join-Path $candidate ".chess-project")) { return $candidate }
        $parent = Split-Path -Parent $candidate
        if ($parent -eq $candidate) { break }
        $candidate = $parent
    }
    throw "Could not locate the Chess_2 project root."
}

function Get-EngineVersionPath([string]$Name) {
    if ($Name -notmatch '^[A-Za-z0-9._-]+$') { throw "Unsafe engine version name: $Name" }
    $root = Get-ChessProjectRoot
    $match = [regex]::Match($Name, '^(\d+)')
    $bucket = if ($match.Success) { "v$($match.Groups[1].Value)" } else { "misc" }
    $directory = Join-Path $root "engines\versions\$bucket"
    foreach ($file in @("${Name}_uci.exe", "$Name.exe")) {
        $candidate = Join-Path $directory $file
        if (Test-Path -LiteralPath $candidate) { return $candidate }
    }
    return Join-Path $directory "$Name.exe"
}

function Get-TestResultDirectory([string]$Kind, [string]$EngineName) {
    $root = Get-ChessProjectRoot
    $match = [regex]::Match($EngineName, '^(\d+)')
    $bucket = if ($match.Success) { "v$($match.Groups[1].Value)" } else { "misc" }
    $directory = Join-Path $root "testing\results\$Kind\$bucket"
    New-Item -ItemType Directory -Force -Path $directory | Out-Null
    return $directory
}
