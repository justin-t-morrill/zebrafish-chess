# Lichess opening data

`lichess-chess-openings/` is a snapshot of the CC0
[`lichess-org/chess-openings`](https://github.com/lichess-org/chess-openings)
repository. It is retained so the generated engine data can be reproduced.

Regenerate the files from the repository root with:

```powershell
& .\lichess-bot\.venv\bin\python.exe .\opening_data\build_lichess_book.py `
    --source .\opening_data\lichess-chess-openings `
    --book .\opening_data\OpeningBook.tsv `
    --names .\opening_data\OpeningNames.tsv
```

`OpeningBook.tsv` contains one unique position/move pair per row. The `weight`
column is currently `1` for every move, so selection is uniform among the
available moves. Changing positive integer weights changes the relative move
probabilities without rebuilding the C engine. `OpeningNames.tsv` separately
contains the ECO/name classification for each named position.

## Evaluate and weight the book

`weight_opening_book.py` runs Stockfish and the project engine on the resulting
position after every candidate move. Stockfish alone rejects objectively weak
moves; the surviving moves are weighted using 75% Stockfish loss and 25% engine
loss by default. The exponential weighting gives a move losing 35 centipawns
roughly 37% of the maximum weight. A move at least 80 centipawns behind
Stockfish's best candidate gets weight zero. To prevent obscure named sidelines
from entering the playable repertoire merely because they exist in the ECO
source, a move with fewer than five supporting database games is also given
weight zero when it is at least 25 centipawns behind Stockfish's best move.
Finally, an absolute guard prevents individually tolerable losses from
accumulating into a bad book position. It is centered on Stockfish's roughly
`+0.50` starting evaluation rather than zero: White leaves book below `-0.40`,
and Black leaves book above `+1.40`. These limits can be changed with
`--white-eval-floor` and `--black-eval-ceiling`.

Zero-weight rows are deliberately preserved. The engine will never select the
move itself, but can still recognize its opening name and use book replies if
an opponent plays it.

Run the default six-worker analysis and install the result with:

```powershell
& .\lichess-bot\.venv\bin\python.exe .\opening_data\weight_opening_book.py `
    --workers 6 `
    --install .\engine_versions\OpeningBook.tsv
```

The defaults use Stockfish depth 14 and engine depth 8. Analysis is cached by
child position in `opening_evaluations.json`; interrupted runs resume. The cache
also records both executable identities and depths, and refuses incompatible
reuse. Weighting parameters such as `--weak-threshold`, `--temperature`, and
`--stockfish-share` can be changed instantly using the completed evaluation
cache. Run with `--help` for every option.

## Broadcast-game extension

`broadcast_database/` contains the August 2025 through July 2026 monthly files
from the official Lichess broadcast database. The 384,608 downloaded games are
licensed CC BY-SA 4.0; 357,538 valid standard games were accepted. Malformed,
incomplete, non-standard, and incorrectly labelled Chess960 records were
excluded.

`extend_book_from_pgn.py` aggregates play through ply 24 and keeps a database
continuation when its position occurred at least 20 times, the move occurred at
least five times, and its conditional frequency was at least 2%. All original
named and weight-zero branches remain reachable. The resulting 61,560 moves are
then passed through `weight_opening_book.py`: Stockfish retains veto authority,
while evaluation, frequency, and lightly smoothed mover WDL performance set the
positive weights.

The installed extended book has 58,533 selectable moves and 3,027 retained
zero-weight moves. Of those rejections, 444 are rare lines that fell at least
25 centipawns behind Stockfish's best candidate, and another 1,303 crossed the
absolute evaluation guard. Rebuild its raw candidates with:

```powershell
& .\lichess-bot\.venv\bin\python.exe .\opening_data\extend_book_from_pgn.py
```
