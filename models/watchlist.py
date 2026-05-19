"""
Live Watch List — scores today's games for live HT/goals betting potential.
No extra API calls: consumes data already fetched by the pre-game scan.

A game scores high when:
  • Pinnacle P(HT Over 0.5) is high          → likely first-half goal
  • P(Over 2.5) is in the 55-72% sweet spot  → attacking but not a certainty,
                                                so live odds move meaningfully
  • League strategy_score is high            → Pinnacle prices HT lines well
"""

from dataclasses import dataclass, field
from config import LIVE_HT_WEIGHT, LIVE_O25_WEIGHT, LIVE_TIER_WEIGHT, MAX_LIVE_CANDIDATES


@dataclass
class WatchlistGame:
    match:        str
    home_team:    str
    away_team:    str
    kickoff:      str       # ISO datetime string
    league:       str
    sport_key:    str
    over_25_prob: float
    ht_05_prob:   float | None
    ht_15_prob:   float | None
    live_score:   float     # 0.0–1.0 composite
    ht_tip:       str = ""  # primary market to watch, e.g. "HT Over 0.5"
    live_action:  str = ""  # instructions for live play

    @property
    def kickoff_time(self) -> str:
        try:
            from datetime import datetime
            dt = datetime.fromisoformat(self.kickoff.replace("Z", "+00:00"))
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
            return "#00b894"
        if self.live_score >= 0.58:
            return "#fdcb6e"
        return "#636e72"


def _ou_sweet_spot(prob: float) -> float:
    """
    Score how valuable this O2.5 probability is for live betting.
    Sweet spot 55-72%: enough goals expected, but live odds still move meaningfully.
    """
    if 0.55 <= prob <= 0.72:
        return 1.0
    if 0.50 <= prob < 0.55:
        return 0.75
    if 0.72 < prob <= 0.80:
        return 0.70
    if 0.45 <= prob < 0.50:
        return 0.40
    return 0.15


def _live_action(ht_05: float | None, ht_15: float | None, over_25: float) -> tuple[str, str]:
    """Return (ht_tip label, action text) based on the strongest HT signal."""
    if ht_15 is not None and ht_15 >= 0.40:
        return (
            "HT Over 1.5",
            f"HT Over 1.5 ({ht_15:.0%}). Enter live at min 5-10 if 0-0 for boosted odds.",
        )
    if ht_05 is not None and ht_05 >= 0.68:
        return (
            "HT Over 0.5",
            f"HT Over 0.5 ({ht_05:.0%}). Best window: min 5-20 if still 0-0.",
        )
    if over_25 >= 0.58:
        return (
            "Over 2.5",
            f"Over 2.5 ({over_25:.0%}). Enter live if 0-0 at min 10-20 for better odds.",
        )
    return (
        "Monitor",
        "Watch first 15 mins for momentum signals before entering.",
    )


def score_live_potential(
    over_25_prob:   float,
    ht_05_prob:     float | None,
    ht_15_prob:     float | None,
    strategy_score: int = 6,
) -> float:
    """
    Composite live HT betting potential score (0–1).

    Weights (from config):
      LIVE_HT_WEIGHT   → HT goal probability (primary signal)
      LIVE_O25_WEIGHT  → O2.5 sweet-spot score
      LIVE_TIER_WEIGHT → league strategic quality
    """
    if ht_05_prob is not None:
        ht_factor = ht_05_prob
    elif ht_15_prob is not None:
        ht_factor = min(0.95, ht_15_prob * 1.55)
    else:
        ht_factor = over_25_prob * 0.78

    strategy_factor = min(1.0, strategy_score / 10.0)

    return round(min(1.0,
        ht_factor                      * LIVE_HT_WEIGHT
        + _ou_sweet_spot(over_25_prob) * LIVE_O25_WEIGHT
        + strategy_factor              * LIVE_TIER_WEIGHT
    ), 4)


def _best_bm_over25(ev: dict) -> float | None:
    """Estimate P(Over 2.5) from best soft-book odds when Pinnacle has no totals."""
    best_odds = None
    for bm, bd in ev.get("odds", {}).items():
        if bm == "pinnacle":
            continue
        totals = bd.get("totals") or {}
        o = totals.get("over_2_5")
        if o is None:
            pts = [float(k.replace("over_", "").replace("_", "."))
                   for k in totals if k.startswith("over_")]
            if pts:
                closest = min(pts, key=lambda x: abs(x - 2.5))
                if abs(closest - 2.5) <= 0.5:
                    o = totals.get(f"over_{str(closest).replace('.', '_')}")
        if o and (best_odds is None or o > best_odds):
            best_odds = o
    if best_odds is None:
        return None
    return round(1 / best_odds, 4)


def generate_watchlist(
    events_data: list[dict],
    max_games:   int = MAX_LIVE_CANDIDATES,
) -> list[WatchlistGame]:
    """
    Score every event from the pre-game scan and return the top max_games
    live candidates sorted by live betting potential (highest first).
    """
    from utils.league_map import get_league_profile

    games: list[WatchlistGame] = []

    for item in events_data:
        ev     = item.get("event", {})
        p_ou   = item.get("p_ou")
        p_ht   = item.get("p_ht")
        p_ht15 = item.get("p_ht15")
        league = item.get("league", "")

        # Prefer strategy_score from events_data (set during scan), fall back to profile lookup
        strategy_score = item.get("strategy_score")
        if strategy_score is None:
            profile = get_league_profile(ev.get("sport", ""))
            strategy_score = profile.get("strategy_score", 6) if profile else 6

        if p_ou:
            over_25 = p_ou.get("over_prob", 0)
        else:
            over_25 = _best_bm_over25(ev)
            if over_25 is None:
                continue

        ht_05 = p_ht.get("over_prob")   if p_ht   else None
        ht_15 = p_ht15.get("over_prob") if p_ht15 else None

        live_score = score_live_potential(over_25, ht_05, ht_15, strategy_score)

        # Steam boost: sharp money on HT/Over markets → game is more interesting live
        from utils.steam import steam_markets as _steam_mkts
        _steam = _steam_mkts(item.get("steam_moves", []))
        if "HT Over 0.5" in _steam or "HT Over 1.5" in _steam:
            live_score = min(1.0, live_score + 0.08)
        elif "Over 2.5" in _steam:
            live_score = min(1.0, live_score + 0.05)

        ht_tip, live_action = _live_action(ht_05, ht_15, over_25)

        from utils.steam import format_steam_short
        _steam_label = format_steam_short(item.get("steam_moves", []))
        _action_full = (live_action + f"  {_steam_label}").strip() if _steam_label else live_action

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
            ht_tip       = ht_tip,
            live_action  = _action_full,
        ))

    games.sort(key=lambda g: -g.live_score)
    top = games[:max_games]
    print(f"[Watchlist] {len(events_data)} events → {len(games)} scored → top {len(top)}: "
          + ", ".join(f"{g.match[:22]} {g.ht_tip} ({g.live_score:.2f})" for g in top))
    return top
