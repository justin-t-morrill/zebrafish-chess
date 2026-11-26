# RatingNet retraining experiment

## Prepared data

`data/ratingnet_raw_multimonth.npz` contains 33,691 labelled Lichess blitz
games from April through July 2026. It was produced without engine analysis.
Positions use compact piece codes and are expanded into CNN planes by the
trainer. Clock values, missing-clock masks, time controls, player names,
dates, split labels, and both ratings are retained.

Rebuild it with:

```powershell
.\analysis\elo_estimator\prepare_ratingnet_data.ps1
```

## GPU status

GPU training is operational as of 2026-09-08:

- WSL 2.7.13 and Ubuntu 24.04 are installed.
- ROCm 7.2.4 and ROCDXG 1.2.2 are installed inside Ubuntu.
- The isolated Python environment is `/opt/ratingnet-venv`.
- PyTorch 2.9.1 + ROCm 7.2 recognizes the RX 7900 XTX as `gfx1100`.
- A RatingNet-like CNN + three-layer bidirectional LSTM completed five full
  forward, backward, and AdamW optimizer steps on the GPU in 19.3 seconds.

ROCm 7.2 under ROCDXG currently requires this environment variable:

```bash
export HSA_ENABLE_DXG_DETECTION=1
```

The next step is adapting the training/validation program to consume the
compact NPZ dataset, followed by a small end-to-end training smoke test.
