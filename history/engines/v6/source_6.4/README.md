# Zebrafish 6.4 — historical source snapshot

This directory preserves accepted version **6.4**. The current release is
8.3; see the [repository README](../../../../README.md) for current setup and
[development ratings](../../../ELO_HISTORY.md) for version-specific evidence.
Only source is retained here. Executables, local experiment data, and older
intermediate snapshots mentioned below are not included.

## Using this snapshot

This snapshot retains its original source layout and internal version labels.
Older build scripts and resource paths can depend on the original workspace;
they are not the current release's supported build entry point. For playing
or analysis, build `engine/current/` using the root instructions. Rebuilding a
historical version requires checking its includes and resource paths, linking
Fathom if it uses Syzygy, and supplying matching NNUE weights if applicable.
For 8.3, the matching weights are in `engine/current/nnue-8.3.bin`.

## Archived development notes

The following notes are historical records, including references to earlier
accepted builds and experiments. Commands using `engine_versions`, `tuning`,
or `run_tournament.ps1` refer to the old workspace, not fresh-checkout paths.


Accepted Engine 6.2 extends Engine 6.1 with cached isolated,
supported, phalanx, candidate-passer, protected-passer, connected-passer, and
outside-passer recognition. Dynamic terms distinguish blocked, safe, and
clear-path passers; compare both kings with the next advance square; and score
friendly or enemy rooks behind a passer. All 34 MG/EG coefficients are exposed
through the `pawn_details` Texel group and automatically included in `all`.
Its 3+0.03 SPRT against Engine 6.1 accepted H1 after 1,239 completed games:
518 wins, 299 draws, and 422 losses, measuring +26.97 Elo with a 95% interval
of +10.13 to +43.94.

Accepted version 6.0 adds phase-tapered threat evaluation to Engine 5.7. It
recognizes pawn pressure on more valuable pieces, minor-piece
pressure on rooks and queens, rook pressure on queens, and attacked targets
that have no pseudo-legal defender. The implementation reuses attack maps
already built for mobility and king safety, and all twenty MG/EG coefficients
are exported through the Texel tuner's `threats` and `all` groups.

Accepted version 5.7 replaces Engine 5.6's coarse LMR adjustments with a
multi-signal schedule. PV and improving nodes reduce less; weak non-PV nodes
may reduce genuinely late quiets more; butterfly history supplies graded
positive and negative adjustments. Checks, castling, hash moves, killers, and
check evasions remain unreduced, and every reduced alpha-raising move still
receives mandatory full-depth verification.

Its SPRT against Engine 5.6 accepted H1 after 5,412 completed games: 1,965
wins, 1,632 draws, and 1,815 losses, measuring +9.6 Elo with a reported +/-7.7
interval and 99.3% likelihood of superiority.

Accepted version 5.6 adds a two-ply improving heuristic and conservative
late-move pruning to Engine 5.5. At shallow scout nodes, sufficiently
late low-history quiet moves may be skipped; improving nodes get a larger move
allowance, and checking moves, castling, hash/killer moves, pawn-only endings,
null branches, and singular verification searches are protected.

Its SPRT against Engine 5.5 accepted H1 after 377 completed games: 174 wins,
107 draws, and 96 losses, measuring +72.9 Elo with a reported +/-30.1 interval
and 100.0% likelihood of superiority.

Accepted version 5.5 starts from version 5.4 and adds a narrow
tactical ProbCut at scout nodes. Captures and promotions must pass both a
raised-beta qsearch and a reduced verification search before the node is
pruned. Recursive ProbCut, check nodes, PV nodes, singular verification nodes,
and mate-score regions are excluded.

Its SPRT against Engine 5.4 accepted H1 after 3,355 completed games: 1,241
wins, 994 draws, and 1,120 losses, measuring +12.5 Elo with a reported +/-9.9
interval and 99.4% likelihood of superiority.

