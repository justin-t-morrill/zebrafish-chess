# Engine Elo history

This is the concise record of accepted releases. Except for the explicitly
marked 8.3 CCRL calibration, ratings are historical local estimates, not
official human, Lichess, FIDE, Chess.com, or CCRL ratings. SPRT results primarily
measure relative change between adjacent versions and should not be assumed to
transfer unchanged between time controls or thread configurations.

Because Stockfish `UCI_Elo` is nonlinear in this setup, absolute estimates
should normally be treated as having at least ±50 Elo systematic uncertainty.
Thread count, hardware, time control, opening suite, and opponent pool all
matter. Full historical notes, including rejected and superseded experiments,
are preserved in
[`archive/ELO_HISTORY_full_2026-09-03.md`](../archive/ELO_HISTORY_full_2026-09-03.md).

## Current estimate

9.2 is the current accepted release. Its observed gains against 9.1 were +33.4 Elo at 1+0.1 and +13.7 Elo at 180+1. The latest external calibration covers 8.3.

| Version | Estimated strength | Configuration | Confidence |
|---|---:|---|---|
| **8.3** | **~3110 CCRL Blitz 8CPU** | 8 threads, 512 MB hash, full-data plain Chess768x256 NNUE | Hardware-normalized CCRL-style calibration against exact single-CPU CCRL versions: 270 centered games imply ~3118; all 300 usable games imply ~3106. Recorded as ~3110 with ±43 Elo match-only and roughly ±60 Elo practical uncertainty. |

## Accepted releases

