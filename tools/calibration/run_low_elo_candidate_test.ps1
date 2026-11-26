param(
    [ValidateRange(2,1000)][int]$GamesPerProfile=100,
    [ValidateRange(1,16)][int]$Concurrency=8,
    [string]$TimeControl="2+1",
    [ValidateRange(400,700)][int[]]$Profiles=@(400,500,600,700)
)
$ErrorActionPreference="Stop"
. (Join-Path $PSScriptRoot "..\tools\project_paths.ps1")
$root=Get-ChessProjectRoot;$cute=(Get-ChildItem (Join-Path $root "local\tools\cutechess") -Recurse -Filter cutechess-cli.exe|Select-Object -First 1).FullName
$python=(Get-Command python).Source;$engine=Join-Path $root "build\current\chess.exe";$proxy=Join-Path $PSScriptRoot "limited_strength_uci.py";$book=Join-Path $root "resources\books\OpeningBook.tsv";$openings=Join-Path $root "tests\fixtures\openings\8moves_v3.epd"
$stamp=Get-Date -Format "yyyyMMdd-HHmmss";$results=Join-Path $root "local\results\strength_calibration\low_candidates-$stamp";New-Item -ItemType Directory -Force -Path $results|Out-Null
if($GamesPerProfile%2){throw "GamesPerProfile must be even."}
$manifest=[ordered]@{status="running";started=(Get-Date).ToString("o");time_control=$TimeControl;anchor_profile=400;anchor_estimated_ccrl=695;planned_games=$Profiles.Count*$GamesPerProfile;current="";completed=@()};$manifestPath=Join-Path $results "manifest.json"
function Save{$manifest|ConvertTo-Json -Depth 6|Set-Content $manifestPath -Encoding utf8}
function ProxyArgs($name,$elo,$model,$seed){@("name=$name","cmd=$python","arg=$proxy","arg=--engine","arg=$engine","arg=--book","arg=$book","proto=uci","option.Threads=1","option.Hash=64","option.OwnBook=false","option.SyzygyProbeLimit=0","option.Strength Elo=$elo","option.Strength Calibration=$model","option.Strength Seed=$seed")}
try{
  $i=0
  foreach($target in $Profiles){
    $i++;$aName="Candidate $target";$bName="Legacy 400";$manifest.current="$aName vs $bName";Save
    $pgn=Join-Path $results ("{0:D2}-candidate-{1}.pgn"-f$i,$target);$log=Join-Path $results ("{0:D2}-candidate-{1}.log"-f$i,$target)
    $args=@("-engine")+(ProxyArgs $aName $target "candidate" (20261000+$i))+@("-engine")+(ProxyArgs $bName 400 "legacy" (20262000+$i))+@("-each","tc=$TimeControl","timemargin=500","-openings","file=$openings","format=epd","order=random","policy=round","-rounds",[string]($GamesPerProfile/2),"-games","2","-repeat","-concurrency",[string]$Concurrency,"-recover","-ratinginterval","20","-pgnout",$pgn)
    Write-Host "[$i/$($Profiles.Count)] $aName vs ${bName}: $GamesPerProfile games"
    $saved=$ErrorActionPreference;$ErrorActionPreference="Continue";try{&$cute @args 2>&1|Tee-Object -FilePath $log|Out-Host;$code=$LASTEXITCODE}finally{$ErrorActionPreference=$saved}
    if($code-ne 0){throw "Cute Chess exited with $code; see $log"}
    $manifest.completed+=[ordered]@{profile=$target;engine_name=$aName;opponent=$bName;opponent_rating=695;opponent_profile=$null;games=$GamesPerProfile;pgn=$pgn;log=$log};Save
    &$python (Join-Path $PSScriptRoot "summarize_ccrl_blitz.py") $manifestPath --output (Join-Path $results "summary.json")|Out-Host
  }
  $manifest.status="complete";$manifest.current="";$manifest.finished=(Get-Date).ToString("o");Save
}catch{$manifest.status="failed";$manifest.error=$_.Exception.Message;Save;throw}
