#!/usr/bin/env python3
"""Extract engine W/D/L records from Cute Chess PGNs and report statistics."""

from __future__ import annotations

import re
import sys
import math
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from tournament_analysis import (  # noqa: E402
    MatchResult, analyze, format_number, print_report,
)


def read_result(path: Path, engine: str) -> MatchResult:
    """Return completed-game results for *engine* from one PGN file."""
    wins = losses = draws = 0
    tags: dict[str, str] = {}

    def consume() -> None:
        nonlocal wins, losses, draws
        if not tags or engine not in (tags.get("White"), tags.get("Black")):
            return
        result = tags.get("Result", "*")
        if result == "1/2-1/2":
            draws += 1
        elif (result == "1-0" and tags.get("White") == engine) or \
             (result == "0-1" and tags.get("Black") == engine):
            wins += 1
        elif result in ("1-0", "0-1"):
            losses += 1

    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        match = re.match(r'^\[([^ ]+) "(.*)"\]$', line)
        if not match:
            continue
        key, value = match.groups()
        if key == "Event" and tags:
            consume()
            tags = {}
        tags[key] = value
    consume()
    return MatchResult(wins=wins, losses=losses, draws=draws)


def print_gauntlet(engine: str, entries: list[str]) -> None:
    """Print one final compact statistical table for all gauntlet matches."""
    if not entries or len(entries) % 2:
        raise SystemExit("Gauntlet mode needs opponent/PGN pairs")

    print("\n\nFINAL GAUNTLET SUMMARY")
    print("=" * 124)
    print(f"{'Opponent':<24} {'G':>5} {'W':>5} {'D':>5} {'L':>5} "
          f"{'Score':>8} {'Elo diff':>10} {'95% Elo CI':>23} "
          f"{'p (2-sided)':>13} {'LOS':>9} {'Exact p':>11}")
    print("-" * 124)

    total_wins = total_losses = total_draws = 0
    rating_weight_sum = 0.0
    weighted_rating_sum = 0.0
    for index in range(0, len(entries), 2):
        opponent, filename = entries[index:index + 2]
        result = read_result(Path(filename), engine)
        if result.games == 0:
            raise SystemExit(f"No completed games found in {filename}")
        stats = analyze(result)
        total_wins += result.wins
        total_losses += result.losses
        total_draws += result.draws
        elo_ci = (f"{format_number(stats['elo_low'], 0)}.."
                  f"{format_number(stats['elo_high'], 0)}")
        los = stats["probability_superior"]
        los_text = "N/A" if los is None else f"{100.0 * float(los):.2f}%"
        print(f"{opponent:<24.24} {result.games:>5} {result.wins:>5} "
              f"{result.draws:>5} {result.losses:>5} "
              f"{100.0 * result.score_rate:>7.2f}% "
              f"{format_number(stats['elo'], 1):>10} {elo_ci:>23} "
              f"{format_number(stats['p_two_sided'], 6):>13} "
              f"{los_text:>9} "
              f"{format_number(stats['exact_decisive_p'], 6):>11}")

        # A limited-strength Stockfish label supplies an external rating
        # anchor. Combine the independently implied ratings using inverse
        # statistical variance; non-Stockfish engines remain in the table but
        # are excluded because they have no compatible numeric anchor.
        profile = re.fullmatch(r"Stockfish(\d+)", opponent)
        if profile:
            low = float(stats["elo_low"])
            high = float(stats["elo_high"])
            estimate = int(profile.group(1)) + float(stats["elo"])
            standard_error = (high - low) / (2.0 * 1.959963984540054)
            if standard_error > 0.0 and math.isfinite(standard_error) and \
                    math.isfinite(estimate):
                weight = 1.0 / (standard_error * standard_error)
                rating_weight_sum += weight
                weighted_rating_sum += weight * estimate

    print("-" * 124)
    total_games = total_wins + total_losses + total_draws
    total_score = total_wins + 0.5 * total_draws
    print(f"{'ALL OPPONENTS':<24} {total_games:>5} {total_wins:>5} "
          f"{total_draws:>5} {total_losses:>5} "
          f"{100.0 * total_score / total_games:>7.2f}%")
    if rating_weight_sum > 0.0:
        combined = weighted_rating_sum / rating_weight_sum
        standard_error = math.sqrt(1.0 / rating_weight_sum)
        radius = 1.959963984540054 * standard_error
        print(f"\nWeighted Stockfish-profile rating: {combined:.1f}")
        print(f"Statistical 95% interval:          "
              f"{combined - radius:.1f} to {combined + radius:.1f}")
        print("This interval excludes systematic error in Stockfish's UCI_Elo "
              "labels and does not represent a universal human/Lichess rating.")
    print("\nElo differences and significance are per opponent. Numeric "
          "Stockfish profiles also contribute to the weighted rating above.")


def main() -> None:
    if len(sys.argv) >= 5 and sys.argv[1] == "--gauntlet":
        print_gauntlet(sys.argv[2], sys.argv[3:])
        return
    if len(sys.argv) != 3:
        raise SystemExit(
            "Usage: summarize_pgn.py <games.pgn> <engine-name>\n"
            "   or: summarize_pgn.py --gauntlet <engine> <opponent> <pgn> ...")
    path = Path(sys.argv[1])
    engine = sys.argv[2]
    result = read_result(path, engine)
    if result.games == 0:
        raise SystemExit(f"No completed games found for {engine!r} in {path}")
    print_report(result, analyze(result), 0.95)


if __name__ == "__main__":
    main()
