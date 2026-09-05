#!/usr/bin/env python3
"""Summarize a puzzle result CSV and prepare reproducible failure follow-ups."""

from __future__ import annotations

import argparse
import csv
import math
import statistics
from collections import Counter, defaultdict
from pathlib import Path


SOURCE_COLUMNS = [
    "PuzzleId", "FEN", "Moves", "Rating", "RatingDeviation", "Popularity",
    "NbPlays", "Themes", "GameUrl",
]
FOCUS_THEMES = {
    "quietMove", "defensiveMove", "zugzwang", "advancedPawn", "promotion",
    "pawnEndgame", "rookEndgame", "bishopEndgame", "knightEndgame",
    "trappedPiece", "clearance", "interference", "exposedKing",
    "kingsideAttack", "sacrifice",
}


def arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("results", type=Path)
    parser.add_argument("--sample-size", type=int, default=120)
    parser.add_argument("--output-directory", type=Path)
    return parser.parse_args()


def solved(row: dict[str, str]) -> bool:
    return row["Solved"].strip().lower() == "true"


def rate(rows: list[dict[str, str]]) -> float:
    return sum(solved(row) for row in rows) / len(rows) if rows else 0.0


def median_number(rows: list[dict[str, str]], column: str) -> float:
    values = [float(row[column]) for row in rows if row.get(column)]
    return statistics.median(values) if values else 0.0


def wilson_fail_interval(failures: int, total: int) -> tuple[float, float]:
    if not total:
        return 0.0, 0.0
    z = 1.959963984540054
    p = failures / total
    denominator = 1 + z * z / total
    center = (p + z * z / (2 * total)) / denominator
    spread = z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total)) / denominator
    return max(0.0, center - spread), min(1.0, center + spread)


def markdown_table(headers: list[str], rows: list[list[str]]) -> list[str]:
    return [
        "| " + " | ".join(headers) + " |",
        "|" + "|".join("---" for _ in headers) + "|",
        *("| " + " | ".join(row) + " |" for row in rows),
    ]


def select_balanced_sample(failures: list[dict[str, str]], size: int) -> list[dict[str, str]]:
    by_theme: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in failures:
        for theme in set(row["Themes"].split()) & FOCUS_THEMES:
            by_theme[theme].append(row)
    for values in by_theme.values():
        values.sort(key=lambda row: (-int(row["Rating"]), row["PuzzleId"]))

    chosen: list[dict[str, str]] = []
    seen: set[str] = set()
    ordered_themes = sorted(by_theme, key=lambda theme: (-len(by_theme[theme]), theme))
    cursor = Counter()
    while len(chosen) < min(size, len(failures)):
        added = False
        for theme in ordered_themes:
            values = by_theme[theme]
            while cursor[theme] < len(values) and values[cursor[theme]]["PuzzleId"] in seen:
                cursor[theme] += 1
            if cursor[theme] >= len(values):
                continue
            row = values[cursor[theme]]
            cursor[theme] += 1
            seen.add(row["PuzzleId"])
            chosen.append(row)
            added = True
            if len(chosen) >= size:
                break
        if not added:
            break

    if len(chosen) < size:
        remaining = sorted(failures, key=lambda row: (-int(row["Rating"]), row["PuzzleId"]))
        for row in remaining:
            if row["PuzzleId"] not in seen:
                chosen.append(row)
                seen.add(row["PuzzleId"])
                if len(chosen) >= size:
                    break
    return chosen


