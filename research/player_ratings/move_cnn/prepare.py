"""Create a compact, game-grouped, player-purged development dataset."""
import argparse
import csv
import hashlib
import json
import time
from collections import defaultdict
from pathlib import Path

import chess
import numpy as np

ENGINE_NAMES = ["best_mover_pawns", "played_mover_pawns", "loss", "best_depth",
                "played_depth", "score_span", "discovery", "error_discovery",
                "error_stability", "legal_moves"]


def stable(value):
    return int.from_bytes(hashlib.sha256(value.encode()).digest()[:8], "big")


def encode(row):
    board = chess.Board(row["fen"])
    move = chess.Move.from_uci(row["played_uci"])
    if not board.is_valid() or move not in board.legal_moves:
        raise ValueError("Invalid board or illegal move")
    if (row["color"] == "white") != board.turn:
        raise ValueError("Mover color mismatch")
    pieces = np.zeros(64, dtype=np.uint8)
    for square, piece in board.piece_map().items():
        pieces[square] = piece.piece_type + (0 if piece.color else 6)
    state = [int(board.turn), int(board.has_kingside_castling_rights(chess.WHITE)),
             int(board.has_queenside_castling_rights(chess.WHITE)),
             int(board.has_kingside_castling_rights(chess.BLACK)),
             int(board.has_queenside_castling_rights(chess.BLACK)),
             64 if board.ep_square is None else board.ep_square]
    def number(key):
        value = float(row.get(key) or 0)
        if not np.isfinite(value):
            raise ValueError(f"Nonfinite {key}")
        return value
    sign = 1 if board.turn else -1
    engine = [np.clip(sign * number("best_score_white_cp") / 100, -15, 15),
              np.clip(sign * number("played_score_white_cp") / 100, -15, 15),
              number("expected_score_loss"), number("best_depth") / 30,
              number("played_depth") / 30, np.clip(number("best_score_span_cp") / 100, -15, 15),
              number("best_move_discovery_depth") / 20,
              number("error_discovery_depth") / 20,
              number("error_stability_depth") / 20, number("legal_moves") / 70]
    return pieces, state, [move.from_square, move.to_square, move.promotion or 0], engine


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("source", type=Path)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--moves-per-player", type=int, default=12)
    p.add_argument("--shard-size", type=int, default=16384)
    p.add_argument("--validation-fraction", type=float, default=.15)
    a = p.parse_args()
    if a.output.exists() or not 0 < a.validation_fraction < 1 or min(a.moves_per_player, a.shard_size) < 1:
        raise ValueError("Use a new output directory and valid positive options")
    started = time.perf_counter()
    games, groups, seen = {}, defaultdict(list), set()
    with a.source.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            site = row["site"].strip()
            player, opponent = row["player"].lower(), row["opponent"].lower()
            if not site or not player or not opponent:
                raise ValueError("Missing game/player identity")
            people = frozenset((player, opponent))
            if len(people) != 2 or (site in games and games[site] != people):
                raise ValueError("Inconsistent game identity")
            games[site] = people
            key = (site, player, int(row["ply"]))
            if key in seen:
                raise ValueError(f"Duplicate move: {key}")
            seen.add(key)
            groups[site, player].append(row)
    validation = {s for s in games if stable("move-cnn-v1/" + s) / 2**64 < a.validation_fraction}
    held_players = set().union(*(games[s] for s in validation)) if validation else set()
    training = {s for s, people in games.items() if s not in validation and not people & held_players}
    train_players = set().union(*(games[s] for s in training)) if training else set()
    assert not train_players & held_players and not training & validation
    if not training or not validation:
        raise ValueError("Empty split")
    a.output.mkdir(parents=True)
    meta, shards, counts = [], [], {"train": 0, "validation": 0}
    arrays = defaultdict(list)
    def flush():
        if not arrays["board"]:
            return
        name = f"shard_{len(shards):04d}.npz"
        types = {"board": np.uint8, "state": np.uint8, "move": np.uint8,
                 "engine": np.float32, "rating": np.float32, "group": np.int32,
                 "split": np.uint8, "weight": np.float32}
        np.savez_compressed(a.output / name, **{k: np.asarray(v, dtype=types[k]) for k,v in arrays.items()})
        shards.append({"file": name, "moves": len(arrays["board"])})
        arrays.clear()
    for (site, player), rows in sorted(groups.items()):
        if site not in training | validation:
            continue
        rating = float(rows[0]["player_elo"])
        if not 800 <= rating < 2800 or any(float(r["player_elo"]) != rating for r in rows):
            raise ValueError("Invalid or inconsistent target rating")
        rows.sort(key=lambda r: int(r["ply"]))
        rows = [rows[i] for i in np.linspace(0, len(rows)-1, min(len(rows), a.moves_per_player), dtype=int)]
        split = int(site in validation)
        group = len(meta)
        meta.append({"site": site, "player": player, "rating": rating, "split": split, "moves": len(rows)})
        for row in rows:
            board, state, move, engine = encode(row)
            for name, value in dict(board=board, state=state, move=move, engine=engine,
                                    rating=rating, group=group, split=split, weight=1/len(rows)).items():
                arrays[name].append(value)
            counts["validation" if split else "train"] += 1
            if len(arrays["board"]) >= a.shard_size:
                flush()
    flush()
    digest = hashlib.sha256()
    with a.source.open("rb") as f:
        for block in iter(lambda: f.read(1024*1024), b""):
            digest.update(block)
    seconds = time.perf_counter() - started
    report = {"purpose": "reused July development pilot; not a fresh temporal test",
              "source": str(a.source.resolve()), "source_sha256": digest.hexdigest(),
              "source_games": len(games), "training_games": len(training),
              "validation_games": len(validation), "purged_games": len(games)-len(training)-len(validation),
              "player_overlap": len(train_players & held_players), "game_overlap": 0,
              "counts": counts, "engine_names": ENGINE_NAMES, "shards": shards,
              "seconds": seconds, "moves_per_second": sum(counts.values())/seconds,
              "moves_per_player": a.moves_per_player, "validation_fraction": a.validation_fraction}
    (a.output / "groups.json").write_text(json.dumps(meta), encoding="utf-8")
    (a.output / "manifest.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2), flush=True)


if __name__ == "__main__":
    main()
