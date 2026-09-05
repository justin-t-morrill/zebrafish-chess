# Chess engine workspace

This directory is the organized home of the chess engine, its historical
versions, test infrastructure, training data, opening resources, tablebases,
GUI assets, and external integrations.

## Layout

- `engine/current/` — current accepted source, `chess.exe`, `chess_gui.exe`,
  NNUE network, and build script.
- `engines/versions/v1/` through `v8/` — historical executables and matching
  `source_<version>` snapshots. `engines/ELO_HISTORY.md` records estimates and
  accepted changes.
- `testing/tools/` — Cute Chess, reference engines, tournament launchers, and
  PGN analysis tools.
- `testing/results/sprt/`, `tournaments/`, and `gauntlets/` — results grouped
  again by the tested engine's major version.
- `testing/puzzles/` and `testing/runtime/` — tactical diagnostics and runtime
  profiles.
- `analysis/game_review/` — isolated game-review schema, stability tracking,
  scoring, annotated-PGN, and future engine/GUI integration.
- `training/tuning/` and `training/nnue/` — Texel/SPSA tooling and datasets,
  plus NNUE training code and data.
- `openings/book/`, `openings/suites/`, and `openings/data/` — runtime opening
  book, test suites, and source/weighting data.
- `endgames/syzygy/` and `endgames/fathom/` — tablebase files and probe code.
- `gui/assets/` — piece images.
- `integrations/lichess-bot/` — Lichess bridge and configuration.
- `archive/` — preserved legacy builds, caches, duplicate resources, and the
  one-time migration script.

## Common commands

Run the current text engine:

```powershell
.\engine\current\chess.exe
```

Run the GUI:

```powershell
.\engine\current\chess_gui.exe
```

Rebuild the accepted engine and GUI:

```powershell
.\engine\current\build.ps1
```

Run an SPRT between saved versions:

```powershell
.\testing\tools\run_version_sprt.ps1 `
    -EngineA 8.0_search_spsa `
    -EngineB 8.0 `
    -MaxGames 10000 `
    -TimeControl "3+0.03" `
    -Concurrency 6 `
    -ThreadsA 1 `
    -ThreadsB 1 `
    -Elo0 0 `
    -Elo1 10
```

New SPRT, tournament, and gauntlet results are automatically placed in the
appropriate test-type and major-version directory. Engine lookup is likewise
automatic from the version name.

Start the Lichess bridge from its own directory:

```powershell
Set-Location .\integrations\lichess-bot
.\run-bot.ps1
```

The bridge points to `engine/current/chess.exe`, so replacing the accepted
current build updates Lichess without changing `config.yml`.
