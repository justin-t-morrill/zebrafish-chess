param(
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
$proxy=Join-Path $PSScriptRoot "limited_strength_uci.py"
$book=Join-Path $root "resources\books\OpeningBook.tsv"
$general=Join-Path $root "tests\fixtures\openings\8moves_v3.epd"
$suiteDir=Join-Path $PSScriptRoot "skill_suites"
$stamp=Get-Date -Format "yyyyMMdd-HHmmss"
$results=Join-Path $root "local\results\strength_calibration\skill-response-$stamp"
New-Item -ItemType Directory -Force -Path $results|Out-Null
$manifest=Join-Path $results "manifest.json"

function P($name,$overall,$t=0,$p=0,$d=0,$e=0){
    [ordered]@{Name=$name;Overall=$overall;T=$t;P=$p;D=$d;E=$e}
}
function Skill-Profile($skill,$rating){
    $p=P "$skill $rating" 1500 1500 1500 1500 1500
    if($skill-eq"tactics"){$p.T=$rating}
    elseif($skill-eq"positional"){$p.P=$rating}
    elseif($skill-eq"defense"){$p.D=$rating}
    else{$p.E=$rating}
    $p
}
function Engine-Args($profile,$seed){
    @("name=$($profile.Name)","cmd=$python","arg=$proxy","arg=--engine","arg=$engine",
      "arg=--book","arg=$book","proto=uci","option.Threads=1","option.Hash=64",
      "option.OwnBook=false","option.SyzygyProbeLimit=0","option.Strength Calibration=candidate",
      "option.Strength Elo=$($profile.Overall)","option.Strength Tactics Elo=$($profile.T)",
      "option.Strength Positional Elo=$($profile.P)","option.Strength Defense Elo=$($profile.D)",
      "option.Strength Endgame Elo=$($profile.E)","option.Strength Seed=$seed")
}

$balanced=P "Balanced 1500" 1500
$skills=@("tactics","positional","defense","endgame")
$ratings=@(900,1200,1800,2100)
$matches=@()
foreach($skill in $skills){
    foreach($rating in $ratings){
        $matches+=,@{A=(Skill-Profile $skill $rating);B=$balanced;Games=160;
            Suite=(Join-Path $suiteDir "$skill.epd");Kind="response";
            ControlledSkill=$skill;SuiteSkill=$skill;RequestedElo=$rating}
        $matches+=,@{A=(Skill-Profile $skill $rating);B=$balanced;Games=60;
            Suite=$general;Kind="held_out_general";ControlledSkill=$skill;
            SuiteSkill="general";RequestedElo=$rating}
    }
    foreach($other in $skills){
        if($other-ne$skill){
            $matches+=,@{A=(Skill-Profile $skill 900);B=$balanced;Games=40;
                Suite=(Join-Path $suiteDir "$other.epd");Kind="leakage";
                ControlledSkill=$skill;SuiteSkill=$other;RequestedElo=900}
        }
    }
}
$planned=0
foreach($match in $matches){$planned += [int]$match.Games}
$state=[ordered]@{status="running";started=(Get-Date).ToString("o");time_control=$TimeControl;
    concurrency=$Concurrency;planned_games=$planned;current="";completed=@()}
function Save-State{$state|ConvertTo-Json -Depth 8|Set-Content -LiteralPath $manifest -Encoding utf8}

try{
    $i=0
    foreach($m in $matches){
        $i++
        $state.current="$($m.A.Name) vs Balanced 1500 ($($m.Kind), $($m.SuiteSkill))"
        Save-State
        $prefix=("{0:D2}-{1}-{2}-{3}"-f$i,$m.ControlledSkill,$m.RequestedElo,$m.Kind)
        if($m.Kind-eq"leakage"){$prefix+="-$($m.SuiteSkill)"}
        $pgn=Join-Path $results "$prefix.pgn";$log=Join-Path $results "$prefix.log"
        $args=@("-engine")+(Engine-Args $m.A (20300913+$i))+@("-engine")+
          (Engine-Args $m.B (20400913+$i))+@("-each","tc=$TimeControl","timemargin=500",
          "-openings","file=$($m.Suite)","format=epd","order=random","policy=round",
          "-rounds",[string]($m.Games/2),"-games","2","-repeat","-concurrency",
          [string]$Concurrency,"-recover","-ratinginterval","40","-pgnout",$pgn)
        Write-Host "[$i/$($matches.Count)] $($state.current): $($m.Games) games"
        $saved=$ErrorActionPreference;$ErrorActionPreference="Continue"
        try{&$cute @args 2>&1|Tee-Object -FilePath $log|Out-Host;$code=$LASTEXITCODE}
        finally{$ErrorActionPreference=$saved}
        if($code-ne 0){throw "Cute Chess exited with $code; see $log"}
        $state.completed+=@{a_name=$m.A.Name;b_name=$m.B.Name;kind=$m.Kind;
            controlled_skill=$m.ControlledSkill;suite_skill=$m.SuiteSkill;
            requested_elo=$m.RequestedElo;games=$m.Games;suite=$m.Suite;pgn=$pgn;log=$log}
        Save-State
        &$python (Join-Path $PSScriptRoot "summarize_skill_calibration.py") $manifest `
          --output (Join-Path $results "summary.json")|Out-Host
    }
    $state.status="complete";$state.current="";$state.finished=(Get-Date).ToString("o");Save-State
    &$python (Join-Path $PSScriptRoot "fit_skill_response.py") `
      (Join-Path $results "summary.json") --output (Join-Path $results "response_fit.json")|Out-Host
}catch{
    $state.status="failed";$state.error=$_.Exception.Message;$state.finished=(Get-Date).ToString("o");Save-State
    throw
}
