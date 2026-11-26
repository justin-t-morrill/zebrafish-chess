"""Isolated CPU inference for the GUI; accepts review JSON on stdin."""
import json
import hashlib
import math
import sys
from pathlib import Path

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "src"))
from zebrafish.paths import resource
sys.path.insert(0, str(resource("ratingnet_runtime")))
sys.path.insert(0, str(resource("review_vendor")))
import chess
import numpy as np
import torch
from zebrafish.ratings.inference.ratingnet_runtime import load_checkpoint, infer


def encode_review(review, metadata):
    if not review.get("complete"):
        raise ValueError("Finish analyzing the game before estimating its rating.")
    headers = review.get("headers", {})
    if headers.get("Variant", "Standard").lower() not in ("standard", "chess"):
        raise ValueError("Rating estimation supports standard chess games.")
    tc = headers.get("TimeControl", "")
    if tc.isdigit():
        tc += "+0"
    if tc not in metadata["allowed_time_controls"]:
        raise ValueError("This estimator needs a supported blitz TimeControl in the PGN (for example 300+0).")
    rows = review["moves"]
    if len(rows) < metadata["minimum_plies"]:
        raise ValueError("At least 24 plies (12 moves by each player) are needed for a rating estimate.")
    if len(rows) > metadata["maximum_validated_plies"]:
        raise ValueError("This game is longer than the estimator's validated 240-ply range.")
    board = chess.Board()
    positions = np.zeros((1, 100, 64), np.uint8)
    clocks = np.full((1, 100), np.nan, np.float32)
    for index, row in enumerate(rows):
        if row["ply"] != index+1:
            raise ValueError("The review is missing moves; re-analyze the full game.")
        if row.get("fen_before"):
            recorded = chess.Board(row["fen_before"])
            if (recorded.board_fen(), recorded.turn, recorded.castling_rights) != (board.board_fen(), board.turn, board.castling_rights):
                raise ValueError("Rating estimation requires a consistent game from the standard starting position.")
        move = chess.Move.from_uci(row["uci"])
        if move not in board.legal_moves:
            raise ValueError("The review contains an illegal move; re-analyze the game.")
        board.push(move)
        if index < 100:
            for square, piece in board.piece_map().items():
                positions[0, index, square] = piece.piece_type + (0 if piece.color else 6)
            clock = row.get("clock_seconds")
            if clock is not None and math.isfinite(float(clock)) and float(clock) >= 0:
                clocks[0, index] = float(clock)
    length = min(100, len(rows))
    coverage = float(np.isfinite(clocks[0, :length]).mean())
    mode = "clock_available" if coverage == 1 else "clock_missing"
    if mode == "clock_missing":
        clocks[:] = np.nan
    control = np.array([[float(v) for v in tc.split("+")]], np.float32)
    return positions, clocks, control, np.array([length], np.int64), mode, coverage


def main():
    request = json.load(sys.stdin)
    release = resource("rating_models") / "releases/ratingnet_natural_v1"
    metadata = json.loads((release / "metadata.json").read_text())
    if hashlib.sha256((release / "ratingnet.pt").read_bytes()).hexdigest() != metadata["checkpoint_sha256"]:
        raise ValueError("The rating checkpoint does not match its calibrated release.")
    values = encode_review(request, metadata)
    torch.set_num_threads(4)
    model, mean, std = load_checkpoint(release / "ratingnet.pt")
    predictions = infer(model, mean, std, *values[:4], batch_size=1)[0]
    if not np.isfinite(predictions).all():
        raise ValueError("The rating model returned an invalid prediction.")
    print(json.dumps({"predictions": predictions.tolist(), "clock_mode": values[4],
                      "clock_coverage": values[5], "plies_used": int(values[3][0])}))


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(1)
