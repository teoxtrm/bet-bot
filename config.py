"""
Κεντρικές ρυθμίσεις του bot.
"""

# --- Value Bet threshold ---
# Ελάχιστο edge (%) για να θεωρείται value bet
MIN_VALUE_EDGE = 0.05  # 5%

# --- Στοιχηματικές που παρακολουθούμε ---
BOOKMAKERS = ["stoiximan", "bet365", "novibet"]

# --- Sofascore API (ανεπίσημο, free) ---
SOFASCORE_BASE_URL = "https://api.sofascore.com/api/v1"
SOFASCORE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json",
    "Referer": "https://www.sofascore.com/",
}

# --- Αγορές που μας ενδιαφέρουν ---
MARKETS = {
    "over_under": [1.5, 2.5, 3.5],
    "both_teams_score": True,
    "corners": True,
}

# --- Live model παράμετροι ---
# Λεπτά σε αγώνα που αυξάνουν/μειώνουν πιθανότητες Over
LIVE_TIME_WEIGHTS = {
    "0-15":  {"multiplier": 1.0},
    "16-30": {"multiplier": 1.05},
    "31-45": {"multiplier": 1.10},
    "46-60": {"multiplier": 0.95},  # Μετά το ημίχρονο, πιο αργό ξεκίνημα
    "61-75": {"multiplier": 1.10},
    "76-90": {"multiplier": 1.15},
}

# --- Cache ---
CACHE_TTL_SECONDS = 300  # 5 λεπτά
