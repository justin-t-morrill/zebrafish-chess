# Zebrafish 9.1 release candidate

The trained candidate beat frozen 9.0 at one second plus 0.1 seconds per move. Cute Chess accepted H1 at LLR +2.97 for 0 versus +10 Elo. It scored 100 wins, 79 draws and 36 losses in 215 games (64.9%, +106.7 observed Elo). The 107 completed opening pairs scored 99 wins, 79 draws and 36 losses. Their approximate 95% Elo interval is +68 to +145. The three-minute SPRT also passed on previously unseen openings, with 103 wins, 129 draws and 46 losses (LLR +2.99). This playing configuration is now [frozen as 9.1](../../versions/v9/source_9.1/README.md). The external CCRL Blitz 8CPU anchor of about 3110 belongs to version 8.3.

## Run it

Keep **9.1-rc1.exe** and **nnue-material.bin** together. The executable loads the network from its own directory. Use `9.1-rc1.exe --uci` for a UCI chess interface. From this directory, `.\run-blitz.ps1` starts a fresh SPRT against 9.0 at three minutes plus one second per move. For three *seconds* plus one second per move, use `.\run-blitz.ps1 -TimeControl "3+1"`. Both engines get one thread and 64 MiB hash, with books and tablebases off. The default is six simultaneous games. `.\build.ps1` rebuilds the Windows executable for the local CPU with GCC and the repository's Fathom source.

To continue an unfinished overnight three-minute test on this PC, run
`.\run-blitz.ps1 -Resume`. Add `-Preview` to see the cumulative score
without starting games. This checks the original executables, both networks
and the opening file, restores missing colors, and continues the original
0 versus +10 Elo test. Completed games and the first boundary crossing are
retained across restarts. New batches and PGNs are saved alongside the
original match. The continuation uses Python 3.11 or later with psutil.

After the three-minute test accepts H1, `.\run-blitz.ps1 -Promote` installs
the preverified 9.1 release locally. It also recognizes an H1 from a resumed
test and verifies its scored game logs. `-Promote -Preview` lists the pending
changes. The installer checks the existing working sources before replacing
them and keeps a backup of each replaced file.

The [lean search change](followups/lean-search.patch) uses the same network and
reproduced the baseline's fixed-depth moves, scores and node counts on all 46
benchmark positions. On this PC, `.\run-blitz.ps1 -SpeedTest -Resume -Preview`
replays the completed 1+0.1 SPRT and prints its result.
`.\run-blitz.ps1 -SpeedTest` starts a fresh three-minute SPRT between those
two builds.

This speed improvement passed its short-clock SPRT at 261 wins, 301 draws
and 189 losses (54.8%, LLR +2.96). The [RC2 package](../9.1-rc2/README.md)
contains the verified executable and its separate three-minute test against RC1.

The [accumulator-frame variant](followups/accumulator-frames.patch) includes
the lean changes and stores parent accumulators by search ply. It used 19.6%
less time on 30 depth-13 positions with identical moves, scores and node
counts. It scored 54 wins, 58 draws and 48 losses in its 160-game pilot.
Apply this patch directly to the RC1 source on a separate checkout.

For an external estimate on this PC, `.\run-calibration.ps1` starts a fresh
270-game match using the same centered opponent pool as the 8.3 calibration.
It gives the candidate eight threads, plays one game at a time, and prints
the fitted performance rating and an opening-pair uncertainty interval.
`.\run-calibration.ps1 -Preview` lists the settings and opponents.

To use any games from the overnight four-opponent calibration, run
`.\run-calibration.ps1 -Resume`. It plays 34 reversed-color opening pairs
against each of Black Marlin 4.0, Peacekeeper 1.60, PeSTO 2.210 and Jackal
1.0.0, for 272 games including any completed overnight. A saved single
color is paired with its missing return game. Add `-Preview` for scores.

## What changed


