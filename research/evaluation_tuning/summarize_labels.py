"""Validate and summarize a Stockfish-labeled evaluation dataset."""

from __future__ import annotations

import argparse
import csv
from collections import Counter
from pathlib import Path


def percentile(values: list[int], fraction: float) -> int:
    values = sorted(values)
    return values[round((len(values) - 1) * fraction)]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path)
    args = parser.parse_args()

    with args.input.open(newline="", encoding="utf-8") as source:
        rows = list(csv.DictReader(source))
    quiet = [row for row in rows if row.get("quiet") == "1"]
    labeled = [row for row in rows if row.get("wdl_win_white")]
    cp = [int(row["stockfish_cp_white"]) for row in quiet]

    duplicate_count = len(rows) - len({row["fen"] for row in rows})
    bad_wdl = sum(
        int(row["wdl_win_white"]) + int(row["wdl_draw_white"]) + int(row["wdl_loss_white"]) != 1000
        for row in labeled
    )

    print(f"Rows:              {len(rows)}")
    print(f"Quiet rows:        {len(quiet)} ({100 * len(quiet) / max(1, len(rows)):.2f}%)")
    print(f"Duplicate FENs:    {duplicate_count}")
    print(f"Missing WDL:       {len(rows) - len(labeled)}")
    print(f"Invalid WDL sums:  {bad_wdl}")
    print("Quiet phases:      " + ", ".join(f"{k}={v}" for k, v in sorted(Counter(r["phase"] for r in quiet).items())))
    print("Quiet splits:      " + ", ".join(f"{k}={v}" for k, v in sorted(Counter(r["split"] for r in quiet).items())))
    print("Outcomes:          " + ", ".join(
        f"{k or 'accepted'}={v}" for k, v in sorted(Counter(r.get("reject_reason", "") for r in rows).items())
    ))
    if cp:
        points = (0.00, 0.01, 0.10, 0.50, 0.90, 0.99, 1.00)
        print("Quiet CP percentiles: " + ", ".join(f"p{int(p * 100):02d}={percentile(cp, p):+d}" for p in points))


if __name__ == "__main__":
    main()
