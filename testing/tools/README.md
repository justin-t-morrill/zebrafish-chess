# Zebrafish tournament tools

This directory contains match launchers and result-analysis scripts. Cute Chess,
Stockfish, Blunder, Carballo, and other downloaded engine binaries are excluded
from Git. Install the required tools into the paths used by the selected script
before running it. See `SOURCES-AND-LICENSES.md` for recorded upstream sources.
Carballo requires Java; the launchers require PowerShell.

## Prepare engine binaries

Build the current engine with `engine/current/build.ps1` from the repository
root. The version launchers resolve numbered executables under
`engines/versions/v<major>/<version>.exe`; source snapshots alone are not enough.
For the current 8.3 build, copy the generated executable and matching network:

```powershell
Copy-Item .\engine\current\chess.exe .\engines\versions\v8\8.3.exe
Copy-Item .\engine\current\nnue-8.3.bin .\engines\versions\v8\nnue-8.3.bin
```

Historical versions require their own builds and matching runtime resources.
The retained releases are 1.7.1, 2.3, 3.5, 4.1, 5.7, 6.4, 7.3, and 8.3.

## Reference matches

Run from the repository root after installing the external tools:

```powershell
.\testing\tools\run_tournament.ps1 -Opponent Blunder `
    -EngineVersion 8.3 -Games 200 -TimeControl "30+0.3" -Concurrency 1
```

Always specify `-EngineVersion`: the script's historical default is 1.7.1.
`-Opponent` supports Blunder, Carballo, StockfishFull, the numeric Stockfish
profiles listed in the script's parameter block, and Gauntlet. Use
`-GauntletOpponents` to select a subset. `-Games` is per opponent and must be
even for paired colors. Set thread counts and concurrency to suit your machine.

## Version comparisons

After building both versions:

```powershell
.\testing\tools\run_version_tournament.ps1 -EngineA 8.3 -EngineB 7.3 `
    -Games 1000 -TimeControl "1+0.1" -Concurrency 1
```

`run_version_sprt.ps1` provides sequential acceptance testing. Use each
script's parameter block for its supported options. Opening suites live under
`openings/suites/`; `-OpeningFile` overrides the default. Results are generated
under `testing/results/` and excluded from Git.

## Interpreting results

Paired colors reduce opening bias. Match Elo differences and their intervals
apply to the tested settings; limited-strength Stockfish profile labels are not
guaranteed to match human ratings. For the current 8.3 estimate and the direct
CCRL calibration conditions, consult `engines/ELO_HISTORY.md` from the root.
The recorded estimate is about 3110 on the CCRL Blitz scale with 8 threads,
with approximately ±60 practical uncertainty; it is a local estimate, not an
official listing.