- Later root moves get a narrow scout window. Late, quiet, non-checking moves can first search one or two plies shallower. A challenger that raises alpha gets a full-depth verification, then a principal-variation search when its score lies inside the window.
- The main move picker tries a validated hash move, non-losing captures and promotions, two quiet killers, history-ordered quiets, then losing captures. It generates each group as needed.
- Search learns a bounded evaluation correction from quiet results with similar pawn structures. Low reversible-move clocks can share transposition entries. Tablebase-eligible boards retain distinct rule-50 keys.
- NNUE fuses per-move accumulator changes and uses an exact packed AVX2 output sum when the weights admit it. Larger integer weights use the scalar fallback.
- The network shares a 256-neuron feature transformer. Four output heads cover 2–8, 9–16, 17–24 and 25–32 pieces. It was initialized from the 8.3 checkpoint and jointly fine-tuned for 1,006,632,960 examples from the existing shuffled corpus. Its held-out sigmoid mean squared error was 0.009163 across 249,989 Lichess positions and 0.004929 across 277,422 controlled positions. Frozen 9.0 scored 0.009311 and 0.005105, respectively.

## Verification

Run `.\test.ps1` to reproduce the staged move, accumulator and perft checks.
When the bundled KQvK tablebase is available, the same script tests rule-50
keys and the interior WDL probe.

Fixed-node analysis divides the requested node count among search threads.
Each helper stops when it has spent its own share, so the main thread can
complete its iteration. A 672-search regression across one, two, four and
eight threads had zero budget overruns. On the previous build, 58 searches
exceeded the requested total and 14 forced-move searches at budgets of at
least 511 nodes returned depth zero. The time-controlled games use a clock.

A single-head network trained on the same positions, schedule and optimizer
budget scored 0.009202 on Lichess and 0.004951 on the controlled set. The four
heads made their largest difference with 2–8 pieces, reducing error by 1.15%
and 1.60% on those two sets. In controlled positions with 17 or more pieces,
the single head had slightly lower error. An independent match isolates the
four-head design from the other search changes.

An optional [transposition-table patch](followups/tt-consistency.patch)
binds stored scores to the full position hash during concurrent replacement.
In a deterministic interleaving check, the original probe accepted 56 mixed
records and the patched probe accepted zero. It reproduced all 30
single-thread depth-13 move, score and node-count comparisons. Both builds
passed a separate 5.6-million-probe stress run. Its Elo effect is unmeasured.

The full-search and staged move generators agreed on 44,805 positions, including en passant, both castles and underpromotions. Incremental NNUE accumulators matched a rebuild after makes and unmakes. The five-position perft suite passed. The UCI stopping checks passed with one and four threads.

An optional [interrupted-search fix](followups/partial-root-bounds.patch) preserves the previous move if both partial scores are upper bounds. In 1,800 deterministic interruptions it changed four moves, all at 1,536 nodes. The match executable retains its original search. To try the follow-up on a separate checkout, apply the patch with `git apply --directory=engines/experiments/9.1-rc1/source engines/experiments/9.1-rc1/followups/partial-root-bounds.patch` and build with a separate output path.

The match executable is labeled **trained** in the raw PGNs. The packaged executable also isolates tablebase-eligible rule-50 keys, clears cached entries when tablebase options change, and records fused accumulator work in profiling builds. With match options, the package reproduced the trained executable’s moves, scores and node counts on all 16 positions at depth 12. A dedicated test verified clock-zero WDL probing and distinct clock keys on an actual KQvK tablebase. The manifest identifies both builds and the exact network.

[Overnight results](RESULTS.md) · [Live scores](../../../testing/results/overnight_9_0_20261124/LIVE.md) · [215-game log](../../../testing/results/overnight_9_0_20261124/matches/trained-baseline-sprt/match.log) · [Games](../../../testing/results/overnight_9_0_20261124/matches/trained-baseline-sprt/games.pgn) · [Training and benchmark details](../../../testing/results/overnight_9_0_20261124/STATUS.md)