| Version | Estimate | Change | Main additions | Evidence |
|---|---:|---:|---|---|
| 1.0 | ~1563 | Baseline | Alpha-beta, PeSTO, qsearch, TT, iterative deepening, book, repetition hashing, GUI/text play, PGN and tournaments | Back-calibrated from later external tests |
| 1.1 | ~1646 | ~+83 inferred | Aspiration windows, killers, LMR, UCI and Lichess integration | No clean direct anchor |
| 1.2 | ~1650 | +4.5 | Castling-aware evaluation and ordering | 1,000 games; uncertain |
| 1.3 | ~1678 | +27.5 | Delta pruning in qsearch | 1,000 games |
| 1.4 | ~1705 | +27.5 | Dedicated qsearch tactical generation | 1,000 games; 418/243/339 |
| 1.5 | ~1732 | +26.8 | Guarded null-move pruning | 1,000 games; 419/239/342 |
| 1.6 | ~1745 | +13.0 | Butterfly-history ordering | 3,000 games; 95% CI about +1.9 to +24.0 |
| 1.7 | ~1775 | +30.3 | Reverse futility pruning | 1,000 games; 95% CI +11.4 to +49.4 |
| 1.7.1 | ~1775 | +1.8 | Rule-50-aware evaluation scaling | 1,517 games; statistically neutral maintenance release |
| 2.0 | ~1800 | +25.1 | WDL-tuned PeSTO PSTs | 1,000-game match plus Stockfish 1750/1800 calibration |
| 2.1 | ~1840 | +85.0 self-play | Joint WDL fit of PST, material, mobility, bishop-pair and pawn terms | 1,000 games; external scale compresses the self-play gain |
| 2.2 | ~1865 | +23.7 | King-safety WDL fit | 1,000 games plus Stockfish 1750/1800 checks |
| 2.3 | **~1935** | +40.0 | Texel fit of 42 non-PST terms over 6.67M qsearch leaves | **External anchor:** 7,000 Stockfish games; weighted estimate 1937.3 |
| 3.0 | ~1995 | +60.5 | Cached ordering, pawn hash, incremental evaluation and Zobrist | 499-game SPRT; runtime down roughly 29–33% |
| 3.1 | ~2145 | +152.9 | Complete bitboard conversion and magic sliders | 203-game SPRT; runtime down 45.5% |
| 3.2 | **~2185** | +42.1 | Safe partial-root adoption at timeout | **External anchor:** 4,000 Stockfish games; weighted estimate 2186.7 |
| 3.3 | ~2250 | +65.0 | Direct legal generation, early TT cutoffs and staged ordering | 476-game SPRT |
| 3.4 | ~2270 | +20.0 | Evaluation cache, faster mobility and delayed qsearch generation | 1,830-game SPRT; +20.0 ±13.9 |
| 3.5 | ~2295 | +25.7 | Native LTO build | 1,341-game SPRT; +25.7 ±16.4 |
| 4.0 | ~2320 | +26.3 | Bitboard SEE and negative-SEE qsearch pruning | 1,259-game SPRT; +26.3 ±16.7 |
| 4.1 | ~2445 | +125.1 | SEE-informed capture ordering | 249-game SPRT; +125.1 ±41.4 |
| 5.0 | **~2615** | +319.6 short-control | Corrected PST orientation and retuned 384 PST terms | **External anchor:** 4,000 Stockfish games; weighted estimate 2615.4 |
| 5.1 | ~2660 | +46.5 | Joint Texel retune from 64,000 fresh self-play games | 662-game SPRT; +46.5 ±23.3 |
| 5.2 | ~2680 | +19.4 | Internal-node PVS | 1,794-game SPRT; +19.4 ±13.6 |
| 5.3 | ~2695 | +15.4 | Improved LMR schedule | 2,484-game SPRT; +15.4 ±11.6 |
| 5.4 | ~2715 | +18.1 | Singular extensions | 1,979-game SPRT; +18.1 ±13.0 |
| 5.5 | ~2728 | +12.5 | Narrow tactical ProbCut | 3,355-game SPRT; +12.5 ±9.9 |
| 5.6 | ~2801 | +72.9 | Improving heuristic and LMP | 377-game SPRT; +72.9 ±30.1; unusually short result |
| 5.7 | ~2811 | +9.6 | Multi-signal LMR | 5,412-game SPRT; +9.6 ±7.7 |
| 6.0 | ~2750 | +30.0 | Phase-tapered threat evaluation | 1,021-game SPRT; absolute estimate reset using long-control evidence |
| 6.1 | ~2763 | +13.1 | Joint retune of 446 evaluation parameters | 3,096-game SPRT; +13.1 ±10.3 |
| 6.2 | ~2790 | +27.0 | Detailed pawn and passed-pawn evaluation | 1,239-game SPRT; 95% CI +10.1 to +43.9 |
| 6.3 | ~2808 | +18.3 | Native six-piece Syzygy through Fathom | 1,845-game SPRT; 95% CI +5.2 to +31.5 |
| 6.4 | ~2808 | Not measured | Weighted Lichess-derived repertoire and opening names | Legality/infrastructure validation; rating carried forward |
| 7.0 | ~3000 | +199.1* | Clustered atomic TT and Lazy SMP | 114 games using 8 threads against 1 thread |
| 7.1 | ~3040 | +21.3 equal-thread; +18.2 scaling | Persistent worker pool and asynchronous UCI stopping | 1,407-game implementation SPRT and 1,773-game 16-vs-8 test |
| 7.2 | ~3060 | +20.6 | SPSA-tuned LMR/LMP | 1,586-game SPRT; +20.6 ±14.2 |
| 7.3 | ~3075 | +13.8 | SPSA-tuned RFP, null move and ProbCut | 2,817-game SPRT; +13.8 ±10.7 |
| 8.0 | **~3245** | +169.8 | Chess768×128 NNUE with incremental accumulators | 192-game SPRT; 95% CI +122.4 to +223.9; absolute estimate provisional |
| 8.1 | **~3257** | +11.6 | SPSA-tuned singular-extension, aspiration, delta-pruning and history constants | 3,588-game SPRT; 1,250/1,208/1,130; +11.62 Elo, 95% CI +2.37 to +20.90 |
| 8.2 | **~3287** | +30.3 | Plain Chess768x128 NNUE retrained on 10M filtered Lichess plus 2.29M controlled positions | 943-game 1+0.1 SPRT; 419/187/337; H1 accepted; +30.3 ±19.9 Elo |
| 8.3 | **~3110 CCRL Blitz 8CPU** | +133.7 at 1+0.1 vs 8.2; not treated as +133.7 at CCRL control | Full-data plain Chess768x256 NNUE | Direct 218-game 1+0.1 SPRT vs accepted 8.2: 128/42/48, H1 accepted, +133.7 ±44.0 Elo. The separate 300-game hardware-normalized CCRL calibration gives ~3106 overall and supersedes the former ~3420 provisional absolute estimate. |
| 9.0 | External calibration pending | +64.0 at 1+0.1 vs frozen 8.3 | Adaptive soft target and hard deadline, instant forced moves, 8.3 NNUE | 412-game SPRT, 179 wins / 129 draws / 104 losses (59.1%), +64.0 ±28.1 Elo as reported by Cute Chess. H1 accepted at LLR +2.95 with bounds ±2.94 for 0 vs +10 Elo and 5% error rates. One thread and 64 MiB hash each, eight concurrent games, paired 8mvs_+90_+99 openings, book and tablebases off. |
| 9.1 | External calibration pending | +106.7 at 1+0.1 and +72.3 at three minutes + one second vs frozen 9.0 | Staged generation, root scout and verified reductions, pawn correction, optimized four-head NNUE | Both SPRTs accepted H1. Three-minute score 103W / 129D / 46L in 278 games. [Test report](experiments/9.1-rc1/RESULTS.md) |
| 9.2 | External calibration pending | +33.4 at 1+0.1 and +13.7 at 180+1 vs 9.1 | Lean search, 9.1 network | The one-second plus 0.1-second SPRT accepted H1 (LLR +2.961). The three-minute SPRT was closed as inconclusive at promotion. Three-minute result 250 wins, 425 draws and 215 losses in 890 games (52.0%, +13.7 observed Elo, LLR +1.223). |

\* Version 7.0 used unequal computational resources, so this is not a clean
single-thread architectural Elo gain.

## External calibration anchors

These matches carry more weight for absolute estimates than self-play.

