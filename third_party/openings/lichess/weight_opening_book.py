#!/usr/bin/env python3
"""Evaluate and weight a position-based opening book with two UCI engines.

Stockfish decides whether a move is safe enough to remain selectable. Among
safe moves, a blend of Stockfish and the project's engine determines relative
weights. Rejected moves remain in the output with weight zero, preserving book
recognition and all replies after an opponent chooses one of those moves.

Analysis is cached by resulting position and is safe to resume. The output's
first three columns are consumed by the C engine; later columns are diagnostics.
"""

from __future__ import annotations

import argparse
import atexit
import csv
import json
import math
import multiprocessing as mp
import os
from pathlib import Path
import shutil
import time

import chess
import chess.engine


_stockfish: chess.engine.SimpleEngine | None = None
_engine: chess.engine.SimpleEngine | None = None
_sf_depth = 0
_our_depth = 0


def _close_engines() -> None:
    for engine in (_stockfish, _engine):
        if engine is not None:
            try:
                engine.quit()
            except Exception:
                pass


def _init_worker(stockfish: str, engine: str, sf_depth: int,
                 our_depth: int, hash_mb: int) -> None:
    global _stockfish, _engine, _sf_depth, _our_depth
    # Loading and validating the large TSV book happens before the candidate
    # answers `uci`. Concurrent workers can make that exceed python-chess's
    # short default startup timeout on slower disks.
    _stockfish = chess.engine.SimpleEngine.popen_uci(stockfish, timeout=60.0)
    _engine = chess.engine.SimpleEngine.popen_uci([engine, "--uci"], timeout=60.0)
    _sf_depth, _our_depth = sf_depth, our_depth
    if "Hash" in _stockfish.options:
        _stockfish.configure({"Hash": hash_mb, "Threads": 1})
    if "OwnBook" in _engine.options:
        _engine.configure({"OwnBook": False})
    atexit.register(_close_engines)


def _white_score(engine: chess.engine.SimpleEngine, board: chess.Board,
                 depth: int) -> int:
    outcome = board.outcome(claim_draw=True)
    if outcome is not None:
        if outcome.winner is None:
            return 0
        return 100_000 if outcome.winner == chess.WHITE else -100_000
    info = engine.analyse(board, chess.engine.Limit(depth=depth))
    if "score" not in info:
        raise RuntimeError(f"UCI engine returned no score for {board.fen()}: {info}")
    return info["score"].pov(chess.WHITE).score(mate_score=100_000)


def _analyse(fen: str) -> tuple[str, int, int]:
    assert _stockfish is not None and _engine is not None
    board = chess.Board(fen)
    return (fen, _white_score(_stockfish, board, _sf_depth),
            _white_score(_engine, board, _our_depth))


def _load_cache(path: Path, signature: dict[str, object]) -> dict[str, tuple[int, int]]:
    if not path.exists():
        return {}
    raw = json.loads(path.read_text(encoding="utf-8"))
    if "scores" in raw:
        if raw.get("meta") != signature:
            raise SystemExit(
                f"Cache settings do not match this run: {path}\n"
                "Use a different --cache path or remove the old cache.")
        raw = raw["scores"]
    else:
        print("Migrating legacy cache without embedded settings; ensure its depths "
              "and engines match this run.")
    return {fen: (int(scores[0]), int(scores[1]))
            for fen, scores in raw.items()}


def _save_cache(path: Path, cache: dict[str, tuple[int, int]],
                signature: dict[str, object]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps({"meta": signature, "scores": cache},
                                    separators=(",", ":")),
                         encoding="utf-8")
    temporary.replace(path)


