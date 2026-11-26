# Zebrafish 9.1

Zebrafish 9.1 preserves the adaptive clock introduced in 9.0 and adds staged
move generation, root principal-variation search with verified reductions,
pawn correction history, optimized incremental NNUE, and four material heads
sharing a 256-neuron feature transformer.

| Clock against frozen 9.0 | Games | Wins / draws / losses | Score | Observed Elo | 0 versus +10 Elo SPRT |
|---|---:|---|---:|---:|---|
| 1 second + 0.1 seconds | 215 | 100 / 79 / 36 | 64.9% | +106.7 | H1, LLR +2.97 |
| 3 minutes + 1 second | 278 | 103 / 129 / 46 | 60.3% | +72.3 | H1, LLR +2.99 |

Both matches played color-reversed openings with one search thread, 64 MiB
hash and tablebases disabled. The last full external estimate is about 3110
CCRL Blitz 8CPU for 8.3. [The test report](../../../experiments/9.1-rc1/RESULTS.md)
records the component matches, uncertainty and external games.

From the repository root, build this frozen text and GUI release and start UCI:

```powershell
.\engines\versions\v9\source_9.1\build.ps1
.\engines\versions\v9\9.1.exe --uci
```

Keep `nnue-9.1.bin` beside either executable. Its SHA-256 is
`a45185364368524ff565a7d31e5b997553057dba6aea32985c72669b55a430c6`.
The working build also supports the local game-review interface and optional
move-ordering research settings. Those research settings default to off.