| Version | Control | Games | Opponents | Weighted estimate |
|---|---|---:|---|---:|
| 2.0 | 10+0.1 | 7,653 | Stockfish 1320, 1600, 1750 and partial 1800 | ~1800 |
| 2.3 | 10+0.1 | 7,000 | Stockfish 1320–2400 | 1937.3 |
| 3.2 | 10+0.1 | 4,000 | Stockfish 2100–2400 | 2186.7 |
| 5.0 | 10+0.1 | 4,000 | Stockfish 2500–2800 | 2615.4 |
| 6.0 | 120+1 | Partial long-control calibration | Nearby Stockfish profiles | ~2750 |
| **8.3** | **CCRL 120+1 equivalent (68.2+0.57 locally)** | **300 usable** | **Blunder 8.5.5, Black Marlin 4.0, Jackal 1.0.0, PeSTO 2.210, Peacekeeper 1.60** | **~3110 CCRL Blitz 8CPU** |

### Detailed closest-anchor results

| Engine | Opponent | W / D / L | Score | Implied rating |
|---|---:|---:|---:|---:|
| 2.3 | SF 1750 | 634 / 24 / 342 | 64.60% | 1854.5 |
| 2.3 | SF 1800 | 625 / 27 / 348 | 63.85% | 1898.8 |
| 2.3 | SF 1850 | 605 / 23 / 372 | 61.65% | 1932.5 |
| 2.3 | SF 2000 | 460 / 30 / 510 | 47.50% | 1982.6 |
| 3.2 | SF 2100 | 529 / 34 / 437 | 54.60% | 2132.1 |
| 3.2 | SF 2200 | 402 / 39 / 559 | 42.15% | 2145.0 |
| 3.2 | SF 2300 | 374 / 41 / 585 | 39.45% | 2225.6 |
| 3.2 | SF 2400 | 278 / 46 / 676 | 30.10% | 2253.6 |
| 5.0 | SF 2500 | 637 / 89 / 274 | 68.15% | 2632.1 |
| 5.0 | SF 2600 | 448 / 133 / 419 | 51.45% | 2610.1 |
| 5.0 | SF 2700 | 324 / 176 / 500 | 41.20% | 2638.2 |
| 5.0 | SF 2800 | 120 / 192 / 688 | 21.60% | 2576.1 |

The variation in implied ratings, especially when opponent strengths are far
apart, is why headline estimates are rounded and carry systematic uncertainty.

### Version 8.3 direct CCRL calibration

This calibration used Engine 8.3 with 8 threads and 512 MB hash against exact
single-CPU CCRL-listed opponent versions using one thread and 128 MB hash.
Pondering and engine books were disabled, paired colors used the common
`8moves_v3.epd` suite, and tablebases were disabled for both sides. A local
Stockfish 10 benchmark took a median 1,167 ms versus the 2,054 ms CCRL reference,
so CCRL's 120+1 control was run locally as 68.2+0.57. Concurrency was one to
avoid oversubscribing the machine.

| Opponent | CCRL rating | Games | W / D / L | Score | Implied 8.3 rating |
|---|---:|---:|---:|---:|---:|
| Blunder 8.5.5 | 2666 | 20 | 13 / 6 / 1 | 80.0% | 2906.8 |
| Black Marlin 4.0 | 3200 | 10 | 1 / 2 / 7 | 20.0% | 2959.2 |
| Jackal 1.0.0 | 2949 | 100 | 59 / 22 / 19 | 70.0% | 3096.2 |
| PeSTO 2.210 | 2989 | 100 | 61 / 21 / 18 | 71.5% | 3148.8 |
| Peacekeeper 1.60 | 3043 | 70 | 33 / 17 / 20 | 59.3% | 3108.3 |

The maximum-likelihood estimate from the 270 deliberately centered games is
about 3118. Including the 30 earlier low/high bracketing games gives about 3106
with an approximate match-only 95% interval of ±43 Elo. The headline is rounded
to **~3110 CCRL Blitz 8CPU**, with roughly **±60 Elo practical uncertainty** to
allow for opponent-list uncertainty, opening mix, missing tablebases, and local
hardware normalization.

Historical ratings were not shifted by a universal constant. Early versions
were single-thread engines, later evidence mixes 1-, 8-, and 16-thread tests,
and many relative SPRTs used much shorter controls. The old numbers remain useful
on their stated local scales, but the 8.3 calibration is the new absolute CCRL
anchor for future releases tested under comparable conditions.

## Active candidates

No NNUE architecture candidate is currently active. Full-data plain 256 was
accepted as 8.3; both king-bucket candidates lost their ladder matches. The
external calibration against exact CCRL-listed engines is complete.

## Recording policy

For each accepted release, record:

1. Opponent, time control, thread counts, concurrency and opening suite.
2. Completed W/D/L, score rate, Elo estimate and confidence interval.
3. Whether evidence came from an SPRT, fixed match or external gauntlet.
4. The code changes included in the release.
5. Resource asymmetry or calibration caveats.

Rejected experiments belong in a dated experiment log or the archived detailed
history, not in the accepted-release table.
