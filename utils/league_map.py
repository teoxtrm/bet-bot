"""
Strategic league directory for bet-bot.

Strategy focus: HT Over 0.5/1.5, Game Over/Under 2.5, 1X2, Corners, Combos.

Tier 1 = PRIME   — Best fit for strategy. Always scan first.
Tier 2 = MAJOR   — Good for strategy. Scan as API budget allows.
Tier 3 = EXPAND  — Add later when budget grows.

Statistical profiles are approximate 3-season rolling averages.
They seed the prediction engine until the database builds its own historical data.
"""

# {api_football_league_id: league_dict}
# Legacy keys (used by existing code): name, odds_key, tier
# Strategy keys: country, avg_goals, avg_ht_goals, avg_corners,
#                ht_over_05_rate, ht_over_15_rate, over_25_rate, strategy_score
LEAGUE_MAP: dict[int, dict] = {

    # ── TIER 1 — PRIME (HT goal machines + strong corner counts) ──────────────

    88: {
        "name": "Eredivisie", "country": "Netherlands",
        "odds_key": "soccer_netherlands_eredivisie", "tier": 1,
        "avg_goals": 3.10, "avg_ht_goals": 1.42, "avg_corners": 10.2,
        "ht_over_05_rate": 0.73, "ht_over_15_rate": 0.37, "over_25_rate": 0.61,
        "strategy_score": 10,
    },
    78: {
        "name": "Bundesliga", "country": "Germany",
        "odds_key": "soccer_germany_bundesliga", "tier": 1,
        "avg_goals": 3.10, "avg_ht_goals": 1.42, "avg_corners": 10.1,
        "ht_over_05_rate": 0.72, "ht_over_15_rate": 0.36, "over_25_rate": 0.61,
        "strategy_score": 10,
    },
    40: {
        "name": "Championship", "country": "England",
        "odds_key": "soccer_efl_champ", "tier": 1,
        "avg_goals": 2.82, "avg_ht_goals": 1.32, "avg_corners": 10.6,
        "ht_over_05_rate": 0.68, "ht_over_15_rate": 0.31, "over_25_rate": 0.55,
        "strategy_score": 9,
    },
    144: {
        "name": "Pro League Belgium", "country": "Belgium",
        "odds_key": "soccer_belgium_first_div", "tier": 1,
        "avg_goals": 2.88, "avg_ht_goals": 1.35, "avg_corners": 9.8,
        "ht_over_05_rate": 0.70, "ht_over_15_rate": 0.34, "over_25_rate": 0.58,
        "strategy_score": 9,
    },
    119: {
        "name": "Superligaen", "country": "Denmark",
        "odds_key": "soccer_denmark_superliga", "tier": 1,
        "avg_goals": 2.85, "avg_ht_goals": 1.32, "avg_corners": 9.5,
        "ht_over_05_rate": 0.68, "ht_over_15_rate": 0.32, "over_25_rate": 0.57,
        "strategy_score": 9,
    },
    203: {
        "name": "Süper Lig", "country": "Turkey",
        "odds_key": "soccer_turkey_super_league", "tier": 1,
        "avg_goals": 2.90, "avg_ht_goals": 1.35, "avg_corners": 9.6,
        "ht_over_05_rate": 0.70, "ht_over_15_rate": 0.33, "over_25_rate": 0.57,
        "strategy_score": 9,
    },
    79: {
        "name": "2. Bundesliga", "country": "Germany",
        "odds_key": "soccer_germany_bundesliga2", "tier": 1,
        "avg_goals": 2.90, "avg_ht_goals": 1.35, "avg_corners": 9.8,
        "ht_over_05_rate": 0.69, "ht_over_15_rate": 0.33, "over_25_rate": 0.58,
        "strategy_score": 9,
    },
    # Netherlands second division — nearly as attacking as Eredivisie
    89: {
        "name": "Eerste Divisie", "country": "Netherlands",
        "odds_key": "soccer_netherlands_eerste_divisie", "tier": 1,
        "avg_goals": 3.05, "avg_ht_goals": 1.38, "avg_corners": 9.8,
        "ht_over_05_rate": 0.71, "ht_over_15_rate": 0.35, "over_25_rate": 0.60,
        "strategy_score": 9,
    },
    41: {
        "name": "League One", "country": "England",
        "odds_key": "soccer_england_league1", "tier": 1,
        "avg_goals": 2.75, "avg_ht_goals": 1.28, "avg_corners": 10.4,
        "ht_over_05_rate": 0.66, "ht_over_15_rate": 0.30, "over_25_rate": 0.54,
        "strategy_score": 8,
    },
    42: {
        "name": "League Two", "country": "England",
        "odds_key": "soccer_england_league2", "tier": 1,
        "avg_goals": 2.72, "avg_ht_goals": 1.25, "avg_corners": 10.2,
        "ht_over_05_rate": 0.66, "ht_over_15_rate": 0.29, "over_25_rate": 0.53,
        "strategy_score": 8,
    },
    103: {
        "name": "Eliteserien", "country": "Norway",
        "odds_key": "soccer_norway_eliteserien", "tier": 1,
        "avg_goals": 2.80, "avg_ht_goals": 1.28, "avg_corners": 9.2,
        "ht_over_05_rate": 0.67, "ht_over_15_rate": 0.30, "over_25_rate": 0.55,
        "strategy_score": 8,
    },
    39: {
        "name": "Premier League", "country": "England",
        "odds_key": "soccer_epl", "tier": 1,
        "avg_goals": 2.82, "avg_ht_goals": 1.30, "avg_corners": 10.8,
        "ht_over_05_rate": 0.68, "ht_over_15_rate": 0.30, "over_25_rate": 0.52,
        "strategy_score": 8,
    },
    113: {
        "name": "Allsvenskan", "country": "Sweden",
        "odds_key": "soccer_sweden_allsvenskan", "tier": 1,
        "avg_goals": 2.72, "avg_ht_goals": 1.25, "avg_corners": 9.1,
        "ht_over_05_rate": 0.66, "ht_over_15_rate": 0.28, "over_25_rate": 0.54,
        "strategy_score": 8,
    },
    218: {
        "name": "Austrian Bundesliga", "country": "Austria",
        "odds_key": "soccer_austria_bundesliga", "tier": 1,
        "avg_goals": 2.88, "avg_ht_goals": 1.33, "avg_corners": 9.5,
        "ht_over_05_rate": 0.69, "ht_over_15_rate": 0.32, "over_25_rate": 0.57,
        "strategy_score": 8,
    },

    # ── TIER 2 — MAJOR (solid leagues, scan as budget allows) ─────────────────

    141: {
        "name": "La Liga 2", "country": "Spain",
        "odds_key": "soccer_spain_segunda_division", "tier": 2,
        "avg_goals": 2.65, "avg_ht_goals": 1.20, "avg_corners": 9.5,
        "ht_over_05_rate": 0.65, "ht_over_15_rate": 0.28, "over_25_rate": 0.52,
        "strategy_score": 7,
    },
    136: {
        "name": "Serie B", "country": "Italy",
        "odds_key": "soccer_italy_serie_b", "tier": 2,
        "avg_goals": 2.62, "avg_ht_goals": 1.18, "avg_corners": 9.3,
        "ht_over_05_rate": 0.64, "ht_over_15_rate": 0.27, "over_25_rate": 0.52,
        "strategy_score": 7,
    },
    62: {
        "name": "Ligue 2", "country": "France",
        "odds_key": "soccer_france_ligue_two", "tier": 2,
        "avg_goals": 2.68, "avg_ht_goals": 1.22, "avg_corners": 9.2,
        "ht_over_05_rate": 0.65, "ht_over_15_rate": 0.28, "over_25_rate": 0.53,
        "strategy_score": 7,
    },
    179: {
        "name": "Scottish Premiership", "country": "Scotland",
        "odds_key": "soccer_scotland_premiership", "tier": 2,
        "avg_goals": 2.80, "avg_ht_goals": 1.28, "avg_corners": 10.3,
        "ht_over_05_rate": 0.67, "ht_over_15_rate": 0.29, "over_25_rate": 0.54,
        "strategy_score": 7,
    },
    140: {
        "name": "La Liga", "country": "Spain",
        "odds_key": "soccer_spain_la_liga", "tier": 2,
        "avg_goals": 2.55, "avg_ht_goals": 1.15, "avg_corners": 9.8,
        "ht_over_05_rate": 0.63, "ht_over_15_rate": 0.25, "over_25_rate": 0.49,
        "strategy_score": 6,
    },
    135: {
        "name": "Serie A", "country": "Italy",
        "odds_key": "soccer_italy_serie_a", "tier": 2,
        "avg_goals": 2.58, "avg_ht_goals": 1.15, "avg_corners": 9.5,
        "ht_over_05_rate": 0.63, "ht_over_15_rate": 0.25, "over_25_rate": 0.50,
        "strategy_score": 6,
    },
    61: {
        "name": "Ligue 1", "country": "France",
        "odds_key": "soccer_france_ligue_one", "tier": 2,
        "avg_goals": 2.58, "avg_ht_goals": 1.15, "avg_corners": 9.2,
        "ht_over_05_rate": 0.63, "ht_over_15_rate": 0.26, "over_25_rate": 0.50,
        "strategy_score": 6,
    },
    106: {
        "name": "Ekstraklasa", "country": "Poland",
        "odds_key": "soccer_poland_ekstraklasa", "tier": 2,
        "avg_goals": 2.65, "avg_ht_goals": 1.20, "avg_corners": 9.0,
        "ht_over_05_rate": 0.64, "ht_over_15_rate": 0.27, "over_25_rate": 0.52,
        "strategy_score": 6,
    },
    94: {
        "name": "Primeira Liga", "country": "Portugal",
        "odds_key": "soccer_portugal_primeira_liga", "tier": 2,
        "avg_goals": 2.65, "avg_ht_goals": 1.20, "avg_corners": 9.4,
        "ht_over_05_rate": 0.64, "ht_over_15_rate": 0.26, "over_25_rate": 0.51,
        "strategy_score": 6,
    },
    197: {
        "name": "Super League Greece", "country": "Greece",
        "odds_key": "soccer_greece_super_league", "tier": 2,
        "avg_goals": 2.50, "avg_ht_goals": 1.10, "avg_corners": 9.1,
        "ht_over_05_rate": 0.62, "ht_over_15_rate": 0.23, "over_25_rate": 0.47,
        "strategy_score": 5,
    },
    # UEFA competitions — tactical, fewer HT goals than domestic leagues
    2: {
        "name": "Champions League", "country": "Europe",
        "odds_key": "soccer_uefa_champs_league", "tier": 2,
        "avg_goals": 2.68, "avg_ht_goals": 1.18, "avg_corners": 9.6,
        "ht_over_05_rate": 0.64, "ht_over_15_rate": 0.26, "over_25_rate": 0.52,
        "strategy_score": 6,
    },
    3: {
        "name": "Europa League", "country": "Europe",
        "odds_key": "soccer_uefa_europa_league", "tier": 2,
        "avg_goals": 2.72, "avg_ht_goals": 1.22, "avg_corners": 9.4,
        "ht_over_05_rate": 0.65, "ht_over_15_rate": 0.27, "over_25_rate": 0.53,
        "strategy_score": 6,
    },
    848: {
        "name": "Conference League", "country": "Europe",
        "odds_key": "soccer_uefa_europa_conference_league", "tier": 2,
        "avg_goals": 2.78, "avg_ht_goals": 1.25, "avg_corners": 9.3,
        "ht_over_05_rate": 0.66, "ht_over_15_rate": 0.28, "over_25_rate": 0.54,
        "strategy_score": 6,
    },

    # ── TIER 3 — EXPAND (add when Odds API budget grows) ──────────────────────

    71: {
        "name": "Brasileirao", "country": "Brazil",
        "odds_key": "soccer_brazil_campeonato", "tier": 3,
        "avg_goals": 2.60, "avg_ht_goals": 1.12, "avg_corners": 8.8,
        "ht_over_05_rate": 0.62, "ht_over_15_rate": 0.23, "over_25_rate": 0.50,
        "strategy_score": 5,
    },
    128: {
        "name": "Argentina Primera", "country": "Argentina",
        "odds_key": "soccer_argentina_primera_division", "tier": 3,
        "avg_goals": 2.68, "avg_ht_goals": 1.18, "avg_corners": 8.6,
        "ht_over_05_rate": 0.64, "ht_over_15_rate": 0.25, "over_25_rate": 0.52,
        "strategy_score": 5,
    },
    130: {
        "name": "Liga MX", "country": "Mexico",
        "odds_key": "soccer_mexico_ligamx", "tier": 3,
        "avg_goals": 2.62, "avg_ht_goals": 1.15, "avg_corners": 8.7,
        "ht_over_05_rate": 0.63, "ht_over_15_rate": 0.24, "over_25_rate": 0.50,
        "strategy_score": 5,
    },
    253: {
        "name": "MLS", "country": "USA",
        "odds_key": "soccer_usa_mls", "tier": 3,
        "avg_goals": 2.80, "avg_ht_goals": 1.25, "avg_corners": 8.9,
        "ht_over_05_rate": 0.66, "ht_over_15_rate": 0.28, "over_25_rate": 0.55,
        "strategy_score": 6,
    },
    98: {
        "name": "J1 League", "country": "Japan",
        "odds_key": "soccer_japan_j_league", "tier": 3,
        "avg_goals": 2.42, "avg_ht_goals": 1.05, "avg_corners": 8.5,
        "ht_over_05_rate": 0.60, "ht_over_15_rate": 0.21, "over_25_rate": 0.45,
        "strategy_score": 4,
    },
}

