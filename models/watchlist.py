"""
Live Watchlist — scores today's scheduled games for live HT betting potential.
No extra API calls: consumes data already fetched by the pre-game scan.

A game scores high when:
  • Pinnacle P(HT Over 0.5) is high          → likely first-half goal
  • P(Over 2.5) is in the 55-72% sweet spot  → attacking but uncertain enough
                                                that live odds move meaningfully
  • Tier-1/2 league                           → Pinnacle prices HT lines well
"""

from dataclasses import dataclass


@dataclass
class WatchlistGame:
    match:        str
    home_team:    str
    away_team:    str
    kickoff:      str    # ISO datetime string
    league:       str
    sport_key:    str
    over_25_prob: float
    ht_05_prob:   float | None   # Pinnacle no-vig HT Over 0.5
    ht_15_prob:   float | None   # Pinnacle no-vig HT Over 1.5
    live_score:   float          # 0.0 – 1.0 composite

    @property
    def kickoff_time(self) -> str:
        """HH:MM from ISO string, converted to local-ish display."""
        try:
            from datetime import datetime, timezone, timedelta
            dt = datetime.fromisoformat(self.kickoff.replace("Z", "+00:00"))
            # No tzinfo conversion — show UTC, user knows their offset
            return dt.strftime("%H:%M")
        except Exception:
            return self.kickoff[11:16] if len(self.kickoff) >= 16 else "—"

    @property
    def rating(self) -> str:
        if self.live_score >= 0.72:
            return "MUST WATCH"
        if self.live_score >= 0.58:
            return "WATCH"
        return "MONITOR"

    @property
    def rating_color(self) -> str:
        if self.live_score >= 0.72:
            return "#00b894"   # green
        if self.live_score >= 0.58:
            return "#fdcb6e"   # yellow
        return "#636e72"       # grey


def _ou_sweet_spot(prob: float) -> float:
    """
    Score how "valuable" this O2.5 probability is for live betting.
    Sweet spot is 55-72%: enough goals expected, but not so certain
    that live in-play odds collapse at kick-off.
    """
    if 0.55 <= prob <= 0.72:
        return 1.0
    if 0.50 <= prob < 0.55:
        return 0.75
    if 0.72 < prob <= 0.80:
        return 0.70
    if 0.45 <= prob < 0.50:
        return 0.40
    return 0.15   # either too defensive (<45%) or too attacking (>80%)


def score_live_potential(
    over_25_prob: float,
    ht_05_prob:   float | None,
    ht_15_prob:   float | None,
    league_tier:  int,
) -> float:
    """
    Composite live HT betting potential score (0–1).

    Weights:
      45% → HT Over 0.5 probability (main signal for HT bets)
      35% → O2.5 sweet-spot score   (is this the right type of game?)
      20% → league tier bonus       (quality of Pinnacle HT market coverage)
    """
    # HT factor — best available HT signal
    if ht_05_prob is not None:
        ht_factor = ht_05_prob
    elif ht_15_prob is not None:
        # Scale up slightly: if P(HT O1.5)=0.45, P(HT O0.5) is likely ~0.75
        ht_factor = min(0.95, ht_15_prob * 1.55)
    else:
        # Fallback: estimate HT Over 0.5 from full-game Over 2.5
        ht_factor = over_25_prob * 0.78

    tier_bonus = {1: 1.0, 2: 0.80, 3: 0.55}.get(league_tier, 0.55)

    score = (
        ht_factor                       * 0.45
        + _ou_sweet_spot(over_25_prob)  * 0.35
        + tier_bonus                    * 0.20
    )
    return round(min(1.0, score), 4)


def generate_watchlist(
    events_data: list[dict],
    max_games:   int = 6,
) -> list[WatchlistGame]:
    """
    Score every event from the pre-game scan and return the top max_games
    candidates sorted by live betting potential (highest first).
    """
    games: list[WatchlistGame] = []

    for item in events_data:
        ev     = item.get("event", {})
        p_ou   = item.get("p_ou")
        p_ht   = item.get("p_ht")
        p_ht15 = item.get("p_ht15")
        league = item.get("league", "")
        tier   = item.get("tier", 2)

        if not p_ou:
            continue

        over_25 = p_ou.get("over_prob", 0)
        ht_05   = p_ht.get("over_prob")   if p_ht   else None
        ht_15   = p_ht15.get("over_prob") if p_ht15 else None

        live_score = score_live_potential(over_25, ht_05, ht_15, tier)

        games.append(WatchlistGame(
            match        = f"{ev.get('home_team','')} vs {ev.get('away_team','')}",
            home_team    = ev.get("home_team", ""),
            away_team    = ev.get("away_team", ""),
            kickoff      = ev.get("commence", ""),
            league       = league,
            sport_key    = ev.get("sport", ""),
            over_25_prob = over_25,
            ht_05_prob   = ht_05,
            ht_15_prob   = ht_15,
            live_score   = live_score,
        ))

    games.sort(key=lambda g: -g.live_score)
    return games[:max_games]
