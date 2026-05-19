"""
Steam Move Detection
====================
Detects sharp money entering a market by comparing Pinnacle no-vig probabilities
between two points in time (pre-game scan vs current, or scan vs live).

A shift > STEAM_MOVE_THRESHOLD means the Pinnacle line moved significantly —
sharp players have taken a position and Pinnacle adjusted to protect itself.

Applied everywhere: pre-game tips, watchlist, live targets, live scanner.
"""

from config import STEAM_MOVE_THRESHOLD


# Markets we track for steam, mapped to their snapshot DB column names
_MARKET_MAP = [
    ("Over 2.5",    "pin_over25_prob"),
    ("HT Over 0.5", "pin_ht05_prob"),
    ("HT Over 1.5", "pin_ht15_prob"),
    ("Home Win",    "pin_home_prob"),
    ("Away Win",    "pin_away_prob"),
]


def detect_steam(
    prev_probs: dict | None,
    curr_probs: dict,
    threshold: float = STEAM_MOVE_THRESHOLD,
) -> list[dict]:
    """
    Compare current Pinnacle no-vig probs against a previous baseline.

    Args:
        prev_probs: dict with DB column keys (pin_over25_prob etc.) — from match_snapshots
        curr_probs: dict with short keys (over25, ht05, ht15, home, away)
        threshold:  minimum probability shift to flag as steam

    Returns:
        List of steam signals, each:
        {market, prev, curr, shift, direction, label}
        Empty list if no steam or no baseline.
    """
    if not prev_probs:
        return []

    short_to_col = {
        "over25": "pin_over25_prob",
        "ht05":   "pin_ht05_prob",
        "ht15":   "pin_ht15_prob",
        "home":   "pin_home_prob",
        "away":   "pin_away_prob",
    }

    signals = []
    for market, col in _MARKET_MAP:
        # Accept both short keys and DB column keys in curr_probs
        short_key = next((k for k, v in short_to_col.items() if v == col), None)
        curr_val  = curr_probs.get(short_key) or curr_probs.get(col)
        prev_val  = prev_probs.get(col)

        if curr_val is None or prev_val is None:
            continue

        shift = curr_val - prev_val
        if abs(shift) < threshold:
            continue

        direction = "up" if shift > 0 else "down"
        arrow     = "↑" if shift > 0 else "↓"
        signals.append({
            "market":    market,
            "prev":      round(prev_val, 4),
            "curr":      round(curr_val, 4),
            "shift":     round(shift, 4),
            "direction": direction,
            "label":     f"🔥 STEAM {market} {arrow}{abs(shift):.0%}",
        })

    return signals


def steam_markets(steam_moves: list[dict]) -> set[str]:
    """Return set of market names that have steam."""
    return {s["market"] for s in (steam_moves or [])}


def format_steam_short(steam_moves: list[dict]) -> str:
    """One-line summary for UI display, e.g. '🔥 Over 2.5 ↑+9%'"""
    if not steam_moves:
        return ""
    parts = []
    for s in steam_moves:
        arrow = "↑" if s["direction"] == "up" else "↓"
        parts.append(f"{s['market']} {arrow}{abs(s['shift']):.0%}")
    return "🔥 " + "  |  ".join(parts)
