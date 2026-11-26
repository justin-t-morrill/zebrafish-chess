"""Check whether a mixed qsearch fit survives the C engine's quantization."""

from __future__ import annotations

import argparse
from pathlib import Path

import fit_eval_2_2_groups_wdl as grouped
from evaluate_quantized_eval_fits import quantize, read_weights
from fit_eval_qsearch_mixed_wdl import load_rows


def setting(path: Path, name: str) -> float:
    prefix = name + "="
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith(prefix):
            return float(line.removeprefix(prefix))
    raise SystemExit(f"Missing {name}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("fit", type=Path)
    parser.add_argument("quiet", nargs=3, type=Path)
    parser.add_argument("qsearch", nargs=3, type=Path)
    args = parser.parse_args()
    quiet = load_rows(*args.quiet, "quiet")
    qsearch = load_rows(*args.qsearch, "qsearch")
    continuous = read_weights(args.fit)
    rounded = quantize(continuous)
    zero = [0.0] * grouped.PARAMETER_COUNT
    k = setting(args.fit, "sigmoid_k")
    midpoint = setting(args.fit, "sigmoid_midpoint_cp")
    print(f"Nonzero continuous={sum(v != 0 for v in continuous)}, "
          f"rounded={sum(v != 0 for v in rounded)}")
    print("rounded=" + ",".join(f"{v:g}" for v in rounded))
    for domain, rows in (("quiet", quiet), ("qsearch", qsearch)):
        for split in ("validation", "test"):
            data = [row for row in rows if row["split"] == split]
            before = grouped.metrics(data, zero, k, midpoint)[0]
            fitted = grouped.metrics(data, continuous, k, midpoint)[0]
            quantized = grouped.metrics(data, rounded, k, midpoint)[0]
            print(f"{domain}_{split}: {before:.9f}->{fitted:.9f} continuous; "
                  f"{quantized:.9f} rounded")


if __name__ == "__main__":
    main()
