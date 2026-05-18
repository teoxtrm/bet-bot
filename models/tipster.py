"""
AI Tipster Engine — High Probability Selection.
No extra API calls: consumes data already fetched by the pre-game scan.
Returns the top 5 picks of the day, max 1 per match.

Singles: Over 1.5/2.5, Under 1.5/2.5, Home Win, Away Win — odds >= 1.40
Combos:  any two-leg accumulator where combined odds >= 1.40
         Win + Over/Under, Over + BTTS, Under + Win/Draw, etc.
"""

from dataclasses import dataclass, field
from models.pregame_model import poisson_over_prob

# ── Constants ─────────────────────────────────────────────────────────────────
TIER_LOCK   = 0.88
TIER_STRONG = 0.78
MIN_CONF    = 0.68
MAX_PICKS   = 5
MIN_ODDS    = 1.40

MIN_COMBO_CONF      = 0.50
MIN_COMBO_COMP_CONF = 0.65

# Min probability to even score a market (Pinnacle no-vig or Poisson-derived)
_MARKET_FLOOR = {
    "Over 1.5":   0.75,   # Poisson-derived
    "Over 2.5":   0.62,   # Pinnacle
    "Under 1.5":  0.45,   # Poisson-derived (low-scoring games)
    "Under 2.5":  0.58,   # Pinnacle
    "Home Win":   0.67,
    "Away Win":   0.62,
    "Draw":       0.28,   # only for combo legs, not singles
}

TIER_COLORS = {
    "LOCK":       "#00b894",
    "STRONG":     "#fdcb6e",
    "VALUE PLAY": "#74b9ff",
    "COMBO":      "#e17055",   # orange for combos
}


@dataclass
class TipsterPick:
    match:          str
    home_team:      str
    away_team:      str
    date:           str
    league:         str
    event_id:       str
    market:         str      # "Over 2.5", "Home Win", "1 + Over 2.5", …
    confidence:     float
    pinnacle_prob:  float    # primary probability (for combos: component 1)
    inferred_xg:    float
    best_odds:      float
    best_bookmaker: str
    signals:        list[str] = field(default_factory=list)
    is_combo:       bool = False

    @property
    def tier(self) -> str:
        if self.is_combo:
            return "COMBO"
        if self.confidence >= TIER_LOCK:
            return "LOCK"
        if self.confidence >= TIER_STRONG:
            return "STRONG"
        return "VALUE PLAY"

    @property
    def tier_color(self) -> str:
        return TIER_COLORS.get(self.tier, "#636e72")

    @property
    def confidence_pct(self) -> str:
        return f"{self.confidence:.0%}"


# ── Helpers ───────────────────────────────────────────────────────────────────

def _infer_xg(over_25_prob: float | None) -> float:
    """Binary-search λ such that P(X > 2.5) = over_25_prob."""
    if not over_25_prob or over_25_prob <= 0.01:
        return 2.0
    if over_25_prob >= 0.99:
        return 7.0
    lo, hi = 0.1, 10.0
    for _ in range(40):
        mid = (lo + hi) / 2
        if poisson_over_prob(mid, 2.5) > over_25_prob:
            hi = mid
        else:
            lo = mid
    return round((lo + hi) / 2, 2)


def _best_odds_for(event: dict, market_key: str, side: str, point: str | None) -> tuple[float, str]:
    best_odds, best_bm = 0.0, "—"
    for bm, bd in event.get("odds", {}).items():
        if bm == "pinnacle":
            continue
        if market_key == "totals":
            key  = f"{side}_{point}" if point else side
            odds = (bd.get("totals") or {}).get(key) or 0.0
        elif market_key == "h2h":
            odds = (bd.get("1x2") or {}).get(side) or 0.0
        else:
            odds = 0.0
        if odds and odds > best_odds:
            best_odds, best_bm = odds, bm
    return best_odds, best_bm