def parse_args() -> argparse.Namespace:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(
        formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    parser.add_argument("--input", type=Path,
                        default=root / "opening_data" / "OpeningBook.tsv")
    parser.add_argument("--output", type=Path,
                        default=root / "opening_data" / "OpeningBookWeighted.tsv")
    parser.add_argument("--cache", type=Path,
                        default=root / "opening_data" / "opening_evaluations.json")
    parser.add_argument("--install", type=Path,
                        help="also copy the completed output to this engine book path")
    parser.add_argument("--stockfish", type=Path, default=root /
        "reference_engines/stockfish/stockfish/stockfish-windows-x86-64.exe")
    parser.add_argument("--engine", type=Path,
                        default=root / "engine_versions/6.3_opening_book.exe")
    parser.add_argument("--stockfish-depth", type=int, default=14)
    parser.add_argument("--engine-depth", type=int, default=8)
    parser.add_argument("--workers", type=int, default=min(6, os.cpu_count() or 1))
    parser.add_argument("--hash-mb", type=int, default=32,
                        help="Stockfish hash per worker")
    parser.add_argument("--weak-threshold", type=int, default=80,
                        help="zero weight at this Stockfish loss in centipawns")
    parser.add_argument("--rare-game-threshold", type=int, default=5,
                        help="moves with fewer games than this are considered rare")
    parser.add_argument("--rare-weak-threshold", type=int, default=25,
                        help="zero rare moves at this Stockfish loss in centipawns")
    parser.add_argument("--white-eval-floor", type=int, default=-40,
                        help="zero White book moves resulting in a lower Stockfish score")
    parser.add_argument("--black-eval-ceiling", type=int, default=140,
                        help="zero Black book moves resulting in a higher Stockfish score")
    parser.add_argument("--temperature", type=float, default=35.0,
                        help="centipawn loss producing an e-fold weight reduction")
    parser.add_argument("--stockfish-share", type=float, default=0.75,
                        help="Stockfish fraction of the safe-move weighting blend")
    parser.add_argument("--popularity-exponent", type=float, default=0.5,
                        help="strength of relative game-frequency weighting")
    parser.add_argument("--performance-strength", type=float, default=0.15,
                        help="small WDL score-rate multiplier strength")
    parser.add_argument("--database-prior", type=float, default=8.0,
                        help="draw-equivalent games used to smooth database data")
    parser.add_argument("--max-weight", type=int, default=1000)
    parser.add_argument("--checkpoint-every", type=int, default=100)
    parser.add_argument("--limit", type=int, default=0,
                        help="analyse only this many uncached positions (smoke tests)")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    for executable in (args.stockfish, args.engine):
        if not executable.exists():
            raise SystemExit(f"Engine not found: {executable}")
    if not 0.0 <= args.stockfish_share <= 1.0:
        raise SystemExit("--stockfish-share must be between 0 and 1")
    if (args.weak_threshold <= 0 or args.rare_game_threshold < 0 or
            args.rare_weak_threshold <= 0 or args.temperature <= 0 or
            args.max_weight <= 0):
        raise SystemExit("threshold, temperature, and maximum weight must be positive")
    if args.popularity_exponent < 0 or args.performance_strength < 0 or args.database_prior < 0:
        raise SystemExit("database weighting parameters cannot be negative")

    rows: list[dict[str, str]] = []
    child_fens: set[str] = set()
    with args.input.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle, delimiter="\t"):
            board = chess.Board(row["fen"])
            move = chess.Move.from_uci(row["move"])
            if move not in board.legal_moves:
                raise SystemExit(f"Illegal input move {move} in {row['fen']}")
            board.push(move)
            row["child_fen"] = board.fen(en_passant="legal")
            rows.append(row)
            child_fens.add(row["child_fen"])

    def engine_identity(path: Path) -> dict[str, object]:
        stat = path.stat()
        return {"path": str(path.resolve()), "size": stat.st_size,
                "modified_ns": stat.st_mtime_ns}

    signature = {
        "stockfish": engine_identity(args.stockfish),
        "engine": engine_identity(args.engine),
        "stockfish_depth": args.stockfish_depth,
        "engine_depth": args.engine_depth,
    }
    cache = _load_cache(args.cache, signature)
    pending = sorted(child_fens - cache.keys())
    if args.limit:
        pending = pending[:args.limit]
    print(f"Book rows: {len(rows)}; unique child positions: {len(child_fens)}")
    print(f"Cached: {len(child_fens & cache.keys())}; remaining this run: {len(pending)}")
    started = time.monotonic()
    if pending:
        context = mp.get_context("spawn")
        with context.Pool(
            processes=args.workers, initializer=_init_worker,
            initargs=(str(args.stockfish.resolve()), str(args.engine.resolve()),
                      args.stockfish_depth, args.engine_depth, args.hash_mb)
        ) as pool:
            for completed, (fen, sf_cp, our_cp) in enumerate(
                    pool.imap_unordered(_analyse, pending), 1):
                cache[fen] = (sf_cp, our_cp)
                if completed % args.checkpoint_every == 0 or completed == len(pending):
                    _save_cache(args.cache, cache, signature)
                    elapsed = time.monotonic() - started
                    rate = completed / elapsed if elapsed else 0.0
                    eta = (len(pending) - completed) / rate if rate else 0.0
                    print(f"Analysed {completed}/{len(pending)}; "
                          f"{rate:.2f} positions/s; ETA {eta / 60:.1f} min")

    unavailable = child_fens - cache.keys()
    if unavailable:
        print(f"Partial run: {len(unavailable)} positions remain; weights not written yet.")
        return
    _save_cache(args.cache, cache, signature)

    # Scores are White-relative. Convert them to the parent mover's perspective
    # before comparing sibling moves from the same position.
    by_parent: dict[str, list[dict[str, str]]] = {}
    for row in rows:
        by_parent.setdefault(row["fen"], []).append(row)

    weighted: list[dict[str, object]] = []
    zero_count = 0
    rare_weak_count = 0
    absolute_guard_count = 0
    for fen, siblings in by_parent.items():
        mover_sign = 1 if chess.Board(fen).turn == chess.WHITE else -1
        max_games = max(int(row.get("games", 0) or 0) for row in siblings)
        values = []
        for row in siblings:
            sf_cp, our_cp = cache[row["child_fen"]]
            values.append((row, sf_cp, our_cp,
                           mover_sign * sf_cp, mover_sign * our_cp))
        best_sf = max(value[3] for value in values)
        best_ours = max(value[4] for value in values)
        for row, sf_cp, our_cp, sf_mover, our_mover in values:
            sf_loss = best_sf - sf_mover
            our_loss = best_ours - our_mover
            blended_loss = (args.stockfish_share * sf_loss +
                            (1.0 - args.stockfish_share) * our_loss)
            games = int(row.get("games", 0) or 0)
            wins = int(row.get("wins", 0) or 0)
            draws = int(row.get("draws", 0) or 0)
            losses = int(row.get("losses", 0) or 0)
            if max_games > 0:
                popularity = ((games + args.database_prior) /
                              (max_games + args.database_prior)) ** args.popularity_exponent
            else:
                popularity = 1.0
            smoothed_score = ((wins + 0.5 * draws + 0.5 * args.database_prior) /
                              (games + args.database_prior)) if games + args.database_prior else 0.5
            performance = math.exp(args.performance_strength *
                                   2.0 * (smoothed_score - 0.5))
            rare_and_weak = (games < args.rare_game_threshold and
                             sf_loss >= args.rare_weak_threshold)
            absolute_guard = ((mover_sign > 0 and sf_cp < args.white_eval_floor) or
                              (mover_sign < 0 and sf_cp > args.black_eval_ceiling))
            if sf_loss >= args.weak_threshold or rare_and_weak or absolute_guard:
                weight = 0
                zero_count += 1
                if rare_and_weak and sf_loss < args.weak_threshold:
                    rare_weak_count += 1
                if (absolute_guard and sf_loss < args.weak_threshold and
                        not rare_and_weak):
                    absolute_guard_count += 1
            else:
                weight = max(1, min(args.max_weight, round(
                    args.max_weight * math.exp(-max(0.0, blended_loss) /
                                               args.temperature) *
                    popularity * performance)))
            weighted.append({
                "fen": fen, "move": row["move"], "weight": weight,
                "stockfish_cp": sf_cp, "engine_cp": our_cp,
                "stockfish_loss": sf_loss, "engine_loss": our_loss,
                "blended_loss": f"{blended_loss:.2f}",
                "games": games, "wins": wins, "draws": draws,
                "losses": losses, "database_score": f"{smoothed_score:.4f}",
                "popularity_factor": f"{popularity:.4f}",
                "performance_factor": f"{performance:.4f}",
            })

    args.output.parent.mkdir(parents=True, exist_ok=True)
    fields = ("fen", "move", "weight", "stockfish_cp", "engine_cp",
              "stockfish_loss", "engine_loss", "blended_loss", "games",
              "wins", "draws", "losses", "database_score",
              "popularity_factor", "performance_factor")
    with args.output.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fields, delimiter="\t",
                                lineterminator="\n")
        writer.writeheader()
        writer.writerows(sorted(weighted, key=lambda row: (row["fen"], row["move"])))
    print(f"Wrote {len(weighted)} weighted moves to {args.output}")
    print(f"Selectable: {len(weighted) - zero_count}; retained with zero weight: {zero_count}")
    print(f"New rare-and-weak rejections: {rare_weak_count}")
    print(f"Additional absolute-evaluation rejections: {absolute_guard_count}")
    if args.install:
        args.install.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(args.output, args.install)
        print(f"Installed completed book at {args.install}")


if __name__ == "__main__":
    mp.freeze_support()
    main()
