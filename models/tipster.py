"""
Pre-game Tip Engine.
Produces up to MAX_PREGAME_TIPS picks per day: singles + combos.
Focus: HT Over 0.5/1.5, Over/Under 2.5, 1X2, and combos of those.
No extra API calls — consumes data already fetched by the pre-game scan.
"""

from dataclasses import dataclass, field
from config import MAX_PREGAME_TIPS, MIN_TIP_PROBABILITY, MIN_TIP_ODDS_SINGLE, MIN_TIP_ODDS_COMBO
from models.pregame_model import poisson_over_prob

# ── Confidence tiers ──────────────────────────────────────────────────────────
TIER_LOCK   = 0.82
TIER_STRONG = 0.72
MIN_CONF    = MIN_TIP_PROBABILITY    # 0.60
MAX_PICKS   = MAX_PREGAME_TIPS       # 3
MIN_ODDS    = MIN_TIP_ODDS_SINGLE    # 1.35
MIN_COMBO_ODDS = MIN_TIP_ODDS_COMBO  # 1.65

MIN_COMBO_LEG = 0.60  # each combo leg must clear this confidence floor

TIER_COLORS = {
    "LOCK":   "#00b894",
    "STRONG": "#fdcb6e",
    "TIP":    "#74b9ff",
    "COMBO":  "#e17055",
}

# Minimum Pinnacle no-vig probability to even consider a market
_MARKET_FLOOR = {
    "Over 1.5":    0.75,
    "Over 2.5":    0.60,
    "Under 1.5":   0.45,
    "Under 2.5":   0.58,
    "Home Win":    0.65,
    "Away Win":    0.60,
    "Draw":        0.28,   # combo legs only
    "HT Over 0.5": 0.68,
    "HT Over 1.5": 0.38,
}


@dataclass
class TipsterPick:
    match:          str
    home_team:      str
    away_team:      str
    date:           str
    league:         str
    event_id:       str
    market:         str
    confidence:     float
    pinnacle_prob:  float
    inferred_xg:    float
    best_odds:      float
    best_bookmaker: str
    signals:        list[str] = field(default_factory=list)
    is_combo:       bool = False
    stake:          float = 0.0

    @property
    def tier(self) -> str:
        if self.is_combo:
            return "COMBO"
        if self.confidence >= TIER_LOCK:
            return "LOCK"
        if self.confidence >= TIER_STRONG:
            return "STRONG"
        return "TIP"

    @property
    def tier_color(self) -> str:
        return TIER_COLORS.get(self.tier, "#636e72")

    @property
    def confidence_pct(self) -> str:
        return f"{self.confidence:.0%}"


# ── Helpers ───────────────────────────────────────────────────────────────────

def _infer_xg(over_25_prob: float | None) -> float:
    """Binary-search λ such that P(Poisson(λ) > 2.5) = over_25_prob."""
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
        if market_key in ("totals", "totals_h1"):
            key  = f"{side}_{point}" if point else side
            odds = (bd.get(market_key) or {}).get(key) or 0.0
        elif market_key == "h2h":
            odds = (bd.get("1x2") or {}).get(side) or 0.0
        else:
            odds = 0.0
        if odds and odds > best_odds:
            best_odds, best_bm = odds, bm
    return best_odds, best_bm


def _score(market: str, prob: float, xg: float, p_1x2: dict | None) -> tuple[float, list[str]]:
    """Return (adjusted_confidence, signals)."""
    bonus   = 0.0
    signals = []

    if market == "Over 1.5":
        signals.append(f"Poisson O1.5: {prob:.0%} (xG {xg:.1f})")
        if xg >= 3.2:
            bonus = 0.03
            signals.append("Very attacking game")
        elif xg >= 2.7:
            bonus = 0.015

    elif market == "Over 2.5":
        signals.append(f"Pinnacle O2.5: {prob:.0%} | xG {xg:.1f}")
        if xg >= 3.5:
            bonus = 0.025
            signals.append("High-scoring game expected")
        elif xg >= 2.9:
            bonus = 0.01

    elif market == "Under 2.5":
        signals.append(f"Pinnacle U2.5: {prob:.0%} | xG {xg:.1f}")
        if xg <= 1.8:
            bonus = 0.025
            signals.append("Defensive game expected")
        elif xg <= 2.2:
            bonus = 0.01

    elif market == "Under 1.5":
        signals.append(f"Poisson U1.5: {prob:.0%} (xG {xg:.1f})")
        if xg <= 1.4:
            bonus = 0.03
            signals.append("Very defensive game")
        elif xg <= 1.8:
            bonus = 0.015

    elif market in ("Home Win", "Away Win"):
        signals.append(f"Pinnacle: {prob:.0%} | xG {xg:.1f}")
        if p_1x2:
            draw = p_1x2.get("draw", 0.25)
            if draw < 0.17:
                bonus = 0.02
                signals.append(f"Draw only {draw:.0%}")

    elif market == "Draw":
        signals.append(f"Draw: {prob:.0%}")
        signals.append(f"xG {xg:.1f}" + (" — defensive" if xg <= 2.0 else ""))
        if xg <= 2.0:
            bonus = 0.01

    elif market == "HT Over 0.5":
        signals.append(f"Pinnacle HT O0.5: {prob:.0%}")
        if prob >= 0.80:
            bonus = 0.025
            signals.append("Strong first-half pressure expected")
        elif prob >= 0.72:
            bonus = 0.01
            signals.append("High first-half goal probability")

    elif market == "HT Over 1.5":
        signals.append(f"Pinnacle HT O1.5: {prob:.0%}")
        if prob >= 0.50:
            bonus = 0.025
            signals.append("Multi-goal first half likely")
        elif prob >= 0.42:
            bonus = 0.01
            signals.append("Active first half expected")

    return min(0.95, prob + bonus), signals


