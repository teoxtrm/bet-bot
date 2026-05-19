"""
Central configuration for bet-bot.
Strategy focus: HT Over 0.5/1.5, Over/Under 2.5, 1X2, Corners, Combos.
"""

# ── Tip quality filters (pre-game) ───────────────────────────────────────────
MIN_TIP_PROBABILITY  = 0.60   # Minimum model probability to generate a tip
MIN_TIP_ODDS_SINGLE  = 1.35   # Skip tips shorter than this (not worth playing)
MIN_TIP_ODDS_COMBO   = 1.65   # Minimum combined odds for 2-leg combos
MAX_PREGAME_TIPS     = 3      # Quality over quantity — best 2-3 per day

# ── Live watch-list scoring weights ──────────────────────────────────────────
LIVE_HT_WEIGHT      = 0.50   # Weight of HT goal probability in live candidate score
LIVE_O25_WEIGHT     = 0.30   # Weight of Over 2.5 probability
LIVE_TIER_WEIGHT    = 0.20   # Weight of league strategic quality (strategy_score / 10)
MAX_LIVE_CANDIDATES = 5      # Max games saved to live watch list per scan

# ── Pre-game → live flagging thresholds ───────────────────────────────────────
HT_FLAG_05 = 0.68            # Flag for live watch if P(HT Over 0.5) >= this
HT_FLAG_15 = 0.38            # Flag if P(HT Over 1.5) >= this
O25_FLAG   = 0.58            # Flag if P(Over 2.5) >= this

# ── API credit budgets (per day) ──────────────────────────────────────────────
ODDS_API_DAILY_BUDGET = 20   # Max Odds API credits/day (free tier: 500/month)
APIFB_DAILY_BUDGET    = 80   # Max API-Football req/day (free: 100/day; 20 reserved for live)

# ── Steam move detection ─────────────────────────────────────────────────────
STEAM_MOVE_THRESHOLD = 0.07  # Pinnacle prob shift > 7% between scans = sharp money signal
STEAM_CONFIDENCE_BOOST = 0.03  # Confidence bonus when steam detected on a market

# ── Legacy: value edge threshold (still used by value_calculator) ─────────────
MIN_VALUE_EDGE = 0.05        # 5% edge vs Pinnacle no-vig

# ── Live scan timing ──────────────────────────────────────────────────────────
LIVE_SCAN_INTERVAL_SEC = 120
LIVE_MIN_MINUTE        = 8   # Ignore first 8 mins (volatile)
LIVE_MAX_MINUTE        = 78  # Ignore after 78 mins (too late for HT bets)
LIVE_MAX_SCORE_DIFF    = 2   # Skip blowouts

LIVE_TIME_WEIGHTS = {
    "0-15":  {"multiplier": 1.00},
    "16-30": {"multiplier": 1.05},
    "31-45": {"multiplier": 1.10},  # Peak HT Over 0.5 window
    "46-60": {"multiplier": 0.95},
    "61-75": {"multiplier": 1.10},
    "76-90": {"multiplier": 1.15},
}
