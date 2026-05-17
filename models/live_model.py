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


def live_ht_probability(
    pregame_ht_prob: float,
    ht_goals_so_far: int,
    minute: int,
    target: float = 0.5,
) -> dict:
    """
    Live probability for 1st-half Over markets.

    Derives Poisson lambda from the Pinnacle no-vig pre-game HT probability,
    then scales to the remaining first-half time and adjusts for goals already scored.

    Args:
        pregame_ht_prob: Pinnacle no-vig P(Over target) for the full 45 min at kick-off
        ht_goals_so_far: Goals scored so far this half (= total_goals when minute ≤ 45)
        minute: Current match minute (1–45)
        target: 0.5 or 1.5
    """
    import math

    if minute > 45:
        return {"live_ht_prob": None, "settled": True}

    k_need = int(target) + 1          # goals total needed: O0.5 → 1, O1.5 → 2

    if ht_goals_so_far >= k_need:
        return {"live_ht_prob": 1.0, "settled": False}

    still_need = k_need - ht_goals_so_far
    p = max(0.001, min(0.999, pregame_ht_prob))

    if target <= 0.5:
        # P(X ≥ 1) = 1 − e^(−λ) = p  →  exact inversion
        lambda_ht = -math.log(1.0 - p)
    else:
        # P(X ≥ 2) = 1 − e^(−λ)(1 + λ) = p  →  binary search
        lo, hi = 1e-6, 30.0
        for _ in range(64):
            mid = (lo + hi) / 2
            if 1.0 - math.exp(-mid) * (1.0 + mid) < p:
                lo = mid
            else:
                hi = mid
        lambda_ht = (lo + hi) / 2

    remaining_frac = max(0.0, (45.0 - minute) / 45.0)
    lambda_rem     = lambda_ht * remaining_frac

    # P(X_rem < still_need) = sum of Poisson PMF for k = 0..still_need-1
    p_fewer = sum(
        math.exp(-lambda_rem) * (lambda_rem ** k) / math.factorial(k)
        for k in range(still_need)
    )

    return {
        "live_ht_prob":    round(max(0.0, min(1.0, 1.0 - p_fewer)), 4),
        "settled":         False,
        "lambda_ht":       round(lambda_ht, 4),
        "remaining_frac":  round(remaining_frac, 3),
    }
