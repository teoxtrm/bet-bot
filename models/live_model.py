"""
Live μοντέλο: αναπροσαρμόζει πιθανότητες βάσει λεπτού αγώνα και score.
"""

from config import LIVE_TIME_WEIGHTS


def get_time_bucket(minute: int) -> str:
    if minute <= 15:
        return "0-15"
    elif minute <= 30:
        return "16-30"
    elif minute <= 45:
        return "31-45"
    elif minute <= 60:
        return "46-60"
    elif minute <= 75:
        return "61-75"
    else:
        return "76-90"


def live_over_probability(
    pregame_over_prob: float,
    current_score_total: int,
    minute: int,
    target_goals: float = 2.5,
) -> dict:
    """
    Αναπροσαρμόζει πιθανότητα Over βάσει live δεδομένων.

    Args:
        pregame_over_prob: Αρχική pre-game πιθανότητα για Over
        current_score_total: Συνολικά γκολ μέχρι τώρα
        minute: Τρέχον λεπτό αγώνα
        target_goals: Γκολ στόχος (π.χ. 2.5)
    """
    goals_needed = target_goals - current_score_total

    # Αν έχει ήδη επιτευχθεί το Over
    if goals_needed <= 0:
        return {
            "live_over_prob": 1.0,
            "status": "ALREADY_OVER",
            "minute": minute,
            "goals_still_needed": 0,
        }

    # Υπολειπόμενα λεπτά
    minutes_remaining = max(90 - minute, 1)
    time_fraction_remaining = minutes_remaining / 90.0

    # Αναλογία γκολ που αναμένεται στο υπόλοιπο
    # Ρυθμός: πόσα γκολ χρειάζονται / πόσο χρόνο μένει
    avg_goals_per_90 = 2.65
    expected_remaining = avg_goals_per_90 * time_fraction_remaining

    # Time multiplier από config
    bucket = get_time_bucket(minute)
    time_mult = LIVE_TIME_WEIGHTS.get(bucket, {}).get("multiplier", 1.0)
    expected_remaining *= time_mult

    # Υπολογισμός πιθανότητας να σκοραριστούν τα γκολ που χρειάζονται
    import math

    def poisson_at_least(lam: float, k: int) -> float:
        prob_less = sum((math.exp(-lam) * lam**i) / math.factorial(i) for i in range(int(k)))
        return max(0.0, 1.0 - prob_less)

    live_prob = poisson_at_least(expected_remaining, int(goals_needed))

    # Blend με pregame prob (60% live, 40% pregame) για σταθερότητα
    blended = (live_prob * 0.6) + (pregame_over_prob * 0.4)

    return {
        "live_over_prob": round(blended, 4),
        "raw_live_prob": round(live_prob, 4),
        "pregame_over_prob": round(pregame_over_prob, 4),
        "minute": minute,
        "goals_still_needed": goals_needed,
        "expected_goals_remaining": round(expected_remaining, 3),
        "status": "IN_PLAY",
    }
