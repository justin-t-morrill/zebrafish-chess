#!/usr/bin/env python3
"""Analyze aggregate chess-engine tournament results.

The Elo estimate uses the standard logistic Elo model applied to total match
score (win=1, draw=0.5, loss=0). No third-party packages are required.
"""

from __future__ import annotations

import argparse
import math
from dataclasses import dataclass


@dataclass(frozen=True)
class MatchResult:
    wins: int
    losses: int
    draws: int

    @property
    def games(self) -> int:
        return self.wins + self.losses + self.draws

    @property
    def score_points(self) -> float:
        return self.wins + 0.5 * self.draws

    @property
    def score_rate(self) -> float:
        return self.score_points / self.games


def elo_from_score(score_rate: float) -> float:
    """Convert expected score to Elo difference: positive favors engine A."""
    if score_rate <= 0.0:
        return -math.inf
    if score_rate >= 1.0:
        return math.inf
    return 400.0 * math.log10(score_rate / (1.0 - score_rate))


def normal_cdf(value: float) -> float:
    return 0.5 * math.erfc(-value / math.sqrt(2.0))


def exact_decisive_p_value(wins: int, losses: int) -> float | None:
    """Two-sided exact binomial test, conditional on decisive games.

    Under equal strength, either engine is equally likely to win a decisive
    game. Draws contain no information in this conditional test.
    """
    decisive = wins + losses
    if decisive == 0:
        return None
    tail = min(wins, losses)
    # Sum in log space. Directly constructing 2**decisive overflows when a
    # long tournament has more than roughly one thousand decisive games.
    log_terms = [
        math.lgamma(decisive + 1) - math.lgamma(k + 1)
        - math.lgamma(decisive - k + 1) - decisive * math.log(2.0)
        for k in range(tail + 1)
    ]
    largest = max(log_terms)
    cumulative = math.exp(largest) * sum(math.exp(term - largest) for term in log_terms)
    return min(1.0, 2.0 * cumulative)


def analyze(result: MatchResult, confidence: float = 0.95) -> dict[str, float | None]:
    if result.games <= 0:
        raise ValueError("At least one game is required.")

    score = result.score_rate
    # Sample variance of per-game points across outcomes 1, 0.5, and 0.
    if result.games > 1:
        squared = (
            result.wins * (1.0 - score) ** 2
            + result.draws * (0.5 - score) ** 2
            + result.losses * score**2
        )
        sample_variance = squared / (result.games - 1)
        score_se = math.sqrt(sample_variance / result.games)
    else:
        score_se = 0.0

    # 1.95996 is the normal critical value for the default 95% interval. A
    # compact inverse-normal approximation supports other confidence levels.
    alpha = 1.0 - confidence
    if not 0.0 < alpha < 1.0:
        raise ValueError("Confidence must be strictly between 0 and 1.")
    z_critical = inverse_normal_cdf(1.0 - alpha / 2.0)

    score_low = max(0.0, score - z_critical * score_se)
    score_high = min(1.0, score + z_critical * score_se)
    elo = elo_from_score(score)
    elo_low = elo_from_score(score_low)
    elo_high = elo_from_score(score_high)

    if score_se > 0.0:
        z_score = (score - 0.5) / score_se
        p_two_sided = min(1.0, math.erfc(abs(z_score) / math.sqrt(2.0)))
        # Probability that A's true score is above 50%, often called LOS.
        probability_superior = normal_cdf(z_score)
        p_one_sided = 1.0 - probability_superior
    else:
        z_score = None
        p_two_sided = None
        p_one_sided = None
        probability_superior = None

    return {
        "score": score,
        "score_se": score_se,
        "score_low": score_low,
        "score_high": score_high,
        "elo": elo,
        "elo_low": elo_low,
        "elo_high": elo_high,
        "z_score": z_score,
        "p_two_sided": p_two_sided,
        "p_one_sided": p_one_sided,
        "probability_superior": probability_superior,
        "exact_decisive_p": exact_decisive_p_value(result.wins, result.losses),
    }


