param(
    [ValidateRange(2, 1000)][int]$GamesPerMatch = 110,
    [ValidateRange(1, 16)][int]$Concurrency = 8,
    [string]$TimeControl = "2+1",
    [string]$EngineVersion = "Current",
    [ValidateSet("Broad","Targeted")][string]$Phase = "Broad"
)
$ErrorActionPreference="Stop"
. (Join-Path $PSScriptRoot "..\tools\project_paths.ps1")
$root=Get-ChessProjectRoot
$cute=(Get-ChildItem (Join-Path $root "testing\tools\cutechess") -Recurse -Filter cutechess-cli.exe | Select-Object -First 1).FullName
$python=(Get-Command python).Source
$engine=if($EngineVersion -eq "Current"){Join-Path $root "build\current\chess.exe"}else{Get-EngineVersionPath $EngineVersion}
$proxy=Join-Path $PSScriptRoot "limited_strength_uci.py"
$book=Join-Path $root "openings\book\OpeningBook.tsv"
$openings=Join-Path $root "openings\suites\8moves_v3.epd"
$pool=Join-Path $root "testing\tools\ccrl_engines"
$stamp=Get-Date -Format "yyyyMMdd-HHmmss"
$results=Join-Path $root "testing\results\strength_calibration\ccrl_blitz-$stamp"
$statePath=Join-Path $results "manifest.json";$summaryPath=Join-Path $results "summary.json"
New-Item -ItemType Directory -Force -Path $results | Out-Null
if(($GamesPerMatch%2)-ne 0){throw "GamesPerMatch must be even."}

