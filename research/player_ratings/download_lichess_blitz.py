#!/usr/bin/env python3
"""Stream a balanced, labeled blitz sample from an official Lichess archive."""

from __future__ import annotations

import argparse
import csv
import io
import re
import sys
import urllib.request
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / "vendor_runtime"))
sys.path.insert(0, str(HERE / "runtime_access"))

try:
    import zstandard
except ImportError as error:
    raise SystemExit(
        "zstandard is missing. Run setup_elo_estimator.ps1 first."
    ) from error


DEFAULT_URL = (
    "https://database.lichess.org/standard/"
    "lichess_db_standard_rated_2026-07.pgn.zst"
)
TAG = re.compile(r'^\[([A-Za-z0-9_]+)\s+"(.*)"\]$')
PLY_TOKEN = re.compile(r"\b\d+\.(?:\.\.)?")


def pgn_games(lines):
    """Yield PGNs without assuming blank lines only separate games."""
    current: list[str] = []
    for line in lines:
        if line.startswith("[Event ") and current:
            yield "".join(current).strip() + "\n\n"
            current = []
        current.append(line)
    if current:
        yield "".join(current).strip() + "\n\n"


def headers_of(pgn: str) -> dict[str, str]:
    headers = {}
    for line in pgn.splitlines():
        match = TAG.match(line)
        if match:
            headers[match.group(1)] = match.group(2)
        elif headers and line.strip() and not line.startswith("["):
            break
    return headers


def approximate_plies(pgn: str) -> int:
    move_text = pgn[pgn.find("\n\n") + 2:]
    # Lichess normally supplies PlyCount. This fallback only needs to reject
    # extremely short games, so counting SAN tokens after move numbers is enough.
    cleaned = re.sub(r"\{[^}]*\}|\([^)]*\)|\d+\.(?:\.\.)?", " ", move_text)
    return sum(token not in {"1-0", "0-1", "1/2-1/2", "*"}
               for token in cleaned.split())


