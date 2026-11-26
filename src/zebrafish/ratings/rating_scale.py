"""Convert the Lichess Blitz training target to a Chess.com Blitz equivalent."""
from __future__ import annotations

import math

# July 2026 ChessGoals cross-platform table. Each pair is
# (Lichess Blitz, Chess.com Blitz) for active accounts on both sites.
CHESSCOM_BLITZ_TABLE = [
    (1090, 500), (1160, 600), (1225, 700), (1290, 800), (1360, 900),
    (1425, 1000), (1490, 1100), (1525, 1150), (1555, 1200),
    (1590, 1250), (1620, 1300), (1655, 1350), (1685, 1400),
    (1720, 1450), (1755, 1500), (1785, 1550), (1820, 1600),
    (1850, 1650), (1885, 1700), (1915, 1750), (1950, 1800),
    (1980, 1850), (2015, 1900), (2045, 1950), (2080, 2000),
    (2145, 2100), (2210, 2200), (2275, 2300), (2340, 2400),
    (2410, 2500), (2475, 2600), (2540, 2700), (2610, 2800),
    (2675, 2900), (2745, 3000),
]

# ChessGoals reports +/-70 as the typical central range containing roughly
# 50% of matched Blitz players. Under a normal approximation this implies
# sigma = 70 / Phi^-1(.75), then a two-sided 90% half-width of 1.64485*sigma.
CONVERSION_CENTRAL_50_HALF_WIDTH = 70.0
NORMAL_75TH_PERCENTILE = 0.6744897501960817
NORMAL_95TH_PERCENTILE = 1.6448536269514722
CONVERSION_90_HALF_WIDTH = (
    CONVERSION_CENTRAL_50_HALF_WIDTH / NORMAL_75TH_PERCENTILE
    * NORMAL_95TH_PERCENTILE
)


def lichess_to_chesscom_blitz(value: float) -> float:
    """Piecewise-linear table interpolation with conservative end extrapolation."""
    points = CHESSCOM_BLITZ_TABLE
    if value <= points[0][0]:
        # Preserve the first observed local slope, but avoid nonsensical negatives.
        left, right = points[0], points[1]
    elif value >= points[-1][0]:
        left, right = points[-2], points[-1]
    else:
        for left, right in zip(points, points[1:]):
            if left[0] <= value <= right[0]:
                break
    fraction = (value - left[0]) / (right[0] - left[0])
    return max(100.0, left[1] + fraction * (right[1] - left[1]))


def _converted_compatibility_interval(value: float, low: float, high: float,
                                      conversion_half: float) -> tuple[int, int, float]:
    converted = lichess_to_chesscom_blitz(value)
    converted_low = lichess_to_chesscom_blitz(low)
    converted_high = lichess_to_chesscom_blitz(high)
    lower_model = max(0.0, converted - converted_low)
    upper_model = max(0.0, converted_high - converted)
    lower_total = math.hypot(lower_model, conversion_half)
    upper_total = math.hypot(upper_model, conversion_half)
    return (round(max(100.0, converted - lower_total)),
            round(converted + upper_total), max(lower_total, upper_total))

def convert_estimate(estimate: dict) -> dict:
    """Convert point/components and combine model and scale uncertainty."""
    lichess_value = float(estimate["raw_stacked_elo"])
    lichess_low = float(estimate["range_low"])
    lichess_high = float(estimate["range_high"])
    chesscom_value = lichess_to_chesscom_blitz(lichess_value)
    converted_low = lichess_to_chesscom_blitz(lichess_low)
    converted_high = lichess_to_chesscom_blitz(lichess_high)
    model_half = max(chesscom_value - converted_low, converted_high - chesscom_value)
    range_low, range_high, total_half = _converted_compatibility_interval(
        lichess_value, lichess_low, lichess_high, CONVERSION_90_HALF_WIDTH)
    estimate.update({
        "rating_scale": "Chess.com Blitz equivalent",
        "source_rating_scale": "Lichess Blitz",
        "lichess_performance_elo": round(lichess_value),
        "lichess_range_low": round(lichess_low),
        "lichess_range_high": round(lichess_high),
        "performance_elo": round(chesscom_value),
        "range_low": range_low,
        "range_high": range_high,
        "model_90_half_width_chesscom": model_half,
        "conversion_90_half_width": CONVERSION_90_HALF_WIDTH,
        "reported_90_half_width": total_half,
        "display_range_low": range_low,
        "display_range_high": range_high,
        "display_interval_percent": 90,
        "conversion_source": "ChessGoals July 2026 active-account Blitz table",
        "conversion_method": "piecewise-linear interpolation",
        "interval_method": "natural-population split conformal plus cross-platform spread",
        "interval_note": ("Compatibility with real players who produced similar games; "
                          "not a posterior bound on latent one-game performance."),
    })
    if "compatibility_68_lichess_low" in estimate:
        conversion_sigma = CONVERSION_CENTRAL_50_HALF_WIDTH / NORMAL_75TH_PERCENTILE
        for level, conversion_half in ((50, CONVERSION_CENTRAL_50_HALF_WIDTH),
                                       (68, conversion_sigma)):
            low, high, half = _converted_compatibility_interval(
                lichess_value, float(estimate[f"compatibility_{level}_lichess_low"]),
                float(estimate[f"compatibility_{level}_lichess_high"]), conversion_half)
            estimate.update({f"compatibility_{level}_low": low,
                             f"compatibility_{level}_high": high,
                             f"compatibility_{level}_half_width": half})
        estimate.update(display_range_low=estimate["compatibility_68_low"],
                        display_range_high=estimate["compatibility_68_high"],
                        display_interval_percent=68)
    else:
        estimate.update(interval_method="engine/move model reference range plus cross-platform spread",
                        interval_note="90% reference range from blitz calibration; coverage outside blitz is unvalidated.")
    if "ratingnet_shared_center_raw_elo" in estimate:
        estimate["ratingnet_shared_center_elo"] = round(lichess_to_chesscom_blitz(
            float(estimate["ratingnet_shared_center_raw_elo"])))
    if "precnn_performance_raw_elo" in estimate:
        estimate["precnn_performance_elo"] = round(lichess_to_chesscom_blitz(
            float(estimate["precnn_performance_raw_elo"])))
    for source, target in (("aggregate_raw_elo", "aggregate_elo"),
                           ("move_distribution_raw_elo", "move_distribution_elo")):
        estimate[target] = round(lichess_to_chesscom_blitz(float(estimate[source])))
    estimate["stack_adjustment"] = (
        chesscom_value - lichess_to_chesscom_blitz(lichess_value - float(estimate["stack_adjustment"]))
    )
    for move in estimate.get("move_impacts", []):
        lichess_impact = float(move["elo_impact"])
        move["lichess_elo_impact"] = lichess_impact
        move["elo_impact"] = chesscom_value - lichess_to_chesscom_blitz(lichess_value - lichess_impact)
    estimate["move_impact_method"] = "controlled move-evidence leave-one-out influence"
    return estimate
