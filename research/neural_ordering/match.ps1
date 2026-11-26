param(
    [ValidateSet('base','cache','board')][string]$Model='cache',
    [ValidateRange(1,32)][int]$MinDepth=4,
    [ValidateRange(2,400)][int]$Games=80,
    [string]$TimeControl='1+0.1',
    [switch]$Run
)
# This screen is NOT part of the pilot promotion decision. Default: print only.
$ErrorActionPreference='Stop'
if($Games % 2) { throw 'Use an even number of games for paired colors.' }
$root=Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$out=Join-Path $root 'testing/results/neural_ordering_pilot'
$exe=Join-Path $out 'experiment.exe'
$modelPath=Join-Path $out "models/$Model.nmo"
$cute=(Get-ChildItem (Join-Path $root 'testing/tools/cutechess') -Filter cutechess-cli.exe -Recurse | Select-Object -First 1).FullName
$openings=Join-Path $out 'match_reserved.fen'
if($Games/2 -gt (Get-Content $openings).Count) { throw 'Not enough distinct reserved pairs. Supply a larger separately frozen opening set.' }
$cache=if($Model -eq 'base') {'false'} else {'true'}
$arguments=@(
    '-engine','name=NMO candidate',"cmd=$exe",'arg=--uci','proto=uci',
      "option.NMO Model=$modelPath",'option.NMO Ordering=true',
      "option.NMO Reserve=$cache","option.NMO Record=$cache","option.NMO Read=$cache",
      "option.NMO MinDepth=$MinDepth",
    '-engine','name=Frozen ordering',"cmd=$exe",'arg=--uci','proto=uci',
    '-each',"tc=$TimeControl",'option.Hash=32','option.Threads=1','option.MultiPV=1',
      'option.OwnBook=false','option.Cutoff Policy=0','option.Move Overhead=0',
      'option.SyzygyProbeLimit=0','timemargin=100',
    '-openings',"file=$openings",'format=epd','order=random','policy=round',
    '-rounds',[string]($Games/2),'-games','2','-repeat','-srand','17417',
    '-concurrency','1','-maxmoves','200',
    '-pgnout',(Join-Path $out 'screen.pgn')
)
$manifest=@{command=$cute; arguments=$arguments; games=$Games; seed=17417;
    adjudication='No score-based or tablebase adjudication; maxmoves 200; timemargin 100 ms';
    executable=(Get-FileHash $exe).Hash; model=(Get-FileHash $modelPath).Hash;
    evaluation=(Get-FileHash (Join-Path $root 'resources/networks/nnue-8.3.bin')).Hash;
    openings=(Get-FileHash $openings).Hash; launched=[bool]$Run}
$manifest | ConvertTo-Json -Depth 5 | Write-Output
if($Run) {
    if(Test-Path (Join-Path $out 'screen.pgn')) { throw 'Refusing to overwrite an existing screen.' }
    $manifest | ConvertTo-Json -Depth 5 | Set-Content (Join-Path $out 'screen_manifest.json')
    Push-Location $root
    try { & $cute @arguments; if($LASTEXITCODE) { throw 'Match runner failed.' } }
    finally { Pop-Location }
}
