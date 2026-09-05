"""Verify a packaged Texel candidate against native engine evaluations.

The check compiles the native feature extractor against both source snapshots,
confirms that their feature streams are identical, and compares the fit's
linear prediction with the actual integer-evaluator score change.
"""
from __future__ import annotations

import argparse
import csv
import subprocess
import tempfile
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[2]
PAIR = np.dtype([("index", "<u2"), ("value", "<f4")])


def compile_extractor(engine: str, output: Path, header: Path) -> None:
    match = __import__("re").match(r"(\d+)", engine)
    bucket = f"v{match.group(1)}" if match else "misc"
    source = ROOT / "engines" / "versions" / bucket / f"source_{engine}" / "chess.c"
    if not source.exists():
        raise SystemExit(f"Missing saved engine source: {source}")
    include = source.relative_to(ROOT).as_posix()
    header.write_text(f'#define TEXEL_ENGINE_SOURCE "../{include}"\n', encoding="ascii")
    command = ["gcc", "-std=c11", "-O3", "-DNDEBUG", "-include", str(header),
               str(ROOT / "training" / "tuning" / "extract_eval_features.c"), "-o", str(output),
               "-lgdiplus", "-lgdi32", "-luser32"]
    subprocess.run(command, cwd=ROOT, check=True)


def rounded_fit(path: Path) -> np.ndarray:
    line = next((line for line in path.read_text(encoding="utf-8").splitlines()
                 if line.startswith("rounded=")), None)
    if line is None:
        raise SystemExit("Fit has no rounded vector")
    return np.asarray([float(value) for value in line[8:].split(",")], dtype=np.float64)


def sparse_rows(path: Path) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    with path.open("rb") as source:
        if source.read(8) != b"TXFTR001":
            raise SystemExit("Bad native feature stream")
        source.read(4)
    records = np.fromfile(path, dtype=PAIR, offset=12)
    endings = np.flatnonzero(records["index"] == 65535)
    previous = np.concatenate((np.array([-1], dtype=np.int64), endings[:-1]))
    lengths = endings - previous - 1
    offsets = np.empty(len(endings) + 1, dtype=np.int64)
    offsets[0] = 0
    np.cumsum(lengths, out=offsets[1:])
    keep = records["index"] != 65535
    return offsets, records["index"][keep], records["value"][keep]


def evals(path: Path) -> np.ndarray:
    with path.open(newline="", encoding="utf-8") as source:
        return np.asarray([int(row["eval_white"]) for row in csv.DictReader(source)],
                          dtype=np.float64)