Accepted Engine 5.1 jointly retunes all 426 exported linear evaluation
parameters on 6,867,145 positions from 64,000 fresh Engine 5.0 self-play
games. Native feature extraction, PST orientation, symmetry, rounded-parameter
packaging, and engine evaluations were verified before testing. Its SPRT
against Engine 5.0 accepted H1 after 662 games at 298 wins, 154 draws, and 210
losses, measuring +46.5 Elo with a reported +/-23.3 interval.

Accepted Engine 5.2 adds internal-node principal variation search (PVS).
After the first ordered move, later moves are initially searched with a
zero-width window and receive a full-window re-search only when they improve
alpha without immediately failing high. LMR moves must still pass a full-depth
zero-window verification before they can affect the PV or cause a cutoff.
Root PVS is deliberately omitted so timeout-based partial-root adoption keeps
comparing fully searched root scores with the same semantics as Engine 5.1.
Its SPRT against Engine 5.1 accepted H1 after 1,794 completed games at 696
wins, 502 draws, and 596 losses, measuring +19.4 Elo with a reported +/-13.6
interval and 99.7% likelihood of superiority.

Accepted Engine 5.3 replaces the two-step LMR rule with a conservative
depth/move-number schedule. Reductions grow for deeper searches and later
quiet moves, shrink at PV nodes and for strong butterfly-history moves, and
grow for strongly negative-history moves. Hash moves, captures, promotions,
killers, castling, checks, and check evasions remain unreduced. Every reduced
alpha improvement is still verified at full depth.

Its SPRT against Engine 5.2 accepted H1 after 2,484 completed games at 948
wins, 698 draws, and 838 losses, measuring +15.4 Elo with a reported +/-11.6
interval and 99.5% likelihood of superiority.

Accepted Engine 5.4 adds conservative one-ply singular extensions. At
internal depth-seven-or-greater nodes with a sufficiently deep exact/lower TT
entry, a reduced null-window search excludes the legal hash move. If every
alternative remains well below the stored score, only that hash move receives
one extra ply. Verification nodes cannot use TT cutoffs, node-level forward
pruning, null move, heuristic updates, or TT storage for the altered move set.

Its SPRT against Engine 5.3 accepted H1 after 1,979 completed games at 768
wins, 546 draws, and 665 losses, measuring +18.1 Elo with a reported +/-13.0
interval and 99.7% likelihood of superiority.

This folder contains the refactored version of `chess_8.c`. The executable's
entry source is now `chess.c`, while implementation details are grouped by
responsibility:

- `chess_types.c` — shared piece, move, position, and bitboard definitions
- `board_logic.c` — attack detection, move generation, legality, and positions
- `game_helpers.c` — FEN parsing, SAN notation, game records, and PGN output
- `chess_engine.c` — PeSTO evaluation, iterative search, and perft diagnostics
- `command_helpers.c` — text command parsing and bot/game-mode helpers
- `tournament.c` — saved-version workers and randomized EPD match runner
- `chess_main.c` — help text and the interactive program loop

The smaller files are intentionally assembled by `chess.c`. This keeps the
original private helper functions private and preserves behavior while still
making each area of the program easy to navigate.

## Build

With GCC:

```text
gcc -std=c11 -O3 -march=native -flto -Wall -Wextra -pedantic chess.c -o chess.exe -lgdiplus -lgdi32 -luser32
gcc -std=c11 -O3 -march=native -flto -Wall -Wextra -pedantic -DCHESS_GUI_DEFAULT chess.c -o chess_gui.exe -lgdiplus -lgdi32 -luser32
```

With Microsoft Visual C:

```text
cl /std:c11 /O2 /W4 chess.c
```

Compile only `chess.c`; it includes the responsibility-specific source files.

## Engine versions and matches

The active build is accepted **version 4.0**. It adds legality-aware bitboard
SEE and prunes negative-SEE captures in qsearch while retaining promotions,
checks, evasions, and equal exchanges. The preserved source and native
executable are `engine_versions\source_4.0` and `engine_versions\4.0.exe`; a
portable O2 build is retained as `engine_versions\4.0_portable.exe`.

