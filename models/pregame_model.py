"""
Pre-game μοντέλο πιθανοτήτων βάσει φόρμας ομάδων.
Χρησιμοποιεί απλό στατιστικό μοντέλο (Poisson approximation).
"""

import math
from dataclasses import dataclass


@dataclass
class TeamStats:
    name: str
    avg_goals_scored: float    # μέσος όρος γκολ που σκοράρει
    avg_goals_conceded: float  # μέσος όρος γκολ που δέχεται
    avg_corners_for: float = 5.0
    avg_corners_against: float = 5.0


def poisson_prob(lam: float, k: int) -> float:
    """P(X = k) για Poisson κατανομή."""
    return (math.exp(-lam) * (lam ** k)) / math.factorial(k)


def poisson_over_prob(lam: float, threshold: float) -> float:
    """P(X > threshold) για Poisson."""
    k = int(threshold)
    prob_under_or_equal = sum(poisson_prob(lam, i) for i in range(k + 1))
    return 1.0 - prob_under_or_equal


def calculate_pregame_probs(home: TeamStats, away: TeamStats, league_avg_goals: float = 2.65) -> dict:
    """
    Υπολογίζει πιθανότητες αγώνα βάσει φόρμας.

    Μοντέλο Dixon-Coles (απλοποιημένο):
    - Expected goals home = (home_attack × away_defense) / league_avg
    - Expected goals away = (away_attack × home_defense) / league_avg
    """
    home_attack = home.avg_goals_scored / (league_avg_goals / 2)
    home_defense = home.avg_goals_conceded / (league_avg_goals / 2)
    away_attack = away.avg_goals_scored / (league_avg_goals / 2)
    away_defense = away.avg_goals_conceded / (league_avg_goals / 2)

    # Home advantage factor (~8% boost)
    home_advantage = 1.08

    lambda_home = home_attack * away_defense * (league_avg_goals / 2) * home_advantage
    lambda_away = away_attack * home_defense * (league_avg_goals / 2)
    lambda_total = lambda_home + lambda_away

    # Over/Under πιθανότητες
    over_15 = poisson_over_prob(lambda_total, 1.5)
    over_25 = poisson_over_prob(lambda_total, 2.5)
    over_35 = poisson_over_prob(lambda_total, 3.5)

    # Both Teams to Score (BTTS)
    prob_home_scores = 1 - poisson_prob(lambda_home, 0)
    prob_away_scores = 1 - poisson_prob(lambda_away, 0)
    btts_yes = prob_home_scores * prob_away_scores

    # Corners (απλό μοντέλο)
    expected_corners = home.avg_corners_for + away.avg_corners_for
    corners_over_95 = poisson_over_prob(expected_corners, 9.5)
    corners_over_105 = poisson_over_prob(expected_corners, 10.5)

    return {
        "expected_goals_home": round(lambda_home, 3),
        "expected_goals_away": round(lambda_away, 3),
        "expected_goals_total": round(lambda_total, 3),
        "over_1_5": round(over_15, 4),
        "over_2_5": round(over_25, 4),
        "over_3_5": round(over_35, 4),
        "btts_yes": round(btts_yes, 4),
        "btts_no": round(1 - btts_yes, 4),
        "corners_over_9_5": round(corners_over_95, 4),
        "corners_over_10_5": round(corners_over_105, 4),
    }