def inverse_normal_cdf(probability: float) -> float:
    """Acklam's accurate inverse standard-normal CDF approximation."""
    if not 0.0 < probability < 1.0:
        if probability == 0.0:
            return -math.inf
        if probability == 1.0:
            return math.inf
        raise ValueError("Probability must be in [0, 1].")

    a = (-39.6968302866538, 220.946098424521, -275.928510446969,
         138.357751867269, -30.6647980661472, 2.50662827745924)
    b = (-54.4760987982241, 161.585836858041, -155.698979859887,
         66.8013118877197, -13.2806815528857)
    c = (-0.00778489400243029, -0.322396458041136, -2.40075827716184,
         -2.54973253934373, 4.37466414146497, 2.93816398269878)
    d = (0.00778469570904146, 0.32246712907004, 2.445134137143,
         3.75440866190742)
    low = 0.02425
    high = 1.0 - low
    if probability < low:
        q = math.sqrt(-2.0 * math.log(probability))
        return (((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) / \
               ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1.0)
    if probability > high:
        q = math.sqrt(-2.0 * math.log(1.0 - probability))
        return -(((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) / \
                ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1.0)
    q = probability - 0.5
    r = q * q
    return (((((a[0]*r+a[1])*r+a[2])*r+a[3])*r+a[4])*r+a[5])*q / \
           (((((b[0]*r+b[1])*r+b[2])*r+b[3])*r+b[4])*r+1.0)


def format_number(value: float | None, digits: int = 4) -> str:
    if value is None:
        return "N/A"
    if math.isinf(value):
        return "+infinity" if value > 0 else "-infinity"
    return f"{value:.{digits}f}"


def print_report(result: MatchResult, statistics: dict[str, float | None],
                 confidence: float) -> None:
    score = float(statistics["score"])
    score_low = float(statistics["score_low"])
    score_high = float(statistics["score_high"])
    label = f"{confidence * 100:.1f}%"
    print("\nTournament analysis (Engine A relative to Engine B)")
    print("-" * 56)
    print(f"Games:              {result.games}")
    print(f"W / D / L:          {result.wins} / {result.draws} / {result.losses}")
    print(f"Points:             {result.score_points:.1f} / {result.games}")
    print(f"Score rate:         {score * 100:.2f}%")
    print(f"Score {label} CI:    {score_low * 100:.2f}% to {score_high * 100:.2f}%")
    print(f"Estimated Elo gain: {format_number(statistics['elo'], 2)}")
    print(f"Elo {label} CI:      {format_number(statistics['elo_low'], 2)} to "
          f"{format_number(statistics['elo_high'], 2)}")
    print(f"Z statistic:        {format_number(statistics['z_score'], 4)}")
    print(f"Two-sided p-value:  {format_number(statistics['p_two_sided'], 6)}")
    print(f"One-sided p-value:  {format_number(statistics['p_one_sided'], 6)}")
    los = statistics["probability_superior"]
    print(f"Likelihood A better:{' ' if los is not None else ''}"
          f"{format_number(None if los is None else 100.0 * float(los), 2)}"
          f"{'%' if los is not None else ''}")
    print(f"Exact decisive p:   {format_number(statistics['exact_decisive_p'], 6)}")
    print("\nNotes:")
    print("  - p-values test equal strength; smaller values are stronger evidence.")
    print("  - The exact test conditions on decisive games and ignores draws.")
    print("  - Elo and its interval use the W=1, D=0.5, L=0 score model.")
    print("  - Opening pairs are correlated; W/D/L alone cannot model that pairing.")


def nonnegative_integer(text: str) -> int:
    value = int(text)
    if value < 0:
        raise argparse.ArgumentTypeError("values cannot be negative")
    return value


def prompt_count(label: str) -> int:
    while True:
        try:
            return nonnegative_integer(input(f"{label}: ").strip())
        except (ValueError, argparse.ArgumentTypeError):
            print("Please enter a nonnegative whole number.")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Analyze W/D/L results for Engine A versus Engine B.")
    parser.add_argument("wins", nargs="?", type=nonnegative_integer,
                        help="Engine A wins")
    parser.add_argument("losses", nargs="?", type=nonnegative_integer,
                        help="Engine A losses")
    parser.add_argument("draws", nargs="?", type=nonnegative_integer,
                        help="draws")
    parser.add_argument("--confidence", type=float, default=0.95,
                        help="confidence level as a fraction (default: 0.95)")
    args = parser.parse_args()

    supplied = (args.wins, args.losses, args.draws)
    if all(value is None for value in supplied):
        print("Enter results from Engine A's perspective.")
        wins = prompt_count("Wins")
        losses = prompt_count("Losses")
        draws = prompt_count("Draws")
    elif any(value is None for value in supplied):
        parser.error("provide all three values: wins losses draws")
    else:
        wins, losses, draws = supplied

    result = MatchResult(wins=wins, losses=losses, draws=draws)
    try:
        statistics = analyze(result, args.confidence)
    except ValueError as error:
        parser.error(str(error))
    print_report(result, statistics, args.confidence)


if __name__ == "__main__":
    main()
