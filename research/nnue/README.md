# Zebrafish NNUE training

## Material-head candidate

The 9.1 release candidate shares one Chess768 feature transformer across four
material ranges. The 256-neuron experiment warm-starts the transformer from the
accepted 8.3 optimizer checkpoint and duplicates its output weights into four
heads. From this directory, the following PowerShell commands reproduce the
training configuration. Set `$validation` to the held-out Lichess positions in
32-byte Bullet format.

```powershell
$base = "checkpoints/minimal-chess-768x256-lichessfull5ep-wdl000-40/optimiser_state/weights.bin"
python material_network.py expand $base four-init.bin
cargo run --release --bin material-heads -- data/lichess-evals/mixed-full-shuffled.data $validation four-init.bin checkpoints material-four 256 1536 40 0.00035
python material_network.py pack checkpoints/material-four-40/quantised.bin nnue-material.bin --width 256
```

[Candidate, network and match results](../../history/experiments/9.1-rc1/README.md)

For a 512-wide teacher initialized by duplicating 256 input channels,
`merge-pairs` combines channels 0 and 256, 1 and 257, and so on. Set
`$paired512Checkpoint` to the teacher's `optimiser_state/weights.bin`.
The merge uses NumPy. Fine-tuning uses the same 256-wide trainer and
evaluator as the original candidate.

```powershell
python material_network.py merge-pairs $paired512Checkpoint merged-init.bin
cargo run --release --bin material-heads -- data/lichess-evals/mixed-full-shuffled.data $validation merged-init.bin checkpoints merged256 256 1536 24 0.00025
python material_network.py pack checkpoints/merged256-24/quantised.bin nnue-merged.bin --width 256
```

## Single-head networks

The current accepted 8.3 network is the plain dual-perspective
`(768 -> 256) x 2 -> 1` SCReLU model. Its exported weights are included as
`engine/current/nnue-8.3.bin`; training is not required to run the engine.
The trainer supports plain hidden sizes 128, 256, and 512, plus experimental
`king10` models at 128 and 256. King-bucket candidates were not accepted for 8.3.

Run the examples below from `research/nnue/`. Install Rust and the GPU toolchain
required by the Bullet `rocm` dependency in Cargo.toml, plus Python dependencies
used by your data preparation scripts. Data, checkpoints, downloaded Python
packages, and Cargo build output are excluded from Git.

## Data

The historical Engine 5.0 Texel bootstrap corpus (not included) contained
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
evaluation. The current engine includes incremental accumulator updates.

The optional fourth argument is Bullet's game-result (WDL) blend. `0.0` trains
entirely on the qsearch score, while `1.0` trains entirely on the final game
result. This corpus defaults to `0.0`: its qsearch labels are substantially
cleaner teachers than outcomes from only 64,000 self-play games. Test a small
nonzero blend only after the score-only baseline is competitive.

## Trainer arguments

The positional arguments are training file, validation file, batches per
superbatch, WDL blend, hidden size, checkpoint tag, and architecture.
For example, using your prepared data files:

```powershell
cargo run --release -- data/train.data data/validation.data 337 0.0 256 experiment plain
```

Adjust the batch count to your dataset; 337 describes the earlier bootstrap
split, not the full 8.3 dataset. Tags may contain letters, digits, and hyphens.
The default hidden size is still 128, so specify 256 for the accepted model's
architecture. This example does not reproduce the accepted weights without the
original data and training conditions.