The historical accepted **version 1.7** source snapshot promoted the tested
`1.6_reverse_futility_v2` candidate. It applies reverse futility pruning only at depths
1-3 in scout nodes, using a 120-centipawn margin per remaining ply. Check
nodes, pawn-only endings, mate-score windows, and artificial null-move branches
are excluded. Search diagnostics report `rfp evaluations/prunes`.

Version **1.7.1** accepts the tested `1.7_rule50` maintenance candidate. Static evaluations
remain unchanged through 40 reversible plies, then taper toward zero as the
fifty-move draw approaches. Captures and pawn moves reset the clock and thereby
regain the full evaluation, encouraging conversion in winning endings without
an unconditional move-type bonus. The combined 1,517-game result was effectively
neutral, so this is recorded as a conversion-quality fix rather than an Elo gain.

The experimental build **1.7.1_eval_pst_wdl** keeps version 1.7.1's search,
material values, pawn evaluation, and other evaluation features unchanged. It
uses rounded, mirrored, zero-mean PST deltas fitted to Stockfish WDL expected
scores. This tournament candidate does not replace accepted version 1.7.1.

Accepted **version 2.0** promotes that WDL-trained PST experiment after a
1,000-game paired-opening match scored 417 wins, 238 draws, and 345 losses
against 1.7.1: +25.06 Elo, 95% CI +6.27 to +43.99. Version 2.0 begins the
evaluation-focused development series while preserving 1.7.1's search.

Accepted **version 2.1** promotes the joint WDL fit after scoring 535 wins, 170
draws, and 295 losses against version 2.0 over 1,000 paired-opening games. The
measured gain was +85.04 Elo (95% CI +65.20 to +105.44). It jointly fits version
2.0's PSTs, N/B/R/Q material values, piece-specific mobility, bishop-pair
bonuses, and pawn structure. Isolated-pawn penalties were exposed to the
optimizer but fitted to zero, so they add no runtime work.

The underlying accepted **version 1.6** adds bounded butterfly-history
ordering, depth-scaled cutoff rewards, equal penalties for earlier quiet
failures, and no updates from check-evasion nodes.

The underlying accepted **version 1.5** promotes the tested
`1.4_null_move` candidate. Null moves remain disabled in check, pawn-only
endings, mate-score windows, shallow nodes, and directly after another null.

The underlying accepted **version 1.4** promotes the tested
`1.3_qsearch_generator` candidate. At non-check quiescence nodes it stores and
sorts only captures, en passant, and promotions. It still recognizes quiet
legal moves for stalemate detection and generates every evasion while in check.

The accepted engine is version **4.0**. Its preserved executable is
`engine_versions\4.0.exe`, and its source snapshot is
`engine_versions\source_4.0`. Future experiments keep the version number at
4.0 but receive a descriptive build ID, such as `4.0-search-test`. Save each
build under that ID in `engine_versions` and do not overwrite the earlier file.
Only change `ENGINE_VERSION` after an experiment is accepted as a new version.

Version 1.3 accepts the successful **1.2_delta_pruning** experiment after a
1,000-game match measured +27.50 Elo with a 95% interval of +8.73 to +46.44.
In quiescence search, a
non-promotion capture may be skipped when stand-pat plus the captured material
and a conservative 200-centipawn margin still cannot reach alpha. It never
delta-prunes in check, checking captures, promotions, or near mate scores.
Search diagnostics report skipped captures in the `delta` field.

Absolute estimates and measured gains are recorded in
`engine_versions\ELO_HISTORY.md`. The initial estimate for version 1.3 is about
1743 Elo in the same local 1+0.1 calibration environment used for version 1.2.

Version 1.2 promotes the `1.1_castling` candidate after tournament validation.
It includes the accepted aspiration-window, killer-ordering, and late-move
reduction search, recognizes
only the normal c/g king files for full castled pawn-shelter credit, gives a
small tapered castling/rook-development bonus, penalizes losing castling rights
without reaching a castled square, and orders castling above ordinary quiet
moves. Its LMR rules are identical to version 1.1.

