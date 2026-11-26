param([switch]$Baseline, [switch]$Verify, [switch]$Scalar)
$ErrorActionPreference='Stop'
$root=Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
Push-Location $root
try {
    $out='local/results/neural_ordering_pilot'
    New-Item -ItemType Directory -Force $out | Out-Null
    $flags=@('-std=c11','-O3','-march=native','-flto','-DNDEBUG','-Ithird_party/fathom')
    $name='experiment'
    if($Baseline) { $flags+='-DNMO_BASELINE'; $name='baseline_driver' }
    if($Verify) { $flags+=@('-DINCREMENTAL_VERIFY','-DBITBOARD_VERIFY'); $name='verify' }
    if($Scalar) { $flags+='-fno-tree-vectorize'; $name='scalar' }
    if(!(Test-Path "$out/tbprobe.o")) {
        & gcc -std=c11 -O3 -march=native -DNDEBUG -Ithird_party/fathom -c third_party/fathom/tbprobe.c -o "$out/tbprobe.o"
        if($LASTEXITCODE) { throw 'Fathom build failed' }
    }
    & gcc @flags research/neural_ordering/driver.c "$out/tbprobe.o" -o "$out/$name.exe" -lgdiplus -lgdi32 -luser32 -lcomctl32 -luxtheme -lm
    if($LASTEXITCODE) { throw 'Driver build failed' }
    (@{flags=$flags; executable="$out/$name.exe"; source='research/neural_ordering/driver.c'; sha256=(Get-FileHash "$out/$name.exe").Hash} | ConvertTo-Json) | Set-Content "$out/build_$name.json"
} finally { Pop-Location }
