param(
    [ValidateRange(2, 2000)][int]$GamesPerProfile = 120,
    [ValidateRange(1, 16)][int]$Concurrency = 6,
    [double]$SecondsPerMove = 0.10,
    [string]$EngineVersion = "Current",
    [string[]]$ProfileNames = @()
)
$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "..\tools\project_paths.ps1")
$root = Get-ChessProjectRoot
$cute = (Get-ChildItem (Join-Path $root "local\tools\cutechess") -Recurse -Filter cutechess-cli.exe | Select-Object -First 1).FullName
$stockfish = (Get-ChildItem (Join-Path $root "local\tools\stockfish") -Recurse -Filter stockfish-windows-x86-64.exe | Select-Object -First 1).FullName
$engine = if ($EngineVersion -eq "Current") { Join-Path $root "build\current\chess.exe" } else { Get-EngineVersionPath $EngineVersion }
$python = (Get-Command python).Source
$proxy = Join-Path $PSScriptRoot "limited_strength_uci.py"
$book = Join-Path $root "resources\books\OpeningBook.tsv"
$openings = Join-Path $root "tests\fixtures\openings\8moves_v3.epd"
$results = Join-Path $root "local\results\strength_calibration\v${EngineVersion}_perception"
New-Item -ItemType Directory -Force -Path $results | Out-Null
if (($GamesPerProfile % 2) -ne 0) { throw "GamesPerProfile must be even." }

# Beginner anchors are measured against the next profile in the chain. The
# established 1200 point connects that chain to Stockfish's minimum 1320 level.
$profiles = @(
    @{Name="p400";Target=400;Reference=600;ProxyReference=$true},
    @{Name="p600";Target=600;Reference=800;ProxyReference=$true},
    @{Name="p800";Target=800;Reference=1000;ProxyReference=$true},
    @{Name="p1000";Target=1000;Reference=1200;ProxyReference=$true},
    @{Name="p1200";Target=1200;Reference=1320;ProxyReference=$false},
    @{Name="p1500";Target=1500;Reference=1500;ProxyReference=$false},
    @{Name="p1800";Target=1800;Reference=1800;ProxyReference=$false},
    @{Name="p2100";Target=2100;Reference=2100;ProxyReference=$false},
    @{Name="p2400";Target=2400;Reference=2400;ProxyReference=$false},
    @{Name="p2600";Target=2600;Reference=2600;ProxyReference=$false},
    @{Name="p2800";Target=2800;Reference=2800;ProxyReference=$false}
)
if ($ProfileNames.Count -gt 0) {
    $profiles = @($profiles | Where-Object { $ProfileNames -contains $_.Name })
    if ($profiles.Count -eq 0) { throw "No requested profile names were found." }
}
$manifest=@()
foreach($profile in $profiles) {
    $stamp=Get-Date -Format "yyyyMMdd-HHmmss";$name="$EngineVersion-$($profile.Name)"
    $pgn=Join-Path $results "$name-$stamp.pgn";$log=Join-Path $results "$name-$stamp.log"
    $engineArgs=@("name=$name","cmd=$python","arg=$proxy","arg=--engine","arg=$engine","arg=--book","arg=$book","proto=uci",
        "option.Threads=1","option.Hash=64","option.OwnBook=false","option.SyzygyProbeLimit=0",
        "option.Strength Elo=$($profile.Target)","option.Strength Seed=20260910")
    if($profile.ProxyReference) {
        $opponentName="$EngineVersion-p$($profile.Reference)"
        $opponentArgs=@("name=$opponentName","cmd=$python","arg=$proxy","arg=--engine","arg=$engine","arg=--book","arg=$book","proto=uci",
            "option.Threads=1","option.Hash=64","option.OwnBook=false","option.SyzygyProbeLimit=0",
            "option.Strength Elo=$($profile.Reference)","option.Strength Seed=20260911")
    } else {
        $opponentName="Stockfish Elo $($profile.Reference)"
        $opponentArgs=@("name=$opponentName","cmd=$stockfish","proto=uci","option.Threads=1","option.Hash=64",
            "option.UCI_LimitStrength=true","option.UCI_Elo=$($profile.Reference)")
    }
    $arguments=@("-engine")+$engineArgs+@("-engine")+$opponentArgs+@("-each","st=$SecondsPerMove","timemargin=500",
        "-openings","file=$openings","format=epd","order=random","policy=round","-rounds",[string]($GamesPerProfile/2),
        "-games","2","-repeat","-concurrency",[string]$Concurrency,"-recover","-ratinginterval","20","-pgnout",$pgn)
    Write-Host "Calibrating $name vs ${opponentName}: $GamesPerProfile games"
    $old=$ErrorActionPreference;$ErrorActionPreference="Continue"
    try { & $cute @arguments 2>&1 | Tee-Object -FilePath $log | Out-Host;$code=$LASTEXITCODE } finally {$ErrorActionPreference=$old}
    if($code -ne 0){throw "Cute Chess failed with $code; see $log"}
    $manifest += [ordered]@{profile=$profile.Name;target=$profile.Target;anchor=$profile.Reference;reference=$opponentName;games=$GamesPerProfile;pgn=$pgn;log=$log}
    $manifest | ConvertTo-Json -Depth 4 | Set-Content (Join-Path $results "manifest.json")
}
& $python (Join-Path $PSScriptRoot "summarize_calibration.py") --manifest (Join-Path $results "manifest.json") --output (Join-Path $results "calibration.json")