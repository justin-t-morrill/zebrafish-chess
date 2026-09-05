[CmdletBinding()]
param(
    [ValidateSet("small", "wdl6", "dtz6", "all")]
    [string]$Set = "all",

    [switch]$ManifestOnly,
    [switch]$VerifyOnly,

    # Useful for testing the downloader without starting the entire collection.
    [ValidateRange(0, 10000)]
    [int]$MaxFiles = 0
)

$ErrorActionPreference = "Stop"
$mirror = "https://tablebase.lichess.ovh/tables/standard"
$manifestDirectory = Join-Path $PSScriptRoot "manifests"
New-Item -ItemType Directory -Force -Path $manifestDirectory | Out-Null

$collections = @(
    [pscustomobject]@{ Key = "small"; Name = "3-4-5 WDL"; Url = "$mirror/3-4-5-wdl/"; Destination = (Join-Path $PSScriptRoot "3-4-5"); Extension = "rtbw" },
    [pscustomobject]@{ Key = "small"; Name = "3-4-5 DTZ"; Url = "$mirror/3-4-5-dtz/"; Destination = (Join-Path $PSScriptRoot "3-4-5"); Extension = "rtbz" },
    [pscustomobject]@{ Key = "wdl6";  Name = "6-piece WDL"; Url = "$mirror/6-wdl/"; Destination = (Join-Path $PSScriptRoot "6-WDL"); Extension = "rtbw" },
    [pscustomobject]@{ Key = "dtz6";  Name = "6-piece DTZ"; Url = "$mirror/6-dtz/"; Destination = (Join-Path $PSScriptRoot "6-DTZ"); Extension = "rtbz" }
)

if ($Set -ne "all") {
    $collections = @($collections | Where-Object Key -eq $Set)
}

function Format-ByteCount([long]$Bytes) {
    if ($Bytes -ge 1TB) { return "{0:N2} TB" -f ($Bytes / 1TB) }
    if ($Bytes -ge 1GB) { return "{0:N2} GB" -f ($Bytes / 1GB) }
    if ($Bytes -ge 1MB) { return "{0:N2} MB" -f ($Bytes / 1MB) }
    return "{0:N0} bytes" -f $Bytes
}

function Get-MirrorManifest($Collection) {
    $manifestPath = Join-Path $manifestDirectory ("{0}.csv" -f ($Collection.Name -replace '[^A-Za-z0-9]+', '_').Trim('_'))
    $indexPath = "$manifestPath.index.html"

    Write-Host "Reading $($Collection.Name) index..."
    & curl.exe -L --fail --silent --show-error --retry 5 --retry-all-errors --connect-timeout 30 --output $indexPath $Collection.Url
    if ($LASTEXITCODE -ne 0) {
        throw "Could not read $($Collection.Url) (curl exit code $LASTEXITCODE)."
    }

    $html = Get-Content -LiteralPath $indexPath -Raw
    Remove-Item -LiteralPath $indexPath -Force
    $pattern = 'href="(?<file>[^"/]+\.' + [regex]::Escape($Collection.Extension) + ')"[^>]*>.*?</a>\s+\S+\s+\S+\s+(?<size>\d+)'
    $rows = foreach ($match in [regex]::Matches($html, $pattern, [System.Text.RegularExpressions.RegexOptions]::IgnoreCase)) {
        [pscustomobject]@{
            File = [System.Net.WebUtility]::HtmlDecode($match.Groups['file'].Value)
            Size = [long]$match.Groups['size'].Value
            Url = $Collection.Url + $match.Groups['file'].Value
        }
    }

    if ($rows.Count -eq 0) {
        throw "No .$($Collection.Extension) files were found at $($Collection.Url). The mirror layout may have changed."
    }

    $rows | Sort-Object File | Export-Csv -LiteralPath $manifestPath -NoTypeInformation
    return @($rows | Sort-Object File)
}

$jobs = @()
foreach ($collection in $collections) {
    New-Item -ItemType Directory -Force -Path $collection.Destination | Out-Null
    $manifest = @(Get-MirrorManifest $collection)
    foreach ($entry in $manifest) {
        $jobs += [pscustomobject]@{
            Collection = $collection.Name
            Destination = $collection.Destination
            File = $entry.File
            Size = [long]$entry.Size
            Url = $entry.Url
        }
    }
}

if ($MaxFiles -gt 0) {
    $jobs = @($jobs | Select-Object -First $MaxFiles)
}

$publishedBytes = [long](($jobs | Measure-Object Size -Sum).Sum)
$completeBytes = 0L
$missingBytes = 0L
$badFiles = @()

foreach ($job in $jobs) {
    $path = Join-Path $job.Destination $job.File
    if (Test-Path -LiteralPath $path) {
        $actual = (Get-Item -LiteralPath $path).Length
        if ($actual -eq $job.Size) {
            $completeBytes += $actual
        } elseif ($actual -lt $job.Size) {
            $completeBytes += $actual
            $missingBytes += ($job.Size - $actual)
        } else {
            $badFiles += "$path is larger than its published size ($actual vs $($job.Size))"
        }
    } else {
        $missingBytes += $job.Size
    }
}

Write-Host ""
Write-Host "Files: $($jobs.Count)"
Write-Host "Published size: $(Format-ByteCount $publishedBytes)"
Write-Host "Already present: $(Format-ByteCount $completeBytes)"
Write-Host "Remaining: $(Format-ByteCount $missingBytes)"

if ($badFiles.Count -gt 0) {
    $badFiles | ForEach-Object { Write-Error $_ }
    throw "Oversized/corrupt files must be moved or removed before downloading."
}

if ($ManifestOnly) {
    Write-Host "Manifest-only run complete."
    exit 0
}

if ($VerifyOnly) {
    if ($missingBytes -eq 0) {
        Write-Host "Verification passed: every file has its published size."
        exit 0
    }
    throw "Verification failed: $(Format-ByteCount $missingBytes) is absent or incomplete."
}

$driveName = (Get-Item -LiteralPath $PSScriptRoot).PSDrive.Name
$freeBytes = (Get-PSDrive -Name $driveName).Free
$safetyMargin = 5GB
if ($freeBytes -lt ($missingBytes + $safetyMargin)) {
    throw "Not enough free space. Need $(Format-ByteCount ($missingBytes + $safetyMargin)); available $(Format-ByteCount $freeBytes)."
}

$index = 0
foreach ($job in $jobs) {
    ++$index
    $path = Join-Path $job.Destination $job.File
    if ((Test-Path -LiteralPath $path) -and ((Get-Item -LiteralPath $path).Length -eq $job.Size)) {
        Write-Host "[$index/$($jobs.Count)] complete $($job.File)"
        continue
    }

    Write-Host "[$index/$($jobs.Count)] downloading $($job.File) ($(Format-ByteCount $job.Size))"
    & curl.exe -L --fail --show-error --retry 20 --retry-delay 5 --retry-all-errors --connect-timeout 30 --continue-at - --output $path $job.Url
    if ($LASTEXITCODE -ne 0) {
        throw "Download failed for $($job.File) (curl exit code $LASTEXITCODE). Run this script again to resume."
    }

    $actual = (Get-Item -LiteralPath $path).Length
    if ($actual -ne $job.Size) {
        throw "Size verification failed for $($job.File): received $actual bytes, expected $($job.Size). Run again to resume."
    }
}

Write-Host "All requested Syzygy files were downloaded and size-verified."
