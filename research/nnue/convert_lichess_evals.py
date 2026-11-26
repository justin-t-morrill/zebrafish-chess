"""Stream Lichess cloud evaluations into Bullet text records.

The input is decompressed by zstd, so the 100+ GB JSONL representation is never
stored. The highest-depth qualifying one-PV score is selected, as recommended by
Lichess. Mate labels and very large centipawn scores are excluded.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from collections import Counter
from pathlib import Path


def phase(fen: str) -> str:
    board = fen.split(" ", 1)[0]
    non_pawn_material = sum(board.count(piece) for piece in "qQrRbBnN")
    if non_pawn_material <= 4:
        return "endgame"
    if non_pawn_material <= 10:
        return "late"
    return "opening_midgame"


def score_bucket(score: int) -> str:
    value = abs(score)
    if value < 50:
        return "000-049"
    if value < 150:
        return "050-149"
    if value < 300:
        return "150-299"
    if value < 600:
        return "300-599"
    return "600-2000"


def sample_value(fen: str, seed: str) -> float:
    digest = hashlib.blake2b((seed + fen).encode(), digest_size=8).digest()
    value = int.from_bytes(digest, "little")
    return value / float(1 << 64)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("archive", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--target", type=int, default=10_000_000)
    parser.add_argument("--sample-rate", type=float, default=0.04)
    parser.add_argument("--sample-min", type=float, default=0.0)
    parser.add_argument("--exclude-min", type=float)
    parser.add_argument("--exclude-max", type=float)
    parser.add_argument("--min-knodes", type=int, default=10_000)
    parser.add_argument("--max-abs-cp", type=int, default=2_000)
    parser.add_argument("--seed", default="minimal-chess-lichess-v1")
    parser.add_argument("--zstd", default=r"C:\msys64\ucrt64\bin\zstd.exe")
    args = parser.parse_args()

    args.output.parent.mkdir(parents=True, exist_ok=True)
    counts: Counter[str] = Counter()
    command = [args.zstd, "-dc", str(args.archive)]
    process = subprocess.Popen(command, stdout=subprocess.PIPE, text=True,
                               encoding="utf-8", errors="strict", bufsize=1024 * 1024)
    assert process.stdout is not None
    try:
        with args.output.open("w", encoding="utf-8", newline="\n") as output:
            for line_number, line in enumerate(process.stdout, 1):
                counts["read"] += 1
                if line_number % 1_000_000 == 0:
                    print(f"read={line_number:,} written={counts['written']:,}",
                          file=sys.stderr, flush=True)
                record = json.loads(line)
                fen = record["fen"]
                value = sample_value(fen, args.seed)
                if not (args.sample_min <= value < args.sample_rate):
                    continue
                if (args.exclude_min is not None and args.exclude_max is not None
                        and args.exclude_min <= value < args.exclude_max):
                    continue

                candidates = []
                for evaluation in record.get("evals", []):
                    pvs = evaluation.get("pvs", [])
                    if (evaluation.get("knodes", 0) >= args.min_knodes and pvs
                            and "cp" in pvs[0]):
                        candidates.append(evaluation)
                if not candidates:
                    counts["no_qualifying_eval"] += 1
                    continue
                best = max(candidates, key=lambda item: item.get("depth", -1))
                score = int(best["pvs"][0]["cp"])
                if abs(score) > args.max_abs_cp:
                    counts["extreme_score"] += 1
                    continue

                # Lichess analysis scores are White-relative. Bullet's chess
                # loader expects White-relative values as well.
                output.write(f"{fen} 0 1 | {score} | 0.5\n")
                counts[f"phase:{phase(fen)}"] += 1
                counts[f"score:{score_bucket(score)}"] += 1
                counts["written"] += 1
                if counts["written"] >= args.target:
                    break
    finally:
        if process.poll() is None:
            process.terminate()
        process.wait()

    print("Conversion summary")
    for key, value in sorted(counts.items()):
        print(f"  {key}: {value:,}")


if __name__ == "__main__":
    main()