$blunder=Join-Path $pool "blunder_versions"
$matches=@(
    @{Profile=400; Opponent="Reduced 600"; OpponentProfile=600; Rating=$null; Path=$null},
    @{Profile=600; Opponent="Reduced 800"; OpponentProfile=800; Rating=$null; Path=$null},
    @{Profile=800; Opponent="Reduced 1000"; OpponentProfile=1000; Rating=$null; Path=$null},
    @{Profile=1000;Opponent="Reduced 1200"; OpponentProfile=1200;Rating=$null;Path=$null},
    @{Profile=1200;Opponent="Raven 0.30";Rating=1467;Path=Join-Path $pool "raven_versions\raven0.30.exe"},
    @{Profile=1500;Opponent="Raven 0.30";Rating=1467;Path=Join-Path $pool "raven_versions\raven0.30.exe"},
    @{Profile=1800;Opponent="Raven 0.40";Rating=1843;Path=Join-Path $pool "raven_versions\raven0.40.exe"},
    @{Profile=2100;Opponent="Blunder 6.1.0";Rating=2107;Path=Join-Path $blunder "blunder-6.1.0\blunder-6.1.0\windows\blunder.exe"},
    @{Profile=2400;Opponent="Blunder 7.4.0";Rating=2520;Path=Join-Path $blunder "blunder-7.4.0\blunder-7.4.0\windows\blunder-windows.exe"},
    @{Profile=2600;Opponent="Blunder 7.6.0";Rating=2619;Path=Join-Path $blunder "blunder-7.6.0\blunder-7.6.0\windows\blunder-windows.exe"},
    @{Profile=2800;Opponent="Blunder 8.5.5";Rating=2663;Path=Join-Path $pool "blunder-8.5.5-default.exe"},
    @{Profile=2800;Opponent="Jackal 1.0.0";Rating=2949;Path=Join-Path $pool "jackal-1.0.0-x86-64-v3.exe"}
)
if($Phase-eq"Targeted"){
    # Cross-check neighboring profiles against each other and reuse several
    # opponents at adjacent settings.  This separates profile-ordering defects
    # from one engine family's stylistic matchup bias.
    $matches=@(
        @{Profile=1000;Opponent="Raven 0.30";Rating=1467;Path=Join-Path $pool "raven_versions\raven0.30.exe"},
        @{Profile=1200;Opponent="Raven 0.30";Rating=1467;Path=Join-Path $pool "raven_versions\raven0.30.exe"},
        @{Profile=1200;Opponent="Reduced 1500";OpponentProfile=1500;Rating=$null;Path=$null},
        @{Profile=1500;Opponent="Raven 0.30";Rating=1467;Path=Join-Path $pool "raven_versions\raven0.30.exe"},
        @{Profile=1500;Opponent="Blunder 4.0.0";Rating=1614;Path=Join-Path $blunder "blunder-4.0.0\blunder-4.0.0\windows\blunder.exe"},
        @{Profile=1500;Opponent="Reduced 1800";OpponentProfile=1800;Rating=$null;Path=$null},
        @{Profile=1800;Opponent="Raven 0.40";Rating=1843;Path=Join-Path $pool "raven_versions\raven0.40.exe"},
        @{Profile=1800;Opponent="Blunder 4.0.0";Rating=1614;Path=Join-Path $blunder "blunder-4.0.0\blunder-4.0.0\windows\blunder.exe"},
        @{Profile=1800;Opponent="Blunder 5.0.0";Rating=2017;Path=Join-Path $blunder "blunder-5.0.0\blunder-5.0.0\windows\blunder.exe"},
        @{Profile=1800;Opponent="Reduced 2100";OpponentProfile=2100;Rating=$null;Path=$null},
        @{Profile=2100;Opponent="Raven 0.60";Rating=2152;Path=Join-Path $pool "raven_versions\raven0.60.exe"},
        @{Profile=2100;Opponent="Blunder 5.0.0";Rating=2017;Path=Join-Path $blunder "blunder-5.0.0\blunder-5.0.0\windows\blunder.exe"},
        @{Profile=2400;Opponent="Blunder 7.4.0";Rating=2520;Path=Join-Path $blunder "blunder-7.4.0\blunder-7.4.0\windows\blunder-windows.exe"},
        @{Profile=2400;Opponent="Blunder 7.6.0";Rating=2619;Path=Join-Path $blunder "blunder-7.6.0\blunder-7.6.0\windows\blunder-windows.exe"},
        @{Profile=2400;Opponent="Reduced 2600";OpponentProfile=2600;Rating=$null;Path=$null},
        @{Profile=2600;Opponent="Blunder 7.6.0";Rating=2619;Path=Join-Path $blunder "blunder-7.6.0\blunder-7.6.0\windows\blunder-windows.exe"},
        @{Profile=2600;Opponent="Blunder 8.0.0";Rating=2651;Path=Join-Path $blunder "blunder-8.0.0\blunder-8.0.0\windows\blunder-8.0.0-default.exe"},
        @{Profile=2600;Opponent="Reduced 2800";OpponentProfile=2800;Rating=$null;Path=$null},
        @{Profile=2800;Opponent="Blunder 8.5.5";Rating=2663;Path=Join-Path $pool "blunder-8.5.5-default.exe"},
        @{Profile=2800;Opponent="Jackal 1.0.0";Rating=2949;Path=Join-Path $pool "jackal-1.0.0-x86-64-v3.exe"}
    )
}
foreach($required in @($cute,$python,$engine,$proxy,$book,$openings)+@($matches|Where-Object Path|ForEach-Object Path)){
    if(-not(Test-Path -LiteralPath $required)){throw "Missing required file: $required"}
}
$state=[ordered]@{status="running";started=(Get-Date).ToString("o");engine=$EngineVersion;phase=$Phase;time_control=$TimeControl;ccrl_reference="CCRL Blitz 2+1";threads_per_engine=1;concurrency=$Concurrency;games_per_match=$GamesPerMatch;planned_games=$GamesPerMatch*$matches.Count;current="";completed=@()}
function Save-State{$state|ConvertTo-Json -Depth 7|Set-Content -LiteralPath $statePath -Encoding utf8}
function Proxy-Args($name,$elo,$seed){
    @("name=$name","cmd=$python","arg=$proxy","arg=--engine","arg=$engine","arg=--book","arg=$book","proto=uci","option.Threads=1","option.Hash=64","option.OwnBook=false","option.SyzygyProbeLimit=0","option.Strength Elo=$elo","option.Strength Seed=$seed")
}
try{
    $number=0
    foreach($m in $matches){
        $number++;$profileName="Reduced $($m.Profile)";$state.current="$profileName vs $($m.Opponent)";Save-State
        $prefix=("{0:D2}-p{1}-vs-{2}" -f $number,$m.Profile,($m.Opponent-replace '[^A-Za-z0-9.-]','_'))
        $pgn=Join-Path $results "$prefix.pgn";$log=Join-Path $results "$prefix.log"
        $a=Proxy-Args $profileName $m.Profile (20260911+$number)
        if($null-ne$m.OpponentProfile){$b=Proxy-Args $m.Opponent $m.OpponentProfile (20261911+$number)}
        else{$b=@("name=$($m.Opponent)","cmd=$($m.Path)","proto=uci")}
        $args=@("-engine")+$a+@("-engine")+$b+@("-each","tc=$TimeControl","timemargin=500","-openings","file=$openings","format=epd","order=random","policy=round","-rounds",[string]($GamesPerMatch/2),"-games","2","-repeat","-concurrency",[string]$Concurrency,"-recover","-ratinginterval","20","-pgnout",$pgn)
        Write-Host "[$number/$($matches.Count)] $profileName vs $($m.Opponent): $GamesPerMatch games at $TimeControl, concurrency $Concurrency"
        $saved=$ErrorActionPreference;$ErrorActionPreference="Continue"
        try{&$cute @args 2>&1|Tee-Object -FilePath $log|Out-Host;$code=$LASTEXITCODE}finally{$ErrorActionPreference=$saved}
        if($code-ne 0){throw "Cute Chess exited with $code; see $log"}
        $state.completed+= [ordered]@{profile=$m.Profile;engine_name=$profileName;opponent=$m.Opponent;opponent_rating=$m.Rating;opponent_profile=$m.OpponentProfile;games=$GamesPerMatch;pgn=$pgn;log=$log}
        Save-State
        &$python (Join-Path $PSScriptRoot "summarize_ccrl_blitz.py") $statePath --output $summaryPath|Out-Host
    }
    $state.status="complete";$state.current="";$state.finished=(Get-Date).ToString("o");Save-State
}catch{$state.status="failed";$state.error=$_.Exception.Message;$state.finished=(Get-Date).ToString("o");Save-State;throw}
