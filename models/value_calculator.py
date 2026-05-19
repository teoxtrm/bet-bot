"""
Υπολογισμός Value Bets.

Value = (Πιθανότητά μας × Απόδοση bookmaker) - 1
Αν Value > 0 → υπάρχει edge υπέρ μας.
"""

from config import MIN_VALUE_EDGE


def decimal_to_implied_prob(odds: float) -> float:
    """Μετατρέπει δεκαδική απόδοση σε implied πιθανότητα."""
    if odds <= 1.0:
        return 1.0
    return 1.0 / odds


def calculate_value(our_prob: float, bookmaker_odds: float) -> dict:
    """
    Υπολογίζει αν υπάρχει value σε ένα στοίχημα.

    Args:
        our_prob: Η πιθανότητα που υπολογίσαμε εμείς (0.0 - 1.0)
        bookmaker_odds: Η δεκαδική απόδοση της στοιχηματικής

    Returns:
        dict με value edge, implied prob και αν είναι value bet
    """
    implied_prob = decimal_to_implied_prob(bookmaker_odds)
    value_edge = (our_prob * bookmaker_odds) - 1.0
    is_value = value_edge >= MIN_VALUE_EDGE

    return {
        "our_probability": round(our_prob, 4),
        "bookmaker_odds": bookmaker_odds,
        "implied_probability": round(implied_prob, 4),
        "bookmaker_margin": round(implied_prob - our_prob, 4),
        "value_edge": round(value_edge, 4),
        "value_edge_pct": f"{value_edge * 100:.2f}%",
        "is_value_bet": is_value,
    }


def kelly_criterion(our_prob: float, bookmaker_odds: float, bankroll: float = 1000.0, fraction: float = 0.25) -> dict:
    """
    Kelly Criterion για βέλτιστο ποσό στοιχήματος.
    Χρησιμοποιούμε fractional Kelly (25%) για ασφάλεια.

    Args:
        our_prob: Η πιθανότητά μας
        bookmaker_odds: Δεκαδική απόδοση
        bankroll: Διαθέσιμο κεφάλαιο
        fraction: Κλάσμα Kelly (0.25 = 25%)
    """
    b = bookmaker_odds - 1  # net odds
    p = our_prob
    q = 1 - p

    kelly_pct = (b * p - q) / b if b > 0 else 0
    kelly_pct = max(0, kelly_pct)  # ποτέ αρνητικό
    fractional_kelly = kelly_pct * fraction
    bet_amount = round(bankroll * fractional_kelly, 2)

    return {
        "kelly_percentage": round(kelly_pct * 100, 2),
        "fractional_kelly_pct": round(fractional_kelly * 100, 2),
        "suggested_bet": bet_amount,
    }


def calculate_stake(
    our_prob:       float,
    bookmaker_odds: float,
    method:         str   = "kelly",
    bankroll:       float = 1000.0,
    base_stake:     float = 10.0,
    fixed_pct:      float = 2.0,
    confidence:     float = 0.0,
) -> float:
    """
    Unified stake sizing.

    method="kelly"     → 25% fractional Kelly on bankroll
    method="fixed_pct" → fixed_pct% of bankroll every bet
    method="tiered"    → base_stake × multiplier based on confidence tier
                         LOCK (≥82%) = 1.5× | STRONG (≥72%) = 1× | TIP = 0.5×
    confidence         → used by tiered (tipster confidence); falls back to our_prob
    """
    if method == "kelly":
        return kelly_criterion(our_prob, bookmaker_odds, bankroll)["suggested_bet"]
    if method == "fixed_pct":
        return round(bankroll * fixed_pct / 100, 2)
    # tiered
    c = confidence if confidence > 0 else our_prob
    if c >= 0.82:
        return round(base_stake * 1.5, 2)
    if c >= 0.72:
        return round(base_stake, 2)
    return round(base_stake * 0.5, 2)


def compare_bookmakers(our_prob: float, odds_by_bookmaker: dict) -> list:
    """
    Συγκρίνει value σε πολλές στοιχηματικές ταυτόχρονα.

    Args:
        our_prob: Η πιθανότητά μας
        odds_by_bookmaker: {"stoiximan": 2.10, "bet365": 2.05, "novibet": 2.15}

    Returns:
        Λίστα αποτελεσμάτων ταξινομημένη από το μεγαλύτερο value
    """
    results = []
    for bookmaker, odds in odds_by_bookmaker.items():
        if odds and odds > 1.0:
            val = calculate_value(our_prob, odds)
            val["bookmaker"] = bookmaker
            results.append(val)

    return sorted(results, key=lambda x: x["value_edge"], reverse=True)
