"""
Maps API-Football league IDs to Odds API sport keys and quality tiers.

Tier 1 = major top divisions  (Pinnacle always prices, high liquidity)
Tier 2 = second divisions     (Pinnacle usually prices, decent liquidity)
Tier 3 = other active leagues (Pinnacle sometimes prices)

Used by discover_live_matches() to filter and rank live candidates
before spending any Odds API credits.
"""

# {api_football_league_id: {name, odds_key, tier}}
LEAGUE_MAP: dict[int, dict] = {
    # ── Tier 1 — Top European ─────────────────────────────────────────────────
    39:  {"name": "Premier League",       "odds_key": "soccer_epl",                          "tier": 1},
    140: {"name": "La Liga",              "odds_key": "soccer_spain_la_liga",                "tier": 1},
    78:  {"name": "Bundesliga",           "odds_key": "soccer_germany_bundesliga",           "tier": 1},
    135: {"name": "Serie A",              "odds_key": "soccer_italy_serie_a",                "tier": 1},
    61:  {"name": "Ligue 1",              "odds_key": "soccer_france_ligue_one",             "tier": 1},
    88:  {"name": "Eredivisie",           "odds_key": "soccer_netherlands_eredivisie",       "tier": 1},
    94:  {"name": "Primeira Liga",        "odds_key": "soccer_portugal_primeira_liga",       "tier": 1},
    197: {"name": "Super League Greece",  "odds_key": "soccer_greece_super_league",          "tier": 1},
    203: {"name": "Süper Lig Turkey",     "odds_key": "soccer_turkey_super_league",          "tier": 1},
    144: {"name": "Pro League Belgium",   "odds_key": "soccer_belgium_first_div",            "tier": 1},
    179: {"name": "Scottish Premiership", "odds_key": "soccer_scotland_premiership",         "tier": 1},
    # ── Tier 1 — UEFA Competitions ────────────────────────────────────────────
    2:   {"name": "Champions League",     "odds_key": "soccer_uefa_champs_league",           "tier": 1},
    3:   {"name": "Europa League",        "odds_key": "soccer_uefa_europa_league",           "tier": 1},
    848: {"name": "Conference League",    "odds_key": "soccer_uefa_europa_conference_league","tier": 1},
    # ── Tier 2 — Second Divisions ─────────────────────────────────────────────
    40:  {"name": "Championship",         "odds_key": "soccer_efl_champ",                   "tier": 2},
    41:  {"name": "League One",           "odds_key": "soccer_england_league1",             "tier": 2},
    141: {"name": "La Liga 2",            "odds_key": "soccer_spain_segunda_division",       "tier": 2},
    79:  {"name": "2. Bundesliga",        "odds_key": "soccer_germany_bundesliga2",          "tier": 2},
    136: {"name": "Serie B",              "odds_key": "soccer_italy_serie_b",                "tier": 2},
    62:  {"name": "Ligue 2",              "odds_key": "soccer_france_ligue_two",             "tier": 2},
    113: {"name": "Allsvenskan",          "odds_key": "soccer_sweden_allsvenskan",           "tier": 2},
    119: {"name": "Superligaen Denmark",  "odds_key": "soccer_denmark_superliga",            "tier": 2},
    103: {"name": "Eliteserien Norway",   "odds_key": "soccer_norway_eliteserien",           "tier": 2},
    106: {"name": "Ekstraklasa Poland",   "odds_key": "soccer_poland_ekstraklasa",           "tier": 2},
    # ── Tier 3 — Global ───────────────────────────────────────────────────────
    71:  {"name": "Brasileirao",          "odds_key": "soccer_brazil_campeonato",            "tier": 3},
    128: {"name": "Argentina Primera",    "odds_key": "soccer_argentina_primera_division",   "tier": 3},
    130: {"name": "Liga MX",              "odds_key": "soccer_mexico_ligamx",                "tier": 3},
    253: {"name": "MLS",                  "odds_key": "soccer_usa_mls",                      "tier": 3},
    98:  {"name": "J1 League Japan",      "odds_key": "soccer_japan_j_league",               "tier": 3},
}

# Reverse lookup: odds_key → league info (for display)
ODDS_KEY_TO_LEAGUE: dict[str, dict] = {
    v["odds_key"]: {"id": k, **v} for k, v in LEAGUE_MAP.items()
}

# All unique Odds API sport keys we monitor
ALL_LIVE_SPORT_KEYS: list[str] = sorted({v["odds_key"] for v in LEAGUE_MAP.values()})
