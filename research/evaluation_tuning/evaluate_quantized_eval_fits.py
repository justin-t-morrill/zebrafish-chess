"""Evaluate integer/tenths-quantized versions of Engine 2.2 WDL fits."""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

import chess

import fit_eval_2_2_groups_wdl as grouped
import fit_joint_wdl as joint
from fit_eval_wdl import calibrate


def read_weights(path: Path) -> list[float]:
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("weights="):
            return [float(value) for value in line.removeprefix("weights=").split(",")]
    raise SystemExit(f"No weights line in {path}")


def quantize(weights: list[float]) -> list[float]:
    result = []
    for index, value in enumerate(weights):
        if joint.MOB_MG <= index < joint.BISHOP_PAIR_MG:
            result.append(round(value, 1))  # engine stores mobility tenths
        else:
            result.append(float(round(value)))
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("labels", type=Path)
    parser.add_argument("baseline", type=Path)
    parser.add_argument("pawn_features", type=Path)
    parser.add_argument("fits", nargs="+", type=Path)
    args = parser.parse_args()
    with args.labels.open(newline="", encoding="utf-8") as source: labels = list(csv.DictReader(source))
    with args.baseline.open(newline="", encoding="utf-8") as source: baselines = list(csv.DictReader(source))
    with args.pawn_features.open(newline="", encoding="utf-8") as source: pawns = list(csv.DictReader(source))
    rows = []
    for number, (label, baseline, pawn) in enumerate(zip(labels, baselines, pawns), 1):
        board = chess.Board(label["fen"])
        features = joint.position_features(board, [float(pawn[f"f{i}"]) for i in range(14)])
        rows.append({"split": label["split"], "phase": label["phase"],
                     "engine": float(baseline["engine_eval_white"]),
                     "target": (float(label["wdl_win_white"]) + .5 * float(label["wdl_draw_white"])) / 1000,
                     "features": features + grouped.added_features(board)})
        if number % 30000 == 0: print(f"Features {number}/{len(labels)}", flush=True)
    train = [row for row in rows if row["split"] == "train"]
    k, midpoint = calibrate(train)
    zero = [0.0] * grouped.PARAMETER_COUNT
    for fit in args.fits:
        continuous = read_weights(fit)
        rounded = quantize(continuous)
        print(f"\n{fit.name}")
        print(f"Nonzero parameters: continuous={sum(v != 0 for v in continuous)}, rounded={sum(v != 0 for v in rounded)}")
        for split in ("validation", "test"):
            data = [row for row in rows if row["split"] == split]
            before = grouped.metrics(data, zero, k, midpoint)[0]
            fitted = grouped.metrics(data, continuous, k, midpoint)[0]
            quantized = grouped.metrics(data, rounded, k, midpoint)[0]
            print(f"{split:10s} Brier {before:.9f}->{fitted:.9f} continuous; {quantized:.9f} rounded")


if __name__ == "__main__": main()