Versions 1.1 and 1.2 support the Universal Chess Interface when launched with
`--uci`. It handles the standard handshake, readiness checks, new-game resets,
`position startpos`, six-field FEN positions, coordinate move histories,
`wtime`/`btime`/increments, `movetime`, `depth`, `Move Overhead`, and UCI
`info`/`bestmove` output. The separate `lichess-bot` folder contains the
official bridge, its isolated Python environment, a private-token setup script,
and a bot-vs-bot matchmaking configuration.

The GUI has an editable lag reserve (default 0.01 seconds). It subtracts this
reserve once from the normal `remaining/20 + increment/2` search allocation.
Local UCI play defaults to zero overhead,
and the reference tournament launcher explicitly requests zero so both engines
can use their full clocks. The Lichess configuration explicitly enables a
0.50-second engine reserve plus a 1.50-second bridge reserve for network and
move-submission delay.

The text interface runs matches with:

```text
tournament 1.0 random 100 5 0 64
tournament 1.0 1.0-null-move-test 200 10 0.1 64
```

The final three settings are optional and mean base seconds, increment seconds,
and maximum depth. `random` selects uniformly from legal moves. Every game uses
a randomly selected starting FEN from `8mvs_+90_+99.epd`, and the two entrants'
colors are randomized independently. Per-game cumulative scores and final wins,
draws, and errors are printed. The GUI provides the same participant and game
count fields and shows the aggregate result after Run Match finishes.

Analyze aggregate results interactively with `python tournament_analysis.py`,
or pass Engine A's wins, losses, and draws directly, for example:

```text
python tournament_analysis.py 60 40 100
```

The report includes score rate, confidence intervals, estimated Elo gain,
normal one- and two-sided p-values, likelihood of superiority, and an exact
binomial p-value conditional on decisive games.

## External reference tournaments

The `reference_engines` folder contains official open-source releases of
Stockfish 18, Blunder 8.5.5, and Carballo 1.8, together with Cute Chess 1.5.1.
Its PowerShell launcher runs UCI matches from paired EPD openings and
automatically sends the resulting PGN through the statistical analyzer:

```text
cd reference_engines
.\run_tournament.ps1 -Opponent Stockfish1320 -Games 100 -TimeControl "10+0.1"
.\run_tournament.ps1 -Opponent Gauntlet -Games 100 -TimeControl "10+0.1"
```

See `reference_engines\README.md` for every opponent profile, recommended
sample sizes, output locations, and calibration limitations.

## Graphical interface

Run `chess_gui.exe` for the native Windows board, or launch `chess.exe --gui`.
Optional startup time controls are accepted, for example `chess_gui.exe 5 2`.
Click a piece to highlight its legal destinations, then click a destination to
move. The toolbar starts human-vs-human games, games as White or Black against
the engine, engine-vs-engine games, or asks the engine to move for the current
side. White and Black have independent editable base-time and increment fields,
plus a shared maximum-depth field. Separate **White unlimited** and **Black
unlimited** options disable time forfeits for only the selected player and let
the depth limit control that engine's searches. Both
clocks remain paused until White
completes the first move. Each engine receives its own current remaining time
and increment in the existing `base/20 + increment/2` search formula.
Promotions default to a queen.
The engine list contains every accepted saved release and its approximate Elo
estimate from `engine_versions/ELO_HISTORY.md`. Press **Apply** after changing
the engine or clock settings, then start a new game. The current release runs
inside the GUI; older releases use their preserved executables. The most recent
recognized ECO code and opening name appear beneath the board and remain shown
after the game leaves the book.
Piece PNGs are loaded from the `images` folder beside the executable, with
scalable Windows chess glyphs as a fallback if an asset cannot be loaded.
The board is double-buffered so frequent clock updates do not visibly erase and
redraw individual squares or pieces.
The dedicated GUI build retains its console window so engine depth, score,
nodes, TT statistics, and PV output remain visible. When a GUI game ends, its
final PGN is printed there once; clock forfeits receive the correct PGN result.

## Startup time controls

