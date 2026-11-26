param(
    [ValidateSet("Smoke","Full","Validate")][string]$Stage="Full",
    [ValidateRange(1,16)][int]$Concurrency=8,
    [string]$TimeControl="2+1",
    [string]$EngineVersion="Current"
)
$ErrorActionPreference="Stop"
. (Join-Path $PSScriptRoot "..\tools\project_paths.ps1")
$root=Get-ChessProjectRoot
$cute=(Get-ChildItem (Join-Path $root "local\tools\cutechess") -Recurse -Filter cutechess-cli.exe|Select-Object -First 1).FullName
$python=(Get-Command python).Source
$engine=if($EngineVersion-eq"Current"){Join-Path $root "build\current\chess.exe"}else{Get-EngineVersionPath $EngineVersion}
$proxy=Join-Path $PSScriptRoot "limited_strength_uci.py";$book=Join-Path $root "resources\books\OpeningBook.tsv"
$general=Join-Path $root "tests\fixtures\openings\8moves_v3.epd";$suiteDir=Join-Path $PSScriptRoot "skill_suites"
$pool=Join-Path $root "local\tools\ccrl_engines"
$raven030=Join-Path $pool "raven_versions\raven0.30.exe"
$blunder40=Join-Path $pool "blunder_versions\blunder-4.0.0\blunder-4.0.0\windows\blunder.exe"
if(-not(Test-Path (Join-Path $suiteDir "tactics.epd"))){&$python (Join-Path $PSScriptRoot "build_skill_suites.py") $general $suiteDir --per-category 5000;if($LASTEXITCODE-ne 0){throw "Suite generation failed"}}
$stamp=Get-Date -Format "yyyyMMdd-HHmmss";$results=Join-Path $root "local\results\strength_calibration\skills-$stamp"
New-Item -ItemType Directory -Force -Path $results|Out-Null;$manifest=Join-Path $results "manifest.json"
function P($name,$overall,$t=0,$p=0,$d=0,$e=0){[ordered]@{Name=$name;Overall=$overall;T=$t;P=$p;D=$d;E=$e}}
$balanced=P "Balanced 1500" 1500
$weak=@{tactics=(P "Tactics 900" 1500 900 1500 1500 1500);positional=(P "Positional 900" 1500 1500 900 1500 1500);defense=(P "Defense 900" 1500 1500 1500 900 1500);endgame=(P "Endgame 900" 1500 1500 1500 1500 900)}
$matches=@()
if($Stage-eq"Smoke"){
    foreach($skill in @("tactics","positional","defense","endgame")){$matches+=,@{A=$weak[$skill];B=$balanced;Games=8;Suite=Join-Path $suiteDir "$skill.epd";Kind="smoke"}}
}elseif($Stage-eq"Validate"){
    foreach($skill in @("tactics","positional","defense","endgame"))
        {$matches+=,@{A=$weak[$skill];B=$balanced;Games=100;Suite=$general;Kind="held_out_general"}}
}else{
    foreach($skill in @("tactics","positional","defense","endgame")){
        $matches+=,@{A=$weak[$skill];B=$balanced;Games=100;Suite=Join-Path $suiteDir "$skill.epd";Kind="sensitivity"}
        foreach($rating in @(1000,1200)){$matches+=,@{A=$weak[$skill];B=(P "Balanced $rating" $rating);Games=80;Suite=Join-Path $suiteDir "$skill.epd";Kind="calibration"}}
        $matches+=,@{A=$weak[$skill];B=$null;ExternalName="Raven 0.30";ExternalPath=$raven030;ExternalRating=1467;Games=80;Suite=Join-Path $suiteDir "$skill.epd";Kind="absolute"}
    }
    $matches+=,@{A=$balanced;B=$null;ExternalName="Raven 0.30";ExternalPath=$raven030;ExternalRating=1467;Games=80;Suite=$general;Kind="control"}
    $matches+=,@{A=$balanced;B=$null;ExternalName="Blunder 4.0";ExternalPath=$blunder40;ExternalRating=1614;Games=80;Suite=$general;Kind="control"}
    $pairs=@(@("tactics","positional"),@("tactics","defense"),@("positional","endgame"),@("defense","endgame"))
    foreach($pair in $pairs){$matches+=,@{A=$weak[$pair[0]];B=$weak[$pair[1]];Games=100;Suite=$general;Kind="cross"}}
}
$state=[ordered]@{status="running";started=(Get-Date).ToString("o");stage=$Stage;time_control=$TimeControl;concurrency=$Concurrency;planned_games=($matches|Measure-Object Games -Sum).Sum;current="";completed=@()}
function Save-State{$state|ConvertTo-Json -Depth 8|Set-Content -LiteralPath $manifest -Encoding utf8}
function Engine-Args($profile,$seed){
    @("name=$($profile.Name)","cmd=$python","arg=$proxy","arg=--engine","arg=$engine","arg=--book","arg=$book","proto=uci","option.Threads=1","option.Hash=64","option.OwnBook=false","option.SyzygyProbeLimit=0","option.Strength Calibration=candidate","option.Strength Elo=$($profile.Overall)","option.Strength Tactics Elo=$($profile.T)","option.Strength Positional Elo=$($profile.P)","option.Strength Defense Elo=$($profile.D)","option.Strength Endgame Elo=$($profile.E)","option.Strength Seed=$seed")
}
try{
 $i=0;foreach($m in $matches){$i++;$bName=if($m.B){$m.B.Name}else{$m.ExternalName};$state.current="$($m.A.Name) vs $bName";Save-State
  $prefix=("{0:D2}-{1}-vs-{2}"-f$i,($m.A.Name-replace'[^A-Za-z0-9]','_'),($bName-replace'[^A-Za-z0-9]','_'))
  $pgn=Join-Path $results "$prefix.pgn";$log=Join-Path $results "$prefix.log"
  $bArgs=if($m.B){Engine-Args $m.B (20270912+$i)}else{@("name=$bName","cmd=$($m.ExternalPath)","proto=uci")}
  $args=@("-engine")+(Engine-Args $m.A (20260912+$i))+@("-engine")+$bArgs+@("-each","tc=$TimeControl","timemargin=500","-openings","file=$($m.Suite)","format=epd","order=random","policy=round","-rounds",[string]($m.Games/2),"-games","2","-repeat","-concurrency",[string]$Concurrency,"-recover","-ratinginterval","20","-pgnout",$pgn)
  Write-Host "[$i/$($matches.Count)] $($state.current): $($m.Games) games"
  $saved=$ErrorActionPreference;$ErrorActionPreference="Continue";try{&$cute @args 2>&1|Tee-Object -FilePath $log|Out-Host;$code=$LASTEXITCODE}finally{$ErrorActionPreference=$saved}
  if($code-ne 0){throw "Cute Chess exited with $code; see $log"}
  $state.completed+=@{a_name=$m.A.Name;b_name=$bName;opponent_rating=$m.ExternalRating;kind=$m.Kind;games=$m.Games;suite=$m.Suite;pgn=$pgn;log=$log};Save-State
  &$python (Join-Path $PSScriptRoot "summarize_skill_calibration.py") $manifest --output (Join-Path $results "summary.json")|Out-Host
 }
 $state.status="complete";$state.current="";$state.finished=(Get-Date).ToString("o");Save-State
}catch{$state.status="failed";$state.error=$_.Exception.Message;$state.finished=(Get-Date).ToString("o");Save-State;throw}
