# Zebrafish 9.0

9.0 promotes the adaptive clock from commit `e906815e300b0368a759919d8069c61c43c06c62`.
The default build enables the tested policy and loads `nnue-8.3.bin`.

```powershell
.\engines\versions\v9\source_9.0\build.ps1
.\engines\versions\v9\9.0.exe --uci
```

Run these commands from the repository root. The build also produces
`engines/versions/v9/9.0_gui.exe` and copies the network beside both binaries.

With a live clock, the target starts at usable remaining time divided by moves
to go (20 by default), plus half the usable increment. A best-move change or a
score drop of at least 40 cp raises the target to 160%. Three consecutive depths
with the same best move and a latest score change within 15 cp lower it to 70%.
The principal worker compares the remaining target with the last iteration's
duration before starting another depth. The hard limit is the smaller of 2.5
times the base target and 80% of the usable clock. A forced move returns immediately.

The candidate scored 179 wins, 129 draws, and 104 losses against frozen 8.3
at 1+0.1. The final log-likelihood ratio was +2.95, above +2.94. The observed
gain was +64.0 Elo. [Match conditions and historical ratings](../../../ELO_HISTORY.md)
