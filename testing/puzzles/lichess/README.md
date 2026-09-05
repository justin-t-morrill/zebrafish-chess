# Puzzle regression tests

This directory builds a reproducible, themed sample of the official Lichess
puzzle database and tests versioned UCI engines against it. Puzzle results are
diagnostics, not an Elo measurement; SPRT remains the acceptance test.

## Create the suite

From the project directory:

```powershell
.\puzzle_tests\download_lichess_suite.ps1
```

The compressed source database is retained in `puzzle_tests/data`, so changing
the sample size or filters does not download it again. The default is up to
2,000 positions from each of 15 strategically useful themes. Sampling uses a
fixed seed and quality filters for repeatability. Opening, mate-in-one, and
one-move puzzles are excluded because they add little diagnostic value here.

## Compare engines

```powershell
.\puzzle_tests\run_puzzle_test.ps1 `
    -Engine 6.1,6.1_pawn_details_texel_v2 `
    -MoveTime 100
```

For a quick smoke test, add `-MaximumPuzzles 500`. Detailed CSV files are put
in `puzzle_tests/results`, and the terminal shows overall/theme solve rates and
the number of puzzles gained or lost relative to the first engine.

The Lichess FEN is the position before the mistake. The runner correctly plays
the first recorded move, then asks the engine to find the second recorded move.
It currently scores the first solution move exactly. Equivalent moves can make
this conservative; inspect gained/lost cases before drawing conclusions.

For failures, use the forced root-move analyzer documented in
[`DIAGNOSTICS.md`](DIAGNOSTICS.md). It compares the recorded and played moves at
several fixed depths and independently verifies both with Stockfish.

For a broad completed run, first rank the errors and prepare follow-up suites:

```powershell
python .\puzzle_tests\analyze_puzzle_results.py `
    .\puzzle_tests\results\6.2-puzzles-YYYYMMDD-HHMMSS.csv
```

This writes a Markdown report, a source-format CSV containing every failure
for a slower rerun, and a theme-balanced sample for root diagnostics.
