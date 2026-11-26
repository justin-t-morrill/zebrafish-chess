# Root-move diagnostic tool

The puzzle runner tells you whether an engine selected the recorded solution.
The root-move diagnostic tool answers the more useful follow-up question:
**why did it prefer another move?**

It forces the engine to search both the recorded solution and the move that it
actually played. It repeats those searches at selected fixed depths and asks
full-strength Stockfish to search both moves independently. Results are saved
as a detailed CSV and a readable Markdown report.

## Basic command

Run this from the project directory:

```powershell
.\puzzle_tests\run_root_diagnostics.ps1 `
    -Results .\puzzle_tests\results\6.2-puzzles-20260831-141416.csv `
    -Engine 6.2 `
    -Depths 6,8,10,12,14 `
    -OnlyFailed `
    -StockfishDepth 22
```

`-Results` must be a detailed CSV created by `run_puzzles.py`. It contains the
FEN, Lichess setup move, recorded solution, and engine move. `-Engine` selects
the preserved source directory and does not modify the accepted executable.

Useful options:

- `-OnlyFailed` analyzes rows whose `Solved` field is false.
- `-MaximumPositions 5` limits a diagnostic run for a quick check.
- `-Depths 6,8,10,12,14` controls the engine's forced fixed-depth searches.
- `-StockfishDepth 22` controls the independent reference search.

Search cost grows exponentially. Start with depths through 12 or 14. Use depth
16 or greater only for a small set of unresolved positions.

## What is measured

For each position and depth, the probe starts with a fresh transposition table,
history table, and search context. It then performs a full-window search after
forcing exactly one root move. This produces:

- `Score`: search score from the puzzle solver's perspective.
- `StaticBefore`: static evaluation before either candidate move.
- `StaticAfter`: static evaluation immediately after the forced move, converted
  back to the original side's perspective.
- `Nodes` and `QNodes`: ordinary and quiescence nodes under that move.
- `PV`: principal variation found under the forced move.

The Markdown report shows `recorded score - played score` as **Delta**:

- Positive: at that depth, the engine agrees that the recorded move is better.
- Negative: at that depth, the engine still prefers its originally played move.
- Near zero: the engine considers the moves approximately equal at that depth.

Stockfish is also forced to search each move. This avoids confusing
Stockfish's unrestricted best move with the actual value of the two moves being
compared.

## Interpreting common patterns

### Search horizon

The delta begins negative but becomes positive as depth increases. The engine's
evaluation/search can recognize the solution once it reaches the required
horizon; the timed root search simply did not reach it reliably.

Typical remedies are better move ordering, selective extensions, reductions
that protect critical moves, or improved time allocation—not new static terms.

### Evaluation disagreement

The engine searches both moves deeply and consistently prefers the wrong one,
while Stockfish shows a large stable advantage for the recorded move. If the
important benefit lies beyond the tested horizon, this can still be search. An
evaluation problem becomes more likely when the decisive positional benefit is
already visible after the move but `StaticAfter` strongly favors the wrong move.

### Root search/time problem

The forced search gives the recorded move a clearly higher score at a depth the
ordinary timed search should often reach, yet the engine did not play it. This
points to root ordering, incomplete iterations, aspiration behavior, or uneven
time distribution between root moves.

### Equivalent or ambiguous solution

Both the engine and Stockfish score the moves within roughly 20 centipawns.
Lichess stores one solution line, so exact-match puzzle scoring can mark a sound
alternative as wrong.

## Important limitations

- A forced full-window search is deliberately cleaner than the real timed root
  search. It does not reproduce aspiration windows, root ordering, or timeout
  effects; those differences are precisely what make it diagnostic.
- A higher fixed-depth score is the engine's opinion, not proof of chess truth.
  The Stockfish comparison provides the independent reference.
- Puzzle solutions emphasize tactics and conversion. Puzzle accuracy is not an
  Elo estimate and should not replace SPRT.
- Scores around forced mates are represented internally by large values rather
  than ordinary centipawns.

Output files are written to `puzzle_tests\diagnostics`. The CSV is intended for
filtering and plotting; the Markdown report is intended for position-by-position
reading.