def _score(market: str, prob: float, xg: float, p_1x2: dict | None) -> tuple[float, list[str]]:
    """Return (confidence, signals)."""
    bonus   = 0.0
    signals = []

    if market == "Over 1.5":
        signals.append(f"Poisson O1.5: {prob:.0%} (xG {xg:.1f})")
        if xg >= 3.2:
            bonus = 0.03
            signals.append("Πολύ επιθετικό")
        elif xg >= 2.7:
            bonus = 0.015

    elif market == "Over 2.5":
        signals.append(f"Pinnacle O2.5: {prob:.0%}")
        signals.append(f"xG {xg:.1f}")
        if xg >= 3.5:
            bonus = 0.025
            signals.append("Επιθετικό")
        elif xg >= 2.9:
            bonus = 0.01

    elif market == "Under 2.5":
        signals.append(f"Pinnacle U2.5: {prob:.0%}")
        signals.append(f"xG {xg:.1f}")
        if xg <= 1.8:
            bonus = 0.025
            signals.append("Αμυντικό")
        elif xg <= 2.2:
            bonus = 0.01

    elif market == "Under 1.5":
        signals.append(f"Poisson U1.5: {prob:.0%} (xG {xg:.1f})")
        if xg <= 1.4:
            bonus = 0.03
            signals.append("Πολύ αμυντικό παιχνίδι")
        elif xg <= 1.8:
            bonus = 0.015

    elif market in ("Home Win", "Away Win"):
        signals.append(f"Pinnacle: {prob:.0%}")
        if p_1x2:
            draw = p_1x2.get("draw", 0.25)
            if draw < 0.17:
                bonus = 0.02
                signals.append(f"Draw {draw:.0%}")
        signals.append(f"xG {xg:.1f}")

    elif market == "Draw":
        signals.append(f"Draw: {prob:.0%}")
        if xg and xg <= 2.0:
            bonus = 0.01
            signals.append(f"xG {xg:.1f} — αμυντικό")
        else:
            signals.append(f"xG {xg:.1f}")

    return min(0.95, prob + bonus), signals


def _make_combo(
    match_label:  str,
    home: str, away: str, date: str, league: str, eid: str,
    leg1_label:   str,    # e.g. "1", "2", "Over 1.5"
    leg1_conf:    float,
    leg1_odds:    float,
    leg2_label:   str,    # e.g. "Over 2.5", "BTTS Yes"
    leg2_conf:    float,
    leg2_odds:    float,
    leg2_bm:      str,
    xg:           float,
    p_1x2:        dict | None,
    corr_bonus:   float = 1.05,  # slight positive correlation adjustment
) -> "TipsterPick | None":
    """
    Generic combo builder for any two-leg accumulator.
    Requires both legs >= MIN_COMBO_COMP_CONF and combined odds >= MIN_ODDS.
    """
    if leg1_conf < MIN_COMBO_COMP_CONF or leg2_conf < MIN_COMBO_COMP_CONF:
        return None
    if leg1_odds <= 1.0 or leg2_odds <= 1.0:
        return None

    combo_conf = min(0.90, leg1_conf * leg2_conf * corr_bonus)
    if combo_conf < MIN_COMBO_CONF:
        return None

    combo_odds = round(leg1_odds * leg2_odds, 2)
    if combo_odds < MIN_ODDS:
        return None

    market_label = f"{leg1_label} + {leg2_label}"
    draw = (p_1x2 or {}).get("draw", 0.25)
    signals = [
        f"{leg1_label}: {leg1_conf:.0%} @{leg1_odds}",
        f"{leg2_label}: {leg2_conf:.0%} @{leg2_odds}",
        f"xG {xg:.1f}",
    ]
    if draw < 0.17 and ("Win" in leg1_label or "1" == leg1_label or "2" == leg1_label):
        signals.append(f"Draw μόνο {draw:.0%}")

    return TipsterPick(
        match          = match_label,
        home_team      = home,
        away_team      = away,
        date           = date,
        league         = league,
        event_id       = eid,
        market         = market_label,
        confidence     = combo_conf,
        pinnacle_prob  = leg1_conf,
        inferred_xg    = xg,
        best_odds      = combo_odds,
        best_bookmaker = leg2_bm,
        signals        = signals,
        is_combo       = True,
    )


# ── Public API ────────────────────────────────────────────────────────────────

