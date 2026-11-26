"""Estimate performance against fixed opponent ratings, resampling whole opening pairs."""
import argparse
import collections
import json
import math
import random
import re
from pathlib import Path


def performance(opponents, points):
    """Find the Elo rating whose expected sum of scores matches the observed sum."""
    games = sum(count for rating, count in opponents)
    if not games or not 0 <= points <= games:
        raise ValueError("Expected a nonempty match and a score between zero and its game count.")
    if points == 0:
        return -math.inf
    if points == games:
        return math.inf
    low = min(rating for rating, _ in opponents) - 4000
    high = max(rating for rating, _ in opponents) + 4000
    for _ in range(55):
        mid = (low + high) / 2
        expected = sum(count / (1 + 10 ** ((rating - mid) / 400)) for rating, count in opponents)
        if expected < points:
            low = mid
        else:
            high = mid
    return (low + high) / 2


def paired_performance(pool, draws=10000):
    by_opponent = []
    ratings = []
    for (_, rating), scores in sorted(pool.items()):
        if len(scores) % 2:
            raise ValueError("Each entry must contain complete opening pairs.")
        ratings.append((rating, len(scores)))
        by_opponent.append([white + black for white, black in zip(scores[::2], scores[1::2])])
    center = performance(ratings, sum(map(sum, by_opponent)))
    if any(len(pairs) < 2 for pairs in by_opponent):
        return center, None
    rng = random.Random(901124)
    totals = sorted(
        sum(sum(rng.choices(pairs, k=len(pairs))) for pairs in by_opponent)
        for _ in range(draws)
    )
    bounds = tuple(performance(ratings, totals[round(q * (draws - 1))]) for q in (.025, .975))
    return center, bounds


def complete_pairs(pgn, candidate):
    grouped = collections.defaultdict(dict)
    scores = {"1-0": 1., "1/2-1/2": .5, "0-1": 0.}
    for game in re.split(r"(?m)(?=^\[Event )", pgn.read_text(encoding="utf-8-sig", errors="replace")):
        tags = dict(re.findall(r'(?m)^\[(\w+) "(.*)"\]\s*$', game))
        if tags.get("Result") not in scores:
            continue
        if candidate not in (tags["White"], tags["Black"]):
            raise ValueError(f"Expected {candidate} in {pgn}")
        white = tags["White"] == candidate
        key = (tags["Round"], tags.get("FEN", "startpos"))
        if white in grouped[key]:
            raise ValueError(f"Duplicate color in round {key[0]} of {pgn}")
        score = scores[tags["Result"]]
        grouped[key][white] = score if white else 1 - score
    return [pair[color] for pair in grouped.values() if len(pair) == 2 for color in (True, False)]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("state", type=Path, help="Calibration state JSON containing opponent ratings and PGN paths")
    args = parser.parse_args()
    state = json.loads(args.state.read_text(encoding="utf-8-sig"))
    candidate = f"Engine {state['engine']} 64-bit 8CPU"
    pool = collections.defaultdict(list)
    for match in state["completed"]:
        pgn = Path(match["pgn"])
        if not pgn.exists():
            pgn = args.state.parent / pgn.name
        key = match["opponent"], match["ccrl_rating"]
        pool[key].extend(complete_pairs(pgn, candidate))
    games = sum(map(len, pool.values()))
    if games == 0:
        raise SystemExit("No complete opening pairs found.")
    for (name, rating), scores in pool.items():
        print(f"{name} ({rating})  {scores.count(1)} W / {scores.count(.5)} D / {scores.count(0)} L")
    center, interval = paired_performance(pool)
    if not math.isfinite(center):
        print(f"All {games} games had the same decisive outcome. This sample has no finite fitted rating.")
        return
    print(f"{candidate} local performance on the reference opponent scale: {center:.0f} from {games} games.")
    if interval:
        print(f"95% interval by resampling opening pairs within each opponent: {interval[0]:.0f} to {interval[1]:.0f}.")
        print("The interval covers match sampling. Reference ratings and hardware normalization add uncertainty.")


if __name__ == "__main__":
    main()
