# NNUE baseline

This is the first step of Bullet's recommended progression: a dual-perspective
`(768 -> 128) x 2 -> 1` network with SCReLU. It intentionally avoids king
buckets and extra layers until the baseline has been tested.

## Data

The existing Engine 5.0 Texel corpus is a good bootstrap dataset: it contains
6,867,145 qsearch leaf positions from 64,000 self-play games, including scores,
results, and game-level splits. Convert its CSV to Bullet text with:

```powershell
python .\prepare_data.py `
  ..\tuning\texel_runs\5.0_native_selfplay_all\leaves.csv .\data
```

This creates text records with one quiet position per line:

```text
<FEN> | <white-relative score in centipawns> | <white result: 0.0, 0.5, or 1.0>
```

Convert each text file with Bullet's `bullet-utils`, then shuffle the training
file. Keep validation separate. The first trainer argument is training data,
the second is validation data, and the optional third is batches per epoch.
For this corpus, `337` batches of 16,384 cover the 5,513,264 training rows once.

Avoid positions in check, book-opening duplicates, terminal positions, and
very large/mate scores. Use game results rather than deciding results from the
evaluation. Split test data by game, not by individual position.

## Train and load

Run `cargo run --release -- <train.data> <validation.data> 337 0.0` after installing
Rust and AMD's HIP SDK (the RX 7900 XTX uses Bullet's `rocm` backend). A checkpoint's `quantised.bin`
matches `nnue.c` exactly: little-endian i16 feature weights, feature bias,
output weights, and output bias. The file may include Bullet's trailing
64-byte padding.

Load it through UCI:

```text
setoption name EvalFile value C:\path\to\quantised.bin
```

Until a network loads successfully, the engine continues using its classical
evaluation. The initial implementation refreshes accumulators from the board;
incremental updates and SIMD belong after scalar output is cross-checked.

The optional fourth argument is Bullet's game-result (WDL) blend. `0.0` trains
entirely on the qsearch score, while `1.0` trains entirely on the final game
result. This corpus defaults to `0.0`: its qsearch labels are substantially
cleaner teachers than outcomes from only 64,000 self-play games. Test a small
nonzero blend only after the score-only baseline is competitive.