def score_event(
    event:  dict,
    p_1x2:  dict | None,
    p_ou:   dict | None,
    league: str,
) -> list["TipsterPick"]:
    """Score one event. Returns qualifying TipsterPick objects (singles + combos)."""
    picks = []
    home  = event.get("home_team", "")
    away  = event.get("away_team", "")
    dt    = event.get("commence", "")[:10]
    eid   = event.get("id", "")
    label = f"{home} vs {away}"

    over_25_prob = p_ou.get("over_prob") if p_ou else None
    xg = _infer_xg(over_25_prob)

    # ── Build candidate checks ────────────────────────────────────────────────
    checks = []

    if p_ou:
        pt_str   = str(p_ou.get("point", 2.5)).replace(".", "_")
        over_25  = p_ou.get("over_prob", 0)
        under_25 = p_ou.get("under_prob", 0)
        if over_25 >= _MARKET_FLOOR["Over 2.5"]:
            checks.append(("Over 2.5",  over_25,  "totals", "over",  pt_str))
        if under_25 >= _MARKET_FLOOR["Under 2.5"]:
            checks.append(("Under 2.5", under_25, "totals", "under", pt_str))

    if xg > 0:
        o15_prob = poisson_over_prob(xg, 1.5)
        u15_prob = 1.0 - o15_prob          # P(X <= 1) = Under 1.5
        if o15_prob >= _MARKET_FLOOR["Over 1.5"]:
            checks.append(("Over 1.5",  o15_prob, "totals", "over",  "1_5"))
        if u15_prob >= _MARKET_FLOOR["Under 1.5"]:
            checks.append(("Under 1.5", u15_prob, "totals", "under", "1_5"))

    if p_1x2:
        home_p = p_1x2.get("home", 0)
        away_p = p_1x2.get("away", 0)
        draw_p = p_1x2.get("draw", 0)
        if home_p >= _MARKET_FLOOR["Home Win"]:
            checks.append(("Home Win", home_p, "h2h", "home", None))
        if away_p >= _MARKET_FLOOR["Away Win"]:
            checks.append(("Away Win", away_p, "h2h", "away", None))
        # Draw only for combo legs (requires higher prob floor for single)
        if draw_p >= _MARKET_FLOOR["Draw"]:
            checks.append(("Draw", draw_p, "h2h", "draw", None))

    # ── Score each candidate ──────────────────────────────────────────────────
    # Buckets for combo generation (populated regardless of single eligibility)
    win_pool:   dict = {}  # {"Home Win": {"conf":, "odds":, "label": "1"}, ...}
    over_pool:  dict = {}  # {"Over 2.5": {"conf":, "odds":, "bm":}, "Over 1.5": {...}}
    under_pool: dict = {}  # {"Under 2.5": {"conf":, "odds":, "bm":}, "Under 1.5": {...}}
    draw_pool:  dict = {}  # {"Draw": {"conf":, "odds":, "bm":}}
    btts_pool:  dict = {}  # {"BTTS Yes": {"conf":, "odds":, "bm":}}

    for market, prob, mkt_key, side, pt in checks:
        conf, signals = _score(market, prob, xg, p_1x2)
        best_odds, best_bm = _best_odds_for(event, mkt_key, side, pt)
        if best_odds <= 1.0:
            continue

        # Feed combo pools (no confidence floor here — combos filter themselves)
        if market == "Over 2.5":
            over_pool["Over 2.5"] = {"conf": conf, "odds": best_odds, "bm": best_bm}
        elif market == "Over 1.5":
            over_pool["Over 1.5"] = {"conf": conf, "odds": best_odds, "bm": best_bm}
        elif market == "Under 2.5":
            under_pool["Under 2.5"] = {"conf": conf, "odds": best_odds, "bm": best_bm}
        elif market == "Under 1.5":
            under_pool["Under 1.5"] = {"conf": conf, "odds": best_odds, "bm": best_bm}
        elif market == "Home Win":
            win_pool["Home Win"] = {"conf": conf, "odds": best_odds, "label": "1"}
        elif market == "Away Win":
            win_pool["Away Win"] = {"conf": conf, "odds": best_odds, "label": "2"}
        elif market == "Draw":
            draw_pool["Draw"] = {"conf": conf, "odds": best_odds, "bm": best_bm}

        if conf < MIN_CONF:
            continue

        # Singles: only include if odds >= MIN_ODDS
        if best_odds >= MIN_ODDS:
            picks.append(TipsterPick(
                match          = label,
                home_team      = home,
                away_team      = away,
                date           = dt,
                league         = league,
                event_id       = eid,
                market         = market,
                confidence     = conf,
                pinnacle_prob  = prob,
                inferred_xg    = xg,
                best_odds      = best_odds,
                best_bookmaker = best_bm,
                signals        = signals,
            ))

    # ── BTTS estimated from soft book odds ────────────────────────────────────
    btts_odds, btts_bm = _best_odds_for(event, "btts", "yes", None)
    if btts_odds > 1.0:
        # BTTS implied probability (no Pinnacle for this market → use best soft book)
        btts_conf = min(0.85, 1 / btts_odds * 1.08)  # remove ~8% soft book margin
        btts_pool["BTTS Yes"] = {"conf": btts_conf, "odds": btts_odds, "bm": btts_bm}

    # ── Generate combos ───────────────────────────────────────────────────────
    combo_args = dict(
        match_label=label, home=home, away=away, date=dt,
        league=league, eid=eid, xg=xg, p_1x2=p_1x2,
    )

    # Win + Over X.X  (try both O1.5 and O2.5 for each Win side)
    for win_mkt, wd in win_pool.items():
        for over_mkt, od in over_pool.items():
            # Correlation: Win+Over is positively correlated (attacking game → more goals)
            combo = _make_combo(
                **combo_args,
                leg1_label=wd["label"], leg1_conf=wd["conf"], leg1_odds=wd["odds"],
                leg2_label=over_mkt,   leg2_conf=od["conf"], leg2_odds=od["odds"],
                leg2_bm=od["bm"], corr_bonus=1.08,
            )
            if combo:
                picks.append(combo)

    # Over 1.5 + BTTS Yes  (both expect goals from both sides)
    if "Over 1.5" in over_pool and btts_pool:
        od  = over_pool["Over 1.5"]
        bd  = btts_pool["BTTS Yes"]
        combo = _make_combo(
            **combo_args,
            leg1_label="Over 1.5", leg1_conf=od["conf"], leg1_odds=od["odds"],
            leg2_label="BTTS Yes", leg2_conf=bd["conf"], leg2_odds=bd["odds"],
            leg2_bm=bd["bm"], corr_bonus=1.10,  # strong positive correlation
        )
        if combo:
            picks.append(combo)

    # Over 2.5 + BTTS Yes
    if "Over 2.5" in over_pool and btts_pool:
        od  = over_pool["Over 2.5"]
        bd  = btts_pool["BTTS Yes"]
        combo = _make_combo(
            **combo_args,
            leg1_label="Over 2.5", leg1_conf=od["conf"], leg1_odds=od["odds"],
            leg2_label="BTTS Yes", leg2_conf=bd["conf"], leg2_odds=bd["odds"],
            leg2_bm=bd["bm"], corr_bonus=1.10,
        )
        if combo:
            picks.append(combo)

    # Win + Under X.X  (clean win: 1-0, 2-0 — dominant but low-scoring)
    for win_mkt, wd in win_pool.items():
        for under_mkt, ud in under_pool.items():
            combo = _make_combo(
                **combo_args,
                leg1_label=wd["label"], leg1_conf=wd["conf"], leg1_odds=wd["odds"],
                leg2_label=under_mkt,   leg2_conf=ud["conf"], leg2_odds=ud["odds"],
                leg2_bm=ud["bm"], corr_bonus=1.05,
            )
            if combo:
                picks.append(combo)

    # Draw + Under X.X  (defensive stalemate: 0-0, 1-1)
    if draw_pool and under_pool:
        dd = draw_pool["Draw"]
        for under_mkt, ud in under_pool.items():
            combo = _make_combo(
                **combo_args,
                leg1_label="X",        leg1_conf=dd["conf"], leg1_odds=dd["odds"],
                leg2_label=under_mkt,  leg2_conf=ud["conf"], leg2_odds=ud["odds"],
                leg2_bm=ud["bm"], corr_bonus=1.08,  # draw and under are strongly correlated
            )
            if combo:
                picks.append(combo)

    return picks


def generate_picks(events_data: list[dict]) -> list[TipsterPick]:
    """
    Process all events and return top MAX_PICKS picks.
    Dedup: combos and singles compete together; max 1 pick per (match, is_combo) pair
    so a match can appear once as a single AND once as a combo.
    """
    all_picks = []
    for item in events_data:
        picks = score_event(
            event  = item["event"],
            p_1x2  = item.get("p_1x2"),
            p_ou   = item.get("p_ou"),
            league = item.get("league", ""),
        )
        all_picks.extend(picks)

    # Sort by confidence descending
    all_picks.sort(key=lambda p: -p.confidence)

    # Dedup: max 1 single per match + max 1 combo per match
    seen_singles: set[str] = set()
    seen_combos:  set[str] = set()
    deduped = []
    for p in all_picks:
        if p.is_combo:
            if p.match not in seen_combos:
                seen_combos.add(p.match)
                deduped.append(p)
        else:
            if p.match not in seen_singles:
                seen_singles.add(p.match)
                deduped.append(p)

    # Re-sort and cap
    deduped.sort(key=lambda p: -p.confidence)
    return deduped[:MAX_PICKS]
