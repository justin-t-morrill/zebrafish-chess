# Reference engine tournament suite

This folder contains official open-source UCI releases and Cute Chess 1.5.1.
Run paired-opening matches from PowerShell:

```powershell
.\run_tournament.ps1 -Opponent Stockfish1320 -Games 100 -TimeControl "10+0.1"
.\run_tournament.ps1 -Opponent Stockfish1800 -Games 300 -TimeControl "10+0.1"
.\run_tournament.ps1 -Opponent Blunder -Games 200 -TimeControl "30+0.3"
.\run_tournament.ps1 -Opponent Gauntlet -Games 100 -TimeControl "10+0.1" `
    -Concurrency 6 -EngineVersion 1.5
```

Limit a gauntlet to selected opponents while retaining its combined summary:

```powershell
.\run_tournament.ps1 -Opponent Gauntlet `
    -GauntletOpponents @("Stockfish1750", "Stockfish1800", "Stockfish1850") `
    -EngineVersion 2.0 -Games 2000 -TimeControl "10+0.1" -Concurrency 6
```

`Games` is the number played against each selected opponent. Leaving out
`GauntletOpponents` runs the original full nine-opponent gauntlet.

For candidate-versus-accepted testing, the faster version runner keeps both UCI
engines alive instead of launching a process for every move:

```powershell
.\run_version_tournament.ps1 -EngineA 1.3_history -EngineB 1.3 `
    -Games 1000 -TimeControl "1+0.1" -Concurrency 4
```

Every opening is played twice with colors reversed. Version matches default to
the draw-reducing `openings\8mvs_+90_+99.epd` suite, while reference-engine
gauntlets default to the broader 34,700-position `openings\8moves_v3.epd`
suite. Both launchers accept `-OpeningFile` to select another suite and
`-Concurrency`; the gauntlet
defaults to six parallel games on this 8-core system and accepts
`-EngineVersion` to select any preserved UCI build (default: 1.7.1). The
repeatable `-GauntletOpponents` list selects a smaller calibration ladder.
For version 1.0 it automatically selects the interface-only `1.0_uci.exe`
compatibility build while retaining the original 1.0 search and evaluation.
The engine's UCI move overhead is explicitly set to zero for these local
matches; the lag reserves used by the GUI and Lichess are not applied.
PGNs, Cute Chess logs, W/D/L, p-values, confidence intervals, and Elo differences
are written or printed after each match. After a gauntlet finishes, it also
prints one consolidated table containing every opponent's W/D/L, score rate,
Elo difference and interval, two-sided p-value, likelihood of superiority, and
exact decisive-game p-value, followed by the overall game and score totals.

Available opponents:

- `Stockfish1320`, `Stockfish1600`, `Stockfish1750`, `Stockfish1800`,
  `Stockfish1850`, `Stockfish2000`, `Stockfish2100`, `Stockfish2200`,
  `Stockfish2300`, `Stockfish2400`, `Stockfish2500`, `Stockfish2600`,
  `Stockfish2700`, `Stockfish2800`, `Stockfish2900`, `Stockfish3000`, and
  `Stockfish3100`: Stockfish 18's official
  limited-strength profiles. The 1750/1800/1850 profiles provide a tighter
  calibration ladder around the engine's estimated strength. `UCI_Elo`
  is a useful calibration control, but is not guaranteed to equal a rating on
  Lichess or another pool.
- `StockfishFull`: unrestricted Stockfish 18; likely too strong for calibration.
- `Blunder`: independent native UCI engine, version 8.5.5.
- `Carballo`: independent Java UCI engine, version 1.8. Java 11+ is required.
- `Gauntlet`: runs all seven limited Stockfish profiles, Blunder, and Carballo.

For the current engine, run 200-400 games against each of Stockfish1750,
Stockfish1800, and Stockfish1850. Treat the resulting Elo as specific to this
hardware, time control, opening set, and match configuration.

For Engine 3.2's six-hour calibration run, use 1,000 games each against
Stockfish2100, Stockfish2200, Stockfish2300, and Stockfish2400 at 10+0.1 with
concurrency 6. The final summary inverse-variance weights the implied rating
from every numeric Stockfish profile and prints a combined statistical
  interval. Profile-label calibration error is systematic and is not included in
  that interval.

For a preliminary human-comparable blitz calibration of Engine 6.0, run 20
paired-opening games per opponent across the 2500--3100 Stockfish ladder at
120+1. The combined report identifies the closest profiles; use those profiles
for the larger overnight run:

```powershell
.\run_tournament.ps1 -Opponent Gauntlet `
    -GauntletOpponents @("Stockfish2500", "Stockfish2600", "Stockfish2700", `
        "Stockfish2800", "Stockfish2900", "Stockfish3000", "Stockfish3100") `
    -EngineVersion 6.0 -Games 20 -TimeControl "120+1" -Concurrency 6
```

See `SOURCES-AND-LICENSES.md` for upstream projects and licenses.