def _make_combo(
    match_label:  str,
    home: str, away: str, date: str, league: str, eid: str,
    leg1_label:   str, leg1_conf: float, leg1_odds: float,
    leg2_label:   str, leg2_conf: float, leg2_odds: float,
    leg2_bm:      str,
    xg:           float,
    p_1x2:        dict | None,
    corr_bonus:   float = 1.05,
) -> "TipsterPick | None":
    if leg1_conf < MIN_COMBO_LEG or leg2_conf < MIN_COMBO_LEG:
        return None
    if leg1_odds <= 1.0 or leg2_odds <= 1.0:
        return None

    combo_conf = min(0.90, leg1_conf * leg2_conf * corr_bonus)
    if combo_conf < MIN_CONF:
        return None

    combo_odds = round(leg1_odds * leg2_odds, 2)
    if combo_odds < MIN_COMBO_ODDS:
        return None

    draw = (p_1x2 or {}).get("draw", 0.25)
    signals = [
        f"{leg1_label}: {leg1_conf:.0%} @{leg1_odds}",
        f"{leg2_label}: {leg2_conf:.0%} @{leg2_odds}",
        f"xG {xg:.1f}",
    ]
    if draw < 0.17 and leg1_label in ("1", "2"):
        signals.append(f"Draw only {draw:.0%}")

    return TipsterPick(
        match=match_label, home_team=home, away_team=away,
        date=date, league=league, event_id=eid,
        market=f"{leg1_label} + {leg2_label}",
        confidence=combo_conf, pinnacle_prob=leg1_conf,
        inferred_xg=xg, best_odds=combo_odds,
        best_bookmaker=leg2_bm, signals=signals, is_combo=True,
    )


# ── Public API ────────────────────────────────────────────────────────────────