def mirrored_fen(fen: str) -> str:
    fields = fen.split()
    fields[0] = "/".join(rank.swapcase() for rank in reversed(fields[0].split("/")))
    fields[1] = "b" if fields[1] == "w" else "w"
    fields[2] = ("".join({"K": "k", "Q": "q", "k": "K", "q": "Q"}[c]
                           for c in fields[2]) if fields[2] != "-" else "-")
    if fields[3] != "-":
        fields[3] = fields[3][0] + str(9 - int(fields[3][1]))
    return " ".join(fields)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("fit", type=Path)
    parser.add_argument("--base-engine", required=True)
    parser.add_argument("--candidate", required=True)
    parser.add_argument("--leaves", type=Path, required=True)
    parser.add_argument("--rows", type=int, default=10000)
    args = parser.parse_args()
    delta = rounded_fit(args.fit.resolve())
    with tempfile.TemporaryDirectory(prefix="texel_verify_") as temporary:
        temp = Path(temporary)
        outputs = {}
        executables = {}
        for engine in (args.base_engine, args.candidate):
            executable = temp / f"{engine}.exe"
            compile_extractor(engine, executable, temp / f"{engine}.h")
            executables[engine] = executable
            binary = temp / f"{engine}.bin"
            scores = temp / f"{engine}.csv"
            subprocess.run([str(executable), str(args.leaves.resolve()), str(binary),
                            str(scores), str(args.rows)], cwd=ROOT, check=True)
            outputs[engine] = (binary, scores)
        base_binary, base_scores = outputs[args.base_engine]
        candidate_binary, candidate_scores = outputs[args.candidate]
        if base_binary.read_bytes() != candidate_binary.read_bytes():
            raise SystemExit("Feature streams differ between base and candidate")
        offsets, indices, values = sparse_rows(base_binary)
        with args.leaves.open(newline="", encoding="utf-8") as source:
            sampled_fens = [row["fen"] for _, row in zip(range(len(offsets) - 1),
                                                           csv.DictReader(source))]
        mirror_input = temp / "mirrored.csv"
        with mirror_input.open("w", encoding="utf-8", newline="") as output:
            output.write("fen\n")
            for fen in sampled_fens:
                output.write(mirrored_fen(fen) + "\n")
        mirror_binary = temp / "mirrored.bin"
        subprocess.run([str(executables[args.base_engine]), str(mirror_input),
                        str(mirror_binary)], cwd=ROOT, check=True)
        moffsets, mindices, mvalues = sparse_rows(mirror_binary)
        if (not np.array_equal(offsets, moffsets) or
                not np.array_equal(indices, mindices) or
                not np.allclose(values, -mvalues, rtol=0, atol=1e-6)):
            for row in range(min(len(offsets), len(moffsets)) - 1):
                original = {int(i): float(v) for i, v in
                            zip(indices[offsets[row]:offsets[row + 1]],
                                values[offsets[row]:offsets[row + 1]])}
                mirrored = {int(i): float(v) for i, v in
                            zip(mindices[moffsets[row]:moffsets[row + 1]],
                                mvalues[moffsets[row]:moffsets[row + 1]])}
                bad = [(index, original.get(index, 0.0), mirrored.get(index, 0.0))
                       for index in sorted(set(original) | set(mirrored))
                       if abs(original.get(index, 0.0) + mirrored.get(index, 0.0)) > 1e-6]
                if bad:
                    print(f"mirror mismatch row={row} fen={sampled_fens[row]}")
                    print("index,original,mirrored=" + ", ".join(
                        f"{index}:{value:+.4f}/{mirror:+.4f}"
                        for index, value, mirror in bad[:20]))
                    break
            raise SystemExit("Native features fail color/vertical-mirror symmetry")
        predicted = np.zeros(len(offsets) - 1, dtype=np.float64)
        for row in range(len(predicted)):
            start, end = offsets[row], offsets[row + 1]
            valid = indices[start:end] < len(delta)
            predicted[row] = np.dot(values[start:end][valid], delta[indices[start:end][valid]])
        base_eval = evals(base_scores)
        candidate_eval = evals(candidate_scores)
        actual = candidate_eval - base_eval
        error = actual - predicted
        print(f"rows={len(actual)}")
        print(f"actual_delta_range={actual.min():.1f}..{actual.max():.1f}")
        print(f"linearization_mae={np.mean(np.abs(error)):.4f} cp")
        print(f"linearization_rmse={np.sqrt(np.mean(error * error)):.4f} cp")
        print(f"linearization_median_error={np.median(np.abs(error)):.4f} cp")
        print(f"linearization_p95_error={np.percentile(np.abs(error), 95):.4f} cp")
        print(f"linearization_max_error={np.max(np.abs(error)):.4f} cp")
        print(f"errors_over_10cp={np.count_nonzero(np.abs(error) > 10)}/{len(error)}")
        worst = np.argsort(np.abs(error))[-5:][::-1]
        for row in worst:
            start, end = offsets[row], offsets[row + 1]
            row_indices, row_values = indices[start:end], values[start:end]
            parts = []
            for label, lower, upper in (("pst", 0, 384), ("material", 384, 392),
                                        ("mobility", 392, 400), ("bishop", 400, 402),
                                        ("pawns", 402, 416), ("king", 418, 426),
                                        ("castling", 426, 428)):
                selected = (row_indices >= lower) & (row_indices < upper)
                amount = float(np.dot(row_values[selected], delta[row_indices[selected]]))
                if amount:
                    parts.append(f"{label}={amount:+.1f}")
            print(f"worst row={row} base={base_eval[row]:+.0f} candidate={candidate_eval[row]:+.0f} "
                  f"actual={actual[row]:+.1f} predicted={predicted[row]:+.1f} "
                  f"error={error[row]:+.1f} {' '.join(parts)} fen={sampled_fens[row]}")
        if np.median(np.abs(error)) > 3.0:
            raise SystemExit("Native fit/evaluator equivalence error exceeds 3 cp median")
        print("Native formulas, PST orientation, mirror symmetry, and packaged deltas verified.")


if __name__ == "__main__":
    main()