def main() -> None:
    args = arguments()
    with args.results.open(encoding="utf-8", newline="") as source:
        rows = list(csv.DictReader(source))
    if not rows:
        raise SystemExit("Result CSV is empty")

    failures = [row for row in rows if not solved(row)]
    successes = [row for row in rows if solved(row)]
    output = args.output_directory or args.results.parent
    output.mkdir(parents=True, exist_ok=True)
    stem = args.results.stem
    failure_suite = output / f"{stem}-failures.csv"
    sample_csv = output / f"{stem}-diagnostic-sample.csv"
    report = output / f"{stem}-analysis.md"

    with failure_suite.open("w", encoding="utf-8", newline="") as target:
        writer = csv.DictWriter(target, fieldnames=SOURCE_COLUMNS)
        writer.writeheader()
        writer.writerows({column: row[column] for column in SOURCE_COLUMNS} for row in failures)

    sample = select_balanced_sample(failures, args.sample_size)
    with sample_csv.open("w", encoding="utf-8", newline="") as target:
        writer = csv.DictWriter(target, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(sample)

    overall_fail = len(failures) / len(rows)
    theme_rows: list[list[str]] = []
    theme_groups: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        for theme in set(row["Themes"].split()) & FOCUS_THEMES:
            theme_groups[theme].append(row)
    ranked_themes = sorted(theme_groups, key=lambda theme: rate(theme_groups[theme]))
    for theme in ranked_themes:
        group = theme_groups[theme]
        misses = sum(not solved(row) for row in group)
        fail_rate = misses / len(group)
        low, high = wilson_fail_interval(misses, len(group))
        theme_rows.append([
            theme, f"{len(group):,}", f"{misses:,}", f"{fail_rate:.2%}",
            f"{fail_rate - overall_fail:+.2%}", f"{low:.2%}–{high:.2%}",
        ])

    rating_ranges = [
        ("<1600", -10**9, 1599), ("1600–1999", 1600, 1999),
        ("2000–2399", 2000, 2399), ("2400+", 2400, 10**9),
    ]
    rating_rows: list[list[str]] = []
    for label, low, high in rating_ranges:
        group = [row for row in rows if low <= int(row["Rating"]) <= high]
        misses = sum(not solved(row) for row in group)
        rating_rows.append([label, f"{len(group):,}", f"{misses:,}", f"{rate(group):.2%}"])

    pair_counts: Counter[tuple[str, str]] = Counter()
    for row in failures:
        themes = sorted(set(row["Themes"].split()) & FOCUS_THEMES)
        for index, first in enumerate(themes):
            for second in themes[index + 1:]:
                pair_counts[(first, second)] += 1
    pair_rows = [[f"{a} + {b}", f"{count:,}"] for (a, b), count in pair_counts.most_common(15)]

    lines = [
        f"# Puzzle analysis: {rows[0].get('Engine', 'engine')}", "",
        f"- Positions: **{len(rows):,}**",
        f"- Solved: **{len(successes):,} ({len(successes)/len(rows):.2%})**",
        f"- Failed: **{len(failures):,} ({overall_fail:.2%})**", "",
        "## Search-effort split", "",
        f"- Solved median depth/nodes: **{median_number(successes, 'Depth'):.0f} / {median_number(successes, 'Nodes'):,.0f}**",
        f"- Failed median depth/nodes: **{median_number(failures, 'Depth'):.0f} / {median_number(failures, 'Nodes'):,.0f}**",
        f"- Solved median elapsed: **{median_number(successes, 'ElapsedMs'):.1f} ms**",
        f"- Failed median elapsed: **{median_number(failures, 'ElapsedMs'):.1f} ms**", "",
        "## Rating bands", "",
        *markdown_table(["Rating", "Positions", "Misses", "Solve rate"], rating_rows), "",
        "## Themes ranked from weakest to strongest", "",
        "Excess failure compares each theme with the full-suite failure rate. The interval is a 95% Wilson interval.", "",
        *markdown_table(["Theme", "Positions", "Misses", "Failure", "Excess", "95% interval"], theme_rows), "",
        "## Most common theme combinations among failures", "",
        *markdown_table(["Combination", "Failures"], pair_rows), "",
        "## Follow-up files", "",
        f"- All failures for a slower rerun: `{failure_suite}`",
        f"- Balanced root-diagnostic sample ({len(sample)} positions): `{sample_csv}`",
    ]
    report.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(report)
    print(failure_suite)
    print(sample_csv)


if __name__ == "__main__":
    main()
