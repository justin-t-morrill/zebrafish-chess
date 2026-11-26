# Zebrafish 9.1-rc2

Promoted locally to [9.2](../../versions/v9/source_9.2/README.md) after 250 wins, 425 draws and 215 losses in 890 games (52.0%, +13.7 observed Elo, LLR +1.223) against 9.1 at 180+1. The three-minute SPRT was closed as inconclusive at promotion.

The lean challenger scored 261 wins, 301 draws and 189 losses in 751 games
against 9.1-rc1 at one second plus 0.1 seconds per move (54.8%,
+33.4 observed Elo). The independent 0 versus +10 Elo SPRT accepted H1
at LLR +2.96. The games used one thread and 64 MiB hash per engine, no
tablebases and color-reversed openings. It avoids redundant check and exchange work and moves the large NNUE refresh temporary off the ordinary evaluation path.

Keep **9.1-rc2.exe** and **nnue-material.bin** together. Use
`9.1-rc2.exe --uci` to run the engine. From this directory,
`.\run-blitz.ps1` starts a fresh three-minute plus one-second SPRT
against 9.1-rc1. Use `-TimeControl "3+1"` for three seconds plus one
second per move. `.\test.ps1` checks legal moves, NNUE state and perft.
The package matched the timed-match binary on all ten fixed-depth comparison
positions. See the [overnight report](../9.1-rc1/RESULTS.md) for updated
longer-clock results, confidence intervals and component tests.

The overnight three-minute test used one thread and 64 MiB per engine with
color-reversed openings. Run `.\run-blitz.ps1 -Resume -Preview` to replay the
score from the original match logs.

Open `Zebrafish-Live.html` in the project root to review the final score and
saved games locally. After 9.2 is installed, the launcher also opens this
archive and the runner keeps the match closed.

Select a live board, or choose a completed game under **Past games**, to
replay moves, inspect the graphical position, and copy or download PGN.
The archive uses the original Cute Chess PGN, including its engine notes.
Games logged before their PGN was flushed show their result while waiting
for the move text. A live recording that starts mid-game labels its partial
PGN and switches to the original when available.

The match ETA uses 1,024 simulations that resample completed color-reversed
opening pairs and stop at the existing SPRT bounds or game cap. The median
and middle 80% of simulated durations assume continuous play at the speed of
the last six completed eight-board batches. These are projections conditional
on the observed game distribution.