# ── Reverse lookups ───────────────────────────────────────────────────────────
ODDS_KEY_TO_LEAGUE: dict[str, dict] = {
    v["odds_key"]: {"id": k, **v} for k, v in LEAGUE_MAP.items()
}

ALL_LIVE_SPORT_KEYS: list[str] = sorted({v["odds_key"] for v in LEAGUE_MAP.values()})


# ── Strategy helpers ──────────────────────────────────────────────────────────

def get_prime_keys() -> list[str]:
    """Odds API keys for Tier 1 (PRIME) leagues, best-first by strategy_score."""
    leagues = [v for v in LEAGUE_MAP.values() if v["tier"] == 1]
    leagues.sort(key=lambda x: x["strategy_score"], reverse=True)
    return [v["odds_key"] for v in leagues]


def get_starter_keys(n: int = 8) -> list[str]:
    """
    Top N leagues by strategy_score for daily scans on a tight API budget.
    Default 8 = ~8 Odds API credits per scan, comfortable within 500/month free tier.
    """
    scored = sorted(LEAGUE_MAP.values(), key=lambda x: x["strategy_score"], reverse=True)
    return [v["odds_key"] for v in scored[:n]]


def get_league_profile(odds_key: str) -> dict | None:
    """Full league dict by Odds API key, or None if not in LEAGUE_MAP."""
    return ODDS_KEY_TO_LEAGUE.get(odds_key)


def strategy_label(score: int) -> str:
    """Human-readable label for strategy_score."""
    if score >= 9:
        return "PRIME"
    if score >= 7:
        return "GOOD"
    if score >= 5:
        return "OK"
    return "LOW"
