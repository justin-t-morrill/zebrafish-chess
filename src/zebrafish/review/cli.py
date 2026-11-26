"""Low-CPU command-line tools for creating and inspecting review jobs."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from zebrafish.review.annotate import render_annotated_pgn
from zebrafish.review.models import AnalysisSettings, ClassicalBreakdown, GameReview
from zebrafish.review.pgn_source import read_pgn_games
from zebrafish.review.scoring import summarize_player
from zebrafish.review.storage import load_review, save_review


def _new_review(pgn_path: str | Path, output: str | Path, *, game_number: int,
                engine: str, nodes: int, multipv: int,
                threads: int) -> GameReview:
    games = read_pgn_games(pgn_path)
    if not games:
        raise SystemExit("No PGN games found")
    if game_number < 1 or game_number > len(games):
        raise SystemExit(f"--game must be from 1 to {len(games)}")
    game = games[game_number - 1]
    review = GameReview(
        source_pgn=str(Path(pgn_path).resolve()),
        source_game_index=game_number,
        headers=game.headers,
        settings=AnalysisSettings(
            engine_version=engine,
            nodes_per_position=nodes,
            multipv=multipv,
            threads=threads,
        ),
    )
    save_review(review, output)
    return review


def command_init(args: argparse.Namespace) -> None:
    games = read_pgn_games(args.pgn)
    _new_review(args.pgn, args.output, game_number=args.game,
                engine=args.engine, nodes=args.nodes, multipv=args.multipv,
                threads=args.threads)
    print(f"Created review job for game {args.game}/{len(games)}: {Path(args.output).resolve()}")
    print("The engine-analysis stage is intentionally not active yet.")


def _read_pasted_pgn() -> str:
    print("Paste the complete PGN below.")
    print("When finished, enter END on a line by itself:")
    lines: list[str] = []
    while True:
        try:
            line = input()
        except EOFError:
            break
        if line.strip() == "END":
            break
        lines.append(line)
    text = "\n".join(lines).strip()
    if not text:
        raise SystemExit("No PGN was pasted")
    return text + "\n"


def command_summary(args: argparse.Namespace) -> None:
    review = load_review(args.review)
    if getattr(args, "threads", None) is not None:
        if not 1 <= args.threads <= 16:
            raise SystemExit("--threads must be from 1 through 16")
        review.settings.threads = args.threads
        save_review(review, args.review)
    previous = review.players
    review.players = {"white": summarize_player(review.moves, "white"),
                      "black": summarize_player(review.moves, "black")}
    for color, summary in review.players.items():
        old = previous.get(color)
        if old is not None:
            summary.estimated_performance_elo = old.estimated_performance_elo
            summary.elo_interval_low = old.elo_interval_low
            summary.elo_interval_high = old.elo_interval_high
            summary.elo_evidence_quality = old.elo_evidence_quality
            summary.elo_model_version = old.elo_model_version
            summary.elo_details = old.elo_details
    if args.update:
        save_review(review, args.review)
    print(json.dumps({
        "source": review.source_pgn,
        "event": review.headers.get("Event", "?"),
        "players": {color: {
            "accuracy": summary.accuracy,
            "average_expected_score_loss": summary.average_expected_score_loss,
            "informative_moves": summary.informative_moves,
            "classifications": summary.classifications,
            "performance_elo": summary.estimated_performance_elo,
            "performance_range": [summary.elo_interval_low, summary.elo_interval_high],
            "evidence_quality": summary.elo_evidence_quality,
            "elo_model_version": summary.elo_model_version,
        } for color, summary in review.players.items()},
        "completed_plies": review.completed_plies,
        "complete": review.complete,
    }, indent=2))


def command_performance_elo(args: argparse.Namespace) -> None:
    from zebrafish.ratings.performance_elo import estimate_review
    review = load_review(args.review)
    review.players = {"white": summarize_player(review.moves, "white"),
                      "black": summarize_player(review.moves, "black")}
    try:
        estimates = estimate_review(review, args.model_dir)
    except ValueError as error:
        raise SystemExit(str(error)) from error
    for color, estimate in estimates.items():
        summary = review.players[color]
        summary.estimated_performance_elo = estimate["performance_elo"]
        summary.elo_interval_low = estimate["range_low"]
        summary.elo_interval_high = estimate["range_high"]
        summary.elo_evidence_quality = estimate["evidence_quality"]
        summary.elo_model_version = estimate.get("model_version", "")
        summary.elo_details = estimate
        scale = estimate.get("rating_scale", "legacy model scale")
        print(f"{color.title()} estimated rating: {estimate['performance_elo']} {scale} "
              f"(90% estimated range {estimate['range_low']}-{estimate['range_high']})")
        for skill, item in estimate.get("categories", {}).items():
            print(f"  {skill.title()}: {item['summary']}")
    if not estimates:
        print("Not enough moves for a rating estimate.")
    if args.update:
        save_review(review, args.review)


def command_export(args: argparse.Namespace) -> None:
    review = load_review(args.review)
    Path(args.output).write_text(render_annotated_pgn(review), encoding="utf-8")
    print(f"Annotated PGN: {Path(args.output).resolve()}")


def command_analyze(args: argparse.Namespace) -> None:
    # Imported lazily so init/summary/export remain dependency-free.
    from zebrafish.review.analyzer import analyze_review

    if args.depth is not None and args.depth < 1:
        raise SystemExit("--depth must be at least 1")
    if args.nodes is not None and args.nodes < 1:
        raise SystemExit("--nodes must be at least 1")
    if args.time is not None and args.time <= 0:
        raise SystemExit("--time must be greater than zero")
    if args.movetime is not None and args.movetime < 1:
        raise SystemExit("--movetime must be at least 1 millisecond")
    review = load_review(args.review)
    from zebrafish.review.classical import format_components

    def print_move(record) -> None:
        def score(value) -> str:
            return "unavailable" if value is None else f"{value / 100:+.2f}"

        def line(moves) -> str:
            return " ".join(moves) if moves else "(none)"

        def endpoint_note(delta, used_full, had_stability) -> str:
            if delta is None:
                agreement = "root-score comparison unavailable"
            elif delta <= review.settings.explanation_score_tolerance_cp:
                agreement = f"within {delta / 100:.2f} of the root NNUE score"
            else:
                agreement = (f"still differs from the root NNUE score by "
                             f"{delta / 100:.2f}")
            if not had_stability:
                return ("full-PV fallback because no stable prefix was found; "
                        + agreement)
            if used_full:
                return ("extended to the full available PV; "
                        + agreement)
            return "shortest stable-supported match; " + agreement

        prefix = f"{record.move_number}." if record.mover == "white" else f"{record.move_number}..."
        print(f"\n{prefix} {record.san}  {record.classification}  "
              f"NNUE {score(record.evaluation_after_cp)}")
        print(f"Best Move: {record.best_move_san or record.best_move_uci}  "
              f"NNUE {score(record.evaluation_before_cp)}")
        print("Full Best Line: " + line(record.full_best_pv_san))
        best_explainable = record.stable_best_pv_san + record.qsearch_pv_san
        if record.stability.stable:
            print("Evaluation-Preserving Best Line With Qsearch: " +
                  line(best_explainable))
            method = "robust consensus" if record.stability.consensus else "strict"
            print(f"Best-line depths: discovered {record.stability.discovery_depth}, "
                  f"stable {record.stability.stability_depth}, "
                  f"verified {record.stability.verification_depth} ({method})")
        else:
            print("Shortened Stable Best Line: not established by this search")
            print("Full-PV Fallback Best Line With Qsearch: " +
                  line(best_explainable))
            if len(record.iterations) >= review.settings.stability_iterations:
                print(f"Best-line depths: discovered "
                      f"{record.stability.discovery_depth}, not stabilized, "
                      f"verified {record.stability.verification_depth}")
            else:
                print(f"Best-line depth: verified "
                      f"{record.stability.verification_depth}; stability needs "
                      "multiple iteration results")
        print("Best explanation endpoint: NNUE " +
              score(record.qsearch_score_cp) + "; " +
              endpoint_note(record.best_explanation_score_delta_cp,
                            record.best_explanation_used_full_pv,
                            record.stability.stable))
        if record.best_classical is not None:
            print(f"Ending Position From Best Move - Explainable Evaluation "
                  f"{record.best_classical.total / 100:+.2f}. This comes from: "
                  f"{format_components(record.best_classical)}")
        for fact in record.explanation_facts:
            print("  " + fact)

        print("Full Best Response to Your Move: " +
              line(record.full_response_pv_san))
        response_explainable = (record.stable_response_pv_san +
                                record.response_qsearch_pv_san)
        if record.response_stability.stable:
            print("Evaluation-Preserving Response With Qsearch: " +
                  line(response_explainable))
            method = ("robust consensus" if record.response_stability.consensus
                      else "strict")
            print(f"Response depths: discovered "
                  f"{record.response_stability.discovery_depth}, stable "
                  f"{record.response_stability.stability_depth}, verified "
                  f"{record.response_stability.verification_depth} ({method})")
        else:
            print("Shortened Stable Response: not established by this search")
            print("Full-PV Fallback Response With Qsearch: " +
                  line(response_explainable))
            if len(record.response_iterations) >= review.settings.stability_iterations:
                print(f"Response depths: discovered "
                      f"{record.response_stability.discovery_depth}, not stabilized, "
                      f"verified {record.response_stability.verification_depth}")
            else:
                print(f"Response depth: verified "
                      f"{record.response_stability.verification_depth}; stability "
                      "needs multiple iteration results")
        print("Response explanation endpoint: NNUE " +
              score(record.response_qsearch_score_cp) + "; " +
              endpoint_note(record.response_explanation_score_delta_cp,
                            record.response_explanation_used_full_pv,
                            record.response_stability.stable))
        if record.played_classical is not None:
            print(f"Ending Position From Your Move - Explainable Evaluation "
                  f"{record.played_classical.total / 100:+.2f}. This comes from: "
                  f"{format_components(record.played_classical)}")
        for fact in record.played_explanation_facts:
            print("  " + fact)

        same_move = record.uci == record.best_move_uci
        if same_move:
            print("Why the engine prefers its move: the played move is the "
                  "engine's best move; there is no alternative-move loss.")
        elif (record.evaluation_before_cp is not None and
                record.evaluation_after_cp is not None):
            direction = 1 if record.mover == "white" else -1
            nnue_loss = direction * (record.evaluation_before_cp -
                                     record.evaluation_after_cp)
            print(f"Why the engine prefers its move: NNUE rates the played "
                  f"move {max(0, nnue_loss) / 100:.2f} pawns worse for "
                  f"{record.mover.title()}.")
        if (not same_move and record.best_classical is not None and
                record.played_classical is not None):
            labels = {
                "material": "material", "piece_square": "placement",
                "activity": "activity", "king_safety": "king safety",
                "pawn_structure": "pawn structure", "threats": "threats",
                "endgame": "endgame factors",
            }
            direction = 1 if record.mover == "white" else -1
            differences = record.best_classical.difference(record.played_classical)
            factors = [(name, value * direction) for name, value in differences.items()
                       if name in labels and abs(value) >= 10]
            factors.sort(key=lambda item: abs(item[1]), reverse=True)
            if factors:
                phrases = [f"{labels[name]} {value / 100:+.2f}"
                           for name, value in factors[:4]]
                print("Classical comparison, best line versus played line from "
                      f"{record.mover.title()}'s perspective: " +
                      ", ".join(phrases))

        alternative = record.simpler_good_alternative
        if alternative:
            method = ("robust consensus" if alternative.get("consensus")
                      else "strict stability")
            print("Simpler Good Alternative: "
                  f"{alternative['move_san']}  NNUE "
                  f"{score(alternative['score_cp'])}")
            print("  This is not the engine's top move. It is "
                  f"{alternative['distance_from_best_cp'] / 100:.2f} below "
                  f"best and {alternative['gain_over_played_cp'] / 100:.2f} "
                  "better than the played move from the mover's perspective.")
            print("  Full Alternative Line: " +
                  line(alternative["full_line_san"]))
            print("  Stable Evaluation-Preserving Alternative Line With Qsearch: " +
                  line(alternative["explainable_line_san"]))
            print(f"  Alternative depths: stable "
                  f"{alternative['stability_depth']}, verified "
                  f"{alternative['verification_depth']} ({method})")
            print(f"  Alternative endpoint: NNUE "
                  f"{score(alternative['endpoint_nnue_cp'])}, within "
                  f"{alternative['endpoint_delta_cp'] / 100:.2f} of its "
                  "root score")
            classical_value = ClassicalBreakdown(**alternative["classical"])
            print(f"  Alternative Explainable Evaluation "
                  f"{classical_value.total / 100:+.2f}. This comes from: "
                  f"{format_components(classical_value)}")
        elif record.alternative_search_attempted:
            print("Simpler Good Alternative: none qualified after testing "
                  f"{record.alternative_candidates_tested} previously preferred "
                  "root move(s).")

    movetime_ms = args.movetime
    analyze_review(
        review,
        review_path=args.review,
        engine_path=args.engine,
        depth=args.depth,
        movetime_ms=movetime_ms,
        nodes_per_position=args.nodes,
        total_time_seconds=args.time,
        max_plies=args.max_plies,
        cpu_count=args.cpu_count,
        start_depth=args.start_depth,
        progress=print_move,
    )
    print(f"Checkpoint updated: {Path(args.review).resolve()}")


def command_review_paste(args: argparse.Namespace) -> None:
    output = Path(args.output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    source = output.with_suffix(".source.pgn")
    source.write_text(_read_pasted_pgn(), encoding="utf-8")
    review = _new_review(source, output, game_number=args.game, engine=args.engine,
                         nodes=args.nodes or 0, multipv=1, threads=args.threads)
    review.settings.minimum_depth = args.start_depth if args.depth else 0
    review.settings.maximum_depth = args.depth or 0
    review.settings.total_review_time_ms = (
        max(1, round(args.time * 1000)) if args.time is not None else 0)
    review.settings.time_per_position_ms = args.movetime or 0
    save_review(review, output)
    # Reuse the normal resumable analyzer after creating the durable source and
    # checkpoint. A cancelled review can therefore continue with `analyze`.
    args.review = str(output)
    command_analyze(args)


def command_explain_fen(args: argparse.Namespace) -> None:
    from zebrafish.review.classical import ClassicalEvaluator, explain_classical

    with ClassicalEvaluator(args.helper) as evaluator:
        value = evaluator.evaluate(args.fen)
    print(json.dumps(value.__dict__ if hasattr(value, "__dict__") else {
        name: getattr(value, name) for name in value.__dataclass_fields__
    }, indent=2))
    for sentence in explain_classical(value):
        print(sentence)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="C Engine game-review tools")
    commands = parser.add_subparsers(dest="command", required=True)

    init = commands.add_parser("init", help="create a resumable review job")
    init.add_argument("pgn")
    init.add_argument("output")
    init.add_argument("--game", type=int, default=1)
    init.add_argument("--engine", default="current")
    init.add_argument("--nodes", type=int, default=2_000_000)
    init.add_argument("--multipv", type=int, default=3)
    init.add_argument("--threads", type=int, default=1)
    init.set_defaults(func=command_init)

    summary = commands.add_parser("summary", help="summarize an existing review")
    summary.add_argument("review")
    summary.add_argument("--update", action="store_true")
    summary.set_defaults(func=command_summary)

    export = commands.add_parser("export-pgn", help="export an annotated PGN")
    export.add_argument("review")
    export.add_argument("output")
    export.set_defaults(func=command_export)

    performance = commands.add_parser(
        "performance-elo", help="estimate White/Black Lichess blitz rating from the game")
    performance.add_argument("review")
    performance.add_argument("--model-dir", default=None)
    performance.add_argument("--update", action="store_true",
                             help="store estimates in the review JSON")
    performance.set_defaults(func=command_performance_elo)

    analyze = commands.add_parser("analyze", help="run resumable UCI analysis")
    analyze.add_argument("review")
    analyze.add_argument("--engine", required=True)
    limit = analyze.add_mutually_exclusive_group(required=True)
    limit.add_argument("--depth", type=int)
    limit.add_argument("--nodes", type=int, help="nodes per search")
    limit.add_argument("--time", type=float,
                       help="total seconds for all remaining review searches")
    limit.add_argument("--movetime", type=int,
                       help="fixed milliseconds per search")
    analyze.add_argument("--max-plies", type=int, default=0,
                         help="stop after this many total plies; zero means all")
    analyze.add_argument("--cpu-count", type=int, default=2,
                         help="logical processors available to the child engine")
    analyze.add_argument("--threads", type=int,
                         help="engine search threads; defaults to the review setting")
    analyze.add_argument("--start-depth", type=int, default=1,
                         help="first staged depth retained for stability analysis")
    analyze.set_defaults(func=command_analyze)

    paste = commands.add_parser(
        "review-paste", help="paste a PGN and immediately review it")
    paste.add_argument("output", help="resumable .review.json output")
    paste.add_argument("--engine", required=True)
    paste.add_argument("--game", type=int, default=1)
    paste_limit = paste.add_mutually_exclusive_group(required=True)
    paste_limit.add_argument("--depth", type=int)
    paste_limit.add_argument("--nodes", type=int, help="nodes per search")
    paste_limit.add_argument("--time", type=float,
                             help="total seconds for the complete review")
    paste_limit.add_argument("--movetime", type=int,
                             help="fixed milliseconds per search")
    paste.add_argument("--max-plies", type=int, default=0)
    paste.add_argument("--cpu-count", type=int, default=2)
    paste.add_argument("--threads", type=int, default=1)
    paste.add_argument("--start-depth", type=int, default=1)
    paste.set_defaults(func=command_review_paste)

    explain = commands.add_parser("explain-fen",
                                  help="print classical terms for one FEN")
    explain.add_argument("fen")
    explain.add_argument("--helper", default=None)
    explain.set_defaults(func=command_explain_fen)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    args.func(args)