def accepted(headers: dict[str, str], pgn: str, args) -> tuple[bool, str, int, int]:
    if headers.get("Event") != "Rated Blitz game":
        return False, "", 0, 0
    if headers.get("Variant", "Standard") != "Standard":
        return False, "", 0, 0
    if headers.get("Result") not in {"1-0", "0-1", "1/2-1/2"}:
        return False, "", 0, 0
    if headers.get("WhiteTitle") == "BOT" or headers.get("BlackTitle") == "BOT":
        return False, "", 0, 0
    try:
        white = int(headers["WhiteElo"])
        black = int(headers["BlackElo"])
    except (KeyError, ValueError):
        return False, "", 0, 0
    if not (args.min_rating <= white <= args.max_rating and
            args.min_rating <= black <= args.max_rating):
        return False, "", 0, 0
    if abs(white - black) > args.max_rating_gap:
        return False, "", 0, 0
    try:
        plies = int(headers.get("PlyCount", ""))
    except ValueError:
        plies = approximate_plies(pgn)
    if not (args.min_plies <= plies <= args.max_plies):
        return False, "", 0, 0
    mean_rating = (white + black) // 2
    band_low = (mean_rating // args.band_width) * args.band_width
    return True, f"{band_low}-{band_low + args.band_width - 1}", white, black


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Create a balanced rated-blitz PGN sample from Lichess")
    parser.add_argument("--url", default=DEFAULT_URL)
    parser.add_argument("--output", type=Path,
                        default=Path(__file__).with_name("data") /
                        "lichess_blitz_balanced.pgn")
    parser.add_argument("--games-per-band", type=int, default=3000)
    parser.add_argument("--target-games", type=int, default=0,
                        help="Collect this many games with the natural rating distribution; "
                             "when set, games-per-band caps are disabled")
    parser.add_argument("--min-rating", type=int, default=800)
    parser.add_argument("--max-rating", type=int, default=2799)
    parser.add_argument("--band-width", type=int, default=200)
    parser.add_argument("--max-rating-gap", type=int, default=350)
    parser.add_argument("--min-plies", type=int, default=24)
    parser.add_argument("--max-plies", type=int, default=240)
    parser.add_argument("--max-games-per-player", type=int, default=20)
    parser.add_argument("--exclude-players", type=Path, action="append",
                        help="one-name-per-line exclusion list; may be supplied repeatedly")
    parser.add_argument("--progress-every", type=int, default=100000)
    args = parser.parse_args()
    if args.games_per_band < 1 or args.band_width < 1:
        parser.error("games-per-band and band-width must be positive")

    bands = [f"{low}-{low + args.band_width - 1}"
             for low in range((args.min_rating // args.band_width) * args.band_width,
                              args.max_rating + 1, args.band_width)]
    counts = Counter()
    players = Counter()
    excluded_players = set()
    if args.exclude_players:
        for path in args.exclude_players:
            lines=path.read_text(encoding="utf-8").splitlines()
            if lines and lines[0].casefold().startswith("player,"):
                excluded_players.update(row[0].strip().casefold() for row in
                                        csv.reader(lines[1:]) if row and row[0].strip())
            else:
                excluded_players.update(line.strip().casefold() for line in lines if line.strip())
    seen_sites: set[str] = set()
    scanned = 0
    kept = 0
    args.output.parent.mkdir(parents=True, exist_ok=True)
    metadata = args.output.with_suffix(".csv")
    print(f"Streaming: {args.url}", flush=True)
    print(f"Target: {args.games_per_band} games in each of {len(bands)} rating bands",
          flush=True)

    request = urllib.request.Request(args.url, headers={"User-Agent": "C-Engine-Elo-Dataset/1.0"})
    with urllib.request.urlopen(request, timeout=60) as response, \
         zstandard.ZstdDecompressor().stream_reader(response) as decompressed, \
         io.TextIOWrapper(decompressed, encoding="utf-8", errors="replace") as text, \
         args.output.open("w", encoding="utf-8", newline="\n") as pgn_out, \
         metadata.open("w", encoding="utf-8", newline="") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=[
            "game_index", "site", "utc_date", "white", "black", "white_elo",
            "black_elo", "result", "time_control", "termination", "eco",
            "opening", "rating_band"])
        writer.writeheader()
        for pgn in pgn_games(text):
            scanned += 1
            headers = headers_of(pgn)
            okay, band, white_elo, black_elo = accepted(headers, pgn, args)
            if (not args.target_games and okay and band in counts and
                    counts[band] >= args.games_per_band):
                okay = False
            elif okay and band not in bands:
                okay = False
            site = headers.get("Site", "")
            white_name = headers.get("White", "")
            black_name = headers.get("Black", "")
            if okay and (white_name.casefold() in excluded_players or
                         black_name.casefold() in excluded_players):
                okay = False
            if okay and (not site or site in seen_sites):
                okay = False
            if okay and (players[white_name] >= args.max_games_per_player or
                         players[black_name] >= args.max_games_per_player):
                okay = False
            if okay:
                kept += 1
                counts[band] += 1
                players[white_name] += 1
                players[black_name] += 1
                seen_sites.add(site)
                pgn_out.write(pgn)
                writer.writerow({
                    "game_index": kept, "site": site,
                    "utc_date": headers.get("UTCDate", headers.get("Date", "")),
                    "white": white_name, "black": black_name,
                    "white_elo": white_elo, "black_elo": black_elo,
                    "result": headers["Result"],
                    "time_control": headers.get("TimeControl", ""),
                    "termination": headers.get("Termination", ""),
                    "eco": headers.get("ECO", ""),
                    "opening": headers.get("Opening", ""),
                    "rating_band": band,
                })
            if scanned % args.progress_every == 0:
                status = " ".join(f"{name}:{counts[name]}" for name in bands)
                print(f"Scanned {scanned:,}; kept {kept:,} | {status}", flush=True)
            if ((args.target_games and kept >= args.target_games) or
                    (not args.target_games and
                     all(counts[name] >= args.games_per_band for name in bands))):
                break

    print(f"Complete: scanned {scanned:,}, kept {kept:,}", flush=True)
    print(f"PGN: {args.output.resolve()}", flush=True)
    print(f"Metadata: {metadata.resolve()}", flush=True)
    for band in bands:
        print(f"  {band}: {counts[band]:,}")
    if ((args.target_games and kept < args.target_games) or
            (not args.target_games and
             not all(counts[name] >= args.games_per_band for name in bands))):
        print("Warning: the stream ended before every rating band reached its target.",
              file=sys.stderr)


if __name__ == "__main__":
    main()