The base time and increment can be supplied in seconds when launching the
program. Both of these forms are accepted:

```text
chess.exe 10 0
chess.exe --time 5 2
```

The first example uses 10+0 and the second uses 5+2. If the increment is
omitted, it defaults to zero. The interactive `time <base> <increment>` command
can still change the time control after startup.

When checkmate, stalemate, or another recognized draw ends the game, the final
PGN is automatically printed once.

All evaluations printed by `eval` or an engine search use White's perspective:
a positive score favors White and a negative score favors Black, independent
of which side is currently moving.

Positions also carry deterministic 64-bit Zobrist keys. The reversible key
history is used to claim a draw on the third occurrence of the same position,
and the engine evaluates repetition nodes as `0.00` during its search.

## Opening book

Accepted version **6.4** replaces the small hand-written opening book with the
CC0 Lichess opening collection. Each candidate continuation was evaluated by
Stockfish at depth 14 and Engine 6.3 at depth 8. Stockfish-weak moves remain in
the data at weight zero for opponent-line recognition, while selectable moves
receive blended position-relative weights. Opening ECO codes and names are
printed while the position remains in book.

`OpeningBook.tsv` is the preferred opening format for the
**6.4** build. Each row contains `fen`, `move`, and an integer
`weight`; the engine randomly selects among legal continuations in proportion
to those weights. The initial Lichess-derived book assigns every unique move a
weight of one. `OpeningNames.tsv` maps named positions to ECO codes and names,
which are printed with UCI search information and the text-mode `eval` command
while the position still has a book continuation. The UCI `OwnBook` option can
disable all book use. `OpeningBook.txt` remains the fallback format and
contains one coordinate-move variation per line. Lines that
start with `//` are comments. At each engine turn, the current Zobrist key is
used to find all distinct legal continuations in the book; one is selected at
random. If none match, the engine falls back to its normal iterative search.
The book is located beside the executable, so the program may be launched from
another working directory without losing access to it.

The PeSTO evaluation also recognizes several drawish pawnless minor-piece
endgames and returns `0.00` for them unless search finds a concrete mate. In a
clearly won bare-king ending, a mop-up term rewards pushing the defending king
to an edge and bringing the attacking king closer.

Middlegame evaluation includes pawn shelter on the king's wing, legal-move
piece mobility, and weighted pressure into an expanded enemy-king zone. The
mobility and attack terms share a direct board scan instead of building two
temporary move lists. Mobility is reduced by half in the endgame, while shelter
and king pressure are tapered using the existing PeSTO game phase.

Pawn structure evaluation rewards passed pawns increasingly by advancement and
in the endgame. Doubled pawns and backward pawns receive separate middlegame
and endgame penalties, with all terms blended according to remaining non-pawn
material through the PeSTO phase calculation.

Search uses a 524,288-entry transposition table with depth-aware exact, lower,
and upper bounds. Mate scores are normalized by ply when stored. Move ordering
tries the table's hash move first, followed by promotions and MVV-LVA captures;
iterative-deepening scores continue to order the remaining root moves.
The search key includes the fifty-move clock, and TT score cutoffs are disabled
after the current position has already appeared on the active history path;
the cached move remains available purely for ordering in that case.
After a completed iteration, the displayed principal variation is reconstructed
from legal hash moves when TT cutoffs left the live PV short. Matching entries
from earlier searches are allowed because the score search can also reuse them;
legality, repetition, and maximum-depth checks keep reconstruction bounded.
This reconstruction is cosmetic and cannot affect the chosen engine move.

## Syzygy tablebases (accepted in 6.3)

This source includes the official Fathom probe library. Build it
from PowerShell with `./build.ps1`; Fathom must be compiled and linked as a
second C source file, so the older one-file command is not sufficient here.

UCI clients may set `SyzygyPath` to a semicolon-separated Windows path. The
candidate probes DTZ at eligible roots and exact WDL inside search after
zeroing moves. `SyzygyProbeDepth`, `SyzygyProbeLimit`, and
`Syzygy50MoveRule` provide the usual controls.
