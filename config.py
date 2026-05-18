"""
Κεντρικές ρυθμίσεις του bot.
"""

# --- Value Bet threshold ---
# Ελάχιστο edge (%) για να θεωρείται value bet
MIN_VALUE_EDGE = 0.05  # 5%

# --- Live model παράμετροι ---
LIVE_TIME_WEIGHTS = {
    "0-15":  {"multiplier": 1.0},
    "16-30": {"multiplier": 1.05},
    "31-45": {"multiplier": 1.10},
    "46-60": {"multiplier": 0.95},
    "61-75": {"multiplier": 1.10},
    "76-90": {"multiplier": 1.15},
}
