"""Versioned data model shared by the future CLI, engine bridge, and GUI."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


SCHEMA_VERSION = 1


@dataclass(slots=True)
class AnalysisSettings:
    engine_name: str = ""
    engine_version: str = ""
    network_sha256: str = ""
    nodes_per_position: int = 0
    time_per_position_ms: int = 0
    total_review_time_ms: int = 0
    minimum_depth: int = 0
    maximum_depth: int = 0
    multipv: int = 3
    hash_mb: int = 256
    threads: int = 1
    tablebase_enabled: bool = True
    stability_iterations: int = 3
    stability_score_tolerance_cp: int = 25
    stability_prefix_plies: int = 4
    explanation_score_tolerance_cp: int = 35


@dataclass(slots=True)
class IterationSnapshot:
    depth: int
    seldepth: int = 0
    nodes: int = 0
    score_cp: int | None = None
    mate: int | None = None
    best_move: str = ""
    pv: list[str] = field(default_factory=list)


@dataclass(slots=True)
class StabilityResult:
    final_best_move: str = ""
    discovery_depth: int | None = None
    discovery_nodes: int | None = None
    stability_depth: int | None = None
    stability_nodes: int | None = None
    verification_depth: int | None = None
    stable_prefix: list[str] = field(default_factory=list)
    stable: bool = False
    score_span_cp: int | None = None
    consensus: bool = False


@dataclass(slots=True)
class ClassicalBreakdown:
    """Interpretable indicators; they are not claimed to sum to NNUE."""

    material: int = 0
    piece_square: int = 0
    activity: int = 0
    king_safety: int = 0
    pawn_structure: int = 0
    threats: int = 0
    endgame: int = 0
    total: int = 0
    phase: int = 0

    def difference(self, other: "ClassicalBreakdown") -> dict[str, int]:
        """Return self-minus-other component differences."""
        left = asdict(self)
        right = asdict(other)
        return {name: left[name] - right[name] for name in left if name != "phase"}


@dataclass(slots=True)
class MoveReview:
    ply: int
    move_number: int
    mover: str
    san: str
    uci: str = ""
    fen_before: str = ""
    best_move_uci: str = ""
    best_move_san: str = ""
    evaluation_before_cp: int | None = None
    evaluation_after_cp: int | None = None
    expected_score_before: float | None = None
    expected_score_after: float | None = None
    expected_score_loss: float | None = None
    classification: str = "unreviewed"
    forced: bool = False
    book: bool = False
    tablebase: bool = False
    critical: bool = False
    multipv: list[dict[str, Any]] = field(default_factory=list)
    iterations: list[IterationSnapshot] = field(default_factory=list)
    stability: StabilityResult = field(default_factory=StabilityResult)
    response_iterations: list[IterationSnapshot] = field(default_factory=list)
    response_stability: StabilityResult = field(default_factory=StabilityResult)
    full_best_pv_san: list[str] = field(default_factory=list)
    stable_best_pv_san: list[str] = field(default_factory=list)
    full_response_pv_san: list[str] = field(default_factory=list)
    stable_response_pv_san: list[str] = field(default_factory=list)
    best_explanation_used_full_pv: bool = False
    response_explanation_used_full_pv: bool = False
    best_explanation_score_delta_cp: int | None = None
    response_explanation_score_delta_cp: int | None = None
    played_classical: ClassicalBreakdown | None = None
    best_classical: ClassicalBreakdown | None = None
    explanation_position_fen: str = ""
    qsearch_score_cp: int | None = None
    qsearch_pv_uci: list[str] = field(default_factory=list)
    qsearch_pv_san: list[str] = field(default_factory=list)
    response_qsearch_score_cp: int | None = None
    response_qsearch_pv_uci: list[str] = field(default_factory=list)
    response_qsearch_pv_san: list[str] = field(default_factory=list)
    explanation_facts: list[str] = field(default_factory=list)
    played_explanation_facts: list[str] = field(default_factory=list)
    simpler_good_alternative: dict[str, Any] = field(default_factory=dict)
    alternative_search_attempted: bool = False
    alternative_candidates_tested: int = 0


@dataclass(slots=True)
class PlayerSummary:
    color: str
    accuracy: float | None = None
    average_expected_score_loss: float | None = None
    informative_moves: int = 0
    classifications: dict[str, int] = field(default_factory=dict)
    estimated_performance_elo: float | None = None
    elo_interval_low: float | None = None
    elo_interval_high: float | None = None


@dataclass(slots=True)
class GameReview:
    source_pgn: str
    source_game_index: int = 1
    headers: dict[str, str] = field(default_factory=dict)
    settings: AnalysisSettings = field(default_factory=AnalysisSettings)
    moves: list[MoveReview] = field(default_factory=list)
    players: dict[str, PlayerSummary] = field(default_factory=dict)
    completed_plies: int = 0
    complete: bool = False
    schema_version: int = SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