def score_event(
    event:       dict,
    p_1x2:       dict | None,
    p_ou:        dict | None,
    league:      str,
    p_ht:        dict | None = None,
    p_ht15:      dict | None = None,
    steam_moves: list        = None,
) -> list["TipsterPick"]:
    """Score one event. Returns qualifying TipsterPick objects (singles + combos)."""
    from utils.steam import steam_markets as _steam_mkts
    from config import STEAM_CONFIDENCE_BOOST
    _steam_set = _steam_mkts(steam_moves)
    picks = []
    home  = event.get("home_team", "")
    away  = event.get("away_team", "")
    dt    = event.get("commence", "")[:10]
    eid   = event.get("id", "")
    label = f"{home} vs {away}"

    over_25_prob = p_ou.get("over_prob") if p_ou else None
    xg = _infer_xg(over_25_prob)

    checks = []

    # Over/Under 2.5 from Pinnacle no-vig
    if p_ou:
        pt_str   = str(p_ou.get("point", 2.5)).replace(".", "_")
        over_25  = p_ou.get("over_prob", 0)
        under_25 = p_ou.get("under_prob", 0)
        if over_25 >= _MARKET_FLOOR["Over 2.5"]:
            checks.append(("Over 2.5",  over_25,  "totals", "over",  pt_str))
        if under_25 >= _MARKET_FLOOR["Under 2.5"]:
            checks.append(("Under 2.5", under_25, "totals", "under", pt_str))

    # Over/Under 1.5 from Poisson(xG)
    if xg > 0:
        o15_prob = poisson_over_prob(xg, 1.5)
        u15_prob = 1.0 - o15_prob
        if o15_prob >= _MARKET_FLOOR["Over 1.5"]:
            checks.append(("Over 1.5",  o15_prob, "totals", "over",  "1_5"))
        if u15_prob >= _MARKET_FLOOR["Under 1.5"]:
            checks.append(("Under 1.5", u15_prob, "totals", "under", "1_5"))

    # 1X2 from Pinnacle no-vig
    if p_1x2:
        home_p = p_1x2.get("home", 0)
        away_p = p_1x2.get("away", 0)
        draw_p = p_1x2.get("draw", 0)
        if home_p >= _MARKET_FLOOR["Home Win"]:
            checks.append(("Home Win", home_p, "h2h", "home", None))
        if away_p >= _MARKET_FLOOR["Away Win"]:
            checks.append(("Away Win", away_p, "h2h", "away", None))
        if draw_p >= _MARKET_FLOOR["Draw"]:
            checks.append(("Draw", draw_p, "h2h", "draw", None))

    # HT Over 0.5 from Pinnacle no-vig HT line
    if p_ht:
        ht_05 = p_ht.get("over_prob", 0)
        if ht_05 >= _MARKET_FLOOR["HT Over 0.5"]:
            pt_ht = str(p_ht.get("point", 0.5)).replace(".", "_")
            checks.append(("HT Over 0.5", ht_05, "totals_h1", "over", pt_ht))

    # HT Over 1.5 from Pinnacle no-vig HT line
    if p_ht15:
        ht_15 = p_ht15.get("over_prob", 0)
        if ht_15 >= _MARKET_FLOOR["HT Over 1.5"]:
            pt_ht15 = str(p_ht15.get("point", 1.5)).replace(".", "_")
            checks.append(("HT Over 1.5", ht_15, "totals_h1", "over", pt_ht15))

    # ── Score each check, populate combo pools ────────────────────────────────
    win_pool:   dict = {}   # {"Home Win": {conf, odds, label="1"}, ...}
    over_pool:  dict = {}   # {"Over 2.5": {conf, odds, bm}, ...}
    under_pool: dict = {}
    ht_pool:    dict = {}   # {"HT Over 0.5": {conf, odds, bm}, ...}
    draw_pool:  dict = {}

    for market, prob, mkt_key, side, pt in checks:
        conf, signals = _score(market, prob, xg, p_1x2)
        best_odds, best_bm = _best_odds_for(event, mkt_key, side, pt)
        if best_odds <= 1.0:
            continue

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
        elif market in ("HT Over 0.5", "HT Over 1.5"):
            ht_pool[market] = {"conf": conf, "odds": best_odds, "bm": best_bm}

        # Steam boost: sharp money on this market → higher confidence
        if market in _steam_set:
            steam_sig = next((s for s in (steam_moves or []) if s["market"] == market), None)
            if steam_sig:
                conf = min(0.95, conf + STEAM_CONFIDENCE_BOOST)
                signals.append(steam_sig["label"])

        if conf < MIN_CONF:
            continue

        if best_odds >= MIN_ODDS:
            picks.append(TipsterPick(
                match=label, home_team=home, away_team=away,
                date=dt, league=league, event_id=eid,
                market=market, confidence=conf, pinnacle_prob=prob,
                inferred_xg=xg, best_odds=best_odds, best_bookmaker=best_bm,
                signals=signals,
            ))

    # BTTS from soft-book odds (no Pinnacle line)
    btts_odds, btts_bm = _best_odds_for(event, "btts", "yes", None)
    btts_pool: dict = {}
    if btts_odds > 1.0:
        btts_conf = min(0.85, 1 / btts_odds * 1.08)
        btts_pool["BTTS Yes"] = {"conf": btts_conf, "odds": btts_odds, "bm": btts_bm}

    # ── Combos ────────────────────────────────────────────────────────────────
    combo_args = dict(
        match_label=label, home=home, away=away, date=dt,
        league=league, eid=eid, xg=xg, p_1x2=p_1x2,
    )

    # 1 + Over 2.5 / 2 + Over 2.5 / 1 + Over 1.5 etc.
    for win_mkt, wd in win_pool.items():
        for over_mkt, od in over_pool.items():
            combo = _make_combo(
                **combo_args,
                leg1_label=wd["label"], leg1_conf=wd["conf"], leg1_odds=wd["odds"],
                leg2_label=over_mkt, leg2_conf=od["conf"], leg2_odds=od["odds"],
                leg2_bm=od["bm"], corr_bonus=1.08,
            )
            if combo:
                picks.append(combo)

    # 1 + HT Over 0.5 / 2 + HT Over 0.5 / 1 + HT Over 1.5
    for win_mkt, wd in win_pool.items():
        for ht_mkt, hd in ht_pool.items():
            combo = _make_combo(
                **combo_args,
                leg1_label=wd["label"], leg1_conf=wd["conf"], leg1_odds=wd["odds"],
                leg2_label=ht_mkt, leg2_conf=hd["conf"], leg2_odds=hd["odds"],
                leg2_bm=hd["bm"], corr_bonus=1.06,
            )
            if combo:
                picks.append(combo)

    # Over 2.5 + HT Over 0.5
    if "Over 2.5" in over_pool and "HT Over 0.5" in ht_pool:
        od = over_pool["Over 2.5"]
        hd = ht_pool["HT Over 0.5"]
        combo = _make_combo(
            **combo_args,
            leg1_label="Over 2.5", leg1_conf=od["conf"], leg1_odds=od["odds"],
            leg2_label="HT Over 0.5", leg2_conf=hd["conf"], leg2_odds=hd["odds"],
            leg2_bm=hd["bm"], corr_bonus=1.10,
        )
        if combo:
            picks.append(combo)

    # Over 2.5 + BTTS Yes
    if "Over 2.5" in over_pool and btts_pool:
        od = over_pool["Over 2.5"]
        bd = btts_pool["BTTS Yes"]
        combo = _make_combo(
            **combo_args,
            leg1_label="Over 2.5", leg1_conf=od["conf"], leg1_odds=od["odds"],
            leg2_label="BTTS Yes", leg2_conf=bd["conf"], leg2_odds=bd["odds"],
            leg2_bm=bd["bm"], corr_bonus=1.10,
        )
        if combo:
            picks.append(combo)

    # Over 1.5 + BTTS Yes
    if "Over 1.5" in over_pool and btts_pool:
        od = over_pool["Over 1.5"]
        bd = btts_pool["BTTS Yes"]
        combo = _make_combo(
            **combo_args,
            leg1_label="Over 1.5", leg1_conf=od["conf"], leg1_odds=od["odds"],
            leg2_label="BTTS Yes", leg2_conf=bd["conf"], leg2_odds=bd["odds"],
            leg2_bm=bd["bm"], corr_bonus=1.10,
        )
        if combo:
            picks.append(combo)

    # 1 + Under / 2 + Under (dominant clean win)
    for win_mkt, wd in win_pool.items():
        for under_mkt, ud in under_pool.items():
            combo = _make_combo(
                **combo_args,
                leg1_label=wd["label"], leg1_conf=wd["conf"], leg1_odds=wd["odds"],
                leg2_label=under_mkt, leg2_conf=ud["conf"], leg2_odds=ud["odds"],
                leg2_bm=ud["bm"], corr_bonus=1.05,
            )
            if combo:
                picks.append(combo)

    # X + Under (defensive stalemate)
    if draw_pool and under_pool:
        dd = draw_pool["Draw"]
        for under_mkt, ud in under_pool.items():
            combo = _make_combo(
                **combo_args,
                leg1_label="X", leg1_conf=dd["conf"], leg1_odds=dd["odds"],
                leg2_label=under_mkt, leg2_conf=ud["conf"], leg2_odds=ud["odds"],
                leg2_bm=ud["bm"], corr_bonus=1.08,
            )
            if combo:
                picks.append(combo)

    return picks


def generate_picks(
    events_data:  list[dict],
    stake_method: str   = "kelly",
    bankroll:     float = 1000.0,
    base_stake:   float = 10.0,
    fixed_pct:    float = 2.0,
) -> list[TipsterPick]:
    """Process all events, return top MAX_PICKS tips. Max 1 single + 1 combo per match."""
    from models.value_calculator import calculate_stake

    all_picks = []
    for item in events_data:
        picks = score_event(
            event       = item["event"],
            p_1x2       = item.get("p_1x2"),
            p_ou        = item.get("p_ou"),
            league      = item.get("league", ""),
            p_ht        = item.get("p_ht"),
            p_ht15      = item.get("p_ht15"),
            steam_moves = item.get("steam_moves", []),
        )
        all_picks.extend(picks)

    all_picks.sort(key=lambda p: -p.confidence)

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

    deduped.sort(key=lambda p: -p.confidence)
    result = deduped[:MAX_PICKS]

    for p in result:
        p.stake = calculate_stake(
            p.pinnacle_prob, p.best_odds,
            method=stake_method, bankroll=bankroll,
            base_stake=base_stake, fixed_pct=fixed_pct,
            confidence=p.confidence,
        )

    return result
