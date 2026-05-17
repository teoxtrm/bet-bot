"""
Live Targets Classifier
=======================
Εντοπίζει αγώνες που δεν έχουν value ΤΩΡα αλλά αξίζει να παρακολουθήσουμε live.
Μηδέν επιπλέον API requests — χρησιμοποιεί δεδομένα που ήδη φορτώθηκαν.

Λογική:
  Pre-game scan  →  αν δεν υπάρχει value τώρα αλλά πληρούνται conditions
                 →  προστίθεται στα Live Targets για το απόγευμα
"""

from dataclasses import dataclass, field

# ── Thresholds ────────────────────────────────────────────────────────────────
OVER_HIGH_PROB      = 0.60   # Pinnacle no-vig Over 2.5 > αυτό = πιθανός goalfest
OVER_VERY_HIGH_PROB = 0.68   # Πολύ υψηλή → highest priority
FAVE_WIN_PROB       = 0.70   # Αν φαβορί > 70% πιθανότητα νίκης
FAVE_MAX_ODDS       = 1.35   # ... αλλά απόδοση < 1.35 = no pre-game value
FAVE_HIGH_PROB      = 0.80   # Φαβορί > 80% → highest priority
BTTS_HIGH_PROB      = 0.65   # BTTS yes > 65% → Live Target
HT_GOAL_HIGH_PROB   = 0.75   # Over 0.5 HT > 75% → HT Goal Candidate
HT_GOAL_LOCK_PROB   = 0.85   # > 85% → highest priority


@dataclass
class LiveTarget:
    match:          str
    home_team:      str
    away_team:      str
    date:           str
    league:         str
    event_id:       str
    target_type:    str     # "OVER 2.5" / "FAVORITE WIN (Home)" / "BTTS" κ.ά.
    reason:         str     # σύντομη εξήγηση
    key_prob:       float   # κύρια πιθανότητα (Pinnacle no-vig)
    current_odds:   float   # καλύτερη τρέχουσα απόδοση
    action:         str     # οδηγία για το live play
    priority:       int     # 1=🔴 High, 2=🟡 Medium, 3=⚪ Low
    tags:           list[str] = field(default_factory=list)

    @property
    def priority_label(self) -> str:
        return {1: "🔴 HIGH", 2: "🟡 MED", 3: "⚪ LOW"}.get(self.priority, "⚪")


def classify(
    event:          dict,
    p_1x2:          dict | None,
    p_ou:           dict | None,
    best_over_odds: float | None = None,
    best_home_odds: float | None = None,
    best_away_odds: float | None = None,
    best_btts_odds: float | None = None,
    best_ht_odds:   float | None = None,
    p_ht_ou:        dict | None = None,
    has_value_bet:  bool = False,
) -> list[LiveTarget]:
    """
    Ελέγχει αν ένας αγώνας είναι Live Target και επιστρέφει λίστα targets.
    Καλείται μία φορά ανά event στον scan worker.

    Args:
        event:          raw event dict από odds_api
        p_1x2:          Pinnacle no-vig 1X2 probs (ή None αν δεν υπάρχει Pinnacle)
        p_ou:           Pinnacle no-vig Over/Under probs
        best_*_odds:    καλύτερη τρέχουσα απόδοση ανά αγορά
        has_value_bet:  αν ήδη βρέθηκε value bet → target γίνεται bonus hint
    """
    targets = []
    home  = event.get("home_team", "")
    away  = event.get("away_team", "")
    date  = event.get("commence", "")[:10]
    eid   = event.get("id", "")
    label = f"{home} vs {away}"
    sport = event.get("sport", "")

    # ─────────────────────────────────────────────────────────────────────────
    # TARGET 1 — OVER 2.5: υψηλή πιθανότητα γκολ, αλλά pre-game odds χωρίς value
    # ─────────────────────────────────────────────────────────────────────────
    if p_ou and p_ou.get("over_prob", 0) >= OVER_HIGH_PROB and not has_value_bet:
        prob = p_ou["over_prob"]
        prio = 1 if prob >= OVER_VERY_HIGH_PROB else 2
        targets.append(LiveTarget(
            match        = label,
            home_team    = home,
            away_team    = away,
            date         = date,
            league       = sport,
            event_id     = eid,
            target_type  = "OVER 2.5",
            reason       = f"Pinnacle: {prob:.1%} > {OVER_HIGH_PROB:.0%} | No pre-game value yet",
            key_prob     = prob,
            current_odds = best_over_odds or 0.0,
            action       = (
                "Φόρτωσε στο Live Monitor. "
                "Αν φτάσεις στο 15'-25' χωρίς γκολ, "
                "οι live odds ανεβαίνουν → ψάξε value window."
            ),
            priority     = prio,
            tags         = ["goals", "over"],
        ))

    # ─────────────────────────────────────────────────────────────────────────
    # TARGET 2 — FAVORITE WIN: φαβορί χωρίς pre-game value λόγω χαμηλής απόδοσης
    # ─────────────────────────────────────────────────────────────────────────
    if p_1x2:
        fave_checks = [
            ("Home", p_1x2.get("home", 0), best_home_odds),
            ("Away", p_1x2.get("away", 0), best_away_odds),
        ]
        for side, prob, odds in fave_checks:
            if prob >= FAVE_WIN_PROB and odds and odds < FAVE_MAX_ODDS:
                prio = 1 if prob >= FAVE_HIGH_PROB else 2
                targets.append(LiveTarget(
                    match        = label,
                    home_team    = home,
                    away_team    = away,
                    date         = date,
                    league       = sport,
                    event_id     = eid,
                    target_type  = f"FAVORITE WIN ({side})",
                    reason       = (
                        f"{side}: {prob:.1%} > {FAVE_WIN_PROB:.0%} | "
                        f"Pre-game odds {odds:.2f} < {FAVE_MAX_ODDS}"
                    ),
                    key_prob     = prob,
                    current_odds = odds,
                    action       = (
                        f"Αν στο 20' η κατάσταση είναι 0-0 ή 0-1 "
                        f"εναντίον του φαβορί ({side.lower()}), "
                        f"οι live odds θα ανέβουν πάνω από 1.50+ → value window."
                    ),
                    priority     = prio,
                    tags         = ["favorite", side.lower()],
                ))

    # ─────────────────────────────────────────────────────────────────────────
    # TARGET 3 — BTTS: υψηλή πιθανότητα και οι δύο να σκοράρουν
    # ─────────────────────────────────────────────────────────────────────────
    if p_1x2 and p_ou:
        # BTTS ≈ (1 - prob_home_shutout) * (1 - prob_away_shutout)
        # Προσέγγιση: αν και οι δύο ομάδες έχουν ισορροπημένη δύναμη
        home_prob = p_1x2.get("home", 0)
        away_prob = p_1x2.get("away", 0)
        balance   = 1 - abs(home_prob - away_prob)   # 1.0 = πλήρης ισορροπία

        # BTTS πιθανό αν ισορροπημένος αγώνας ΚΑΙ over_prob υψηλό
        btts_est  = p_ou.get("over_prob", 0) * balance * 0.95
        if btts_est >= BTTS_HIGH_PROB and not has_value_bet:
            targets.append(LiveTarget(
                match        = label,
                home_team    = home,
                away_team    = away,
                date         = date,
                league       = sport,
                event_id     = eid,
                target_type  = "BTTS YES",
                reason       = (
                    f"Est. BTTS prob ≈ {btts_est:.1%} | "
                    f"Balance: {balance:.0%} | Over: {p_ou['over_prob']:.1%}"
                ),
                key_prob     = btts_est,
                current_odds = best_btts_odds or 0.0,
                action       = (
                    "Αν στο 25' σκοράρει μία ομάδα (1-0 ή 0-1), "
                    "οι BTTS Yes live odds βελτιώνονται → ψάξε value."
                ),
                priority     = 2,
                tags         = ["btts", "balanced"],
            ))

    # ─────────────────────────────────────────────────────────────────────────
    # TARGET 4 — HT GOAL CANDIDATE: Pinnacle Over 0.5 HT > 75%
    # ─────────────────────────────────────────────────────────────────────────
    if p_ht_ou and p_ht_ou.get("over_prob", 0) >= HT_GOAL_HIGH_PROB and not has_value_bet:
        prob = p_ht_ou["over_prob"]
        prio = 1 if prob >= HT_GOAL_LOCK_PROB else 2
        targets.append(LiveTarget(
            match        = label,
            home_team    = home,
            away_team    = away,
            date         = date,
            league       = sport,
            event_id     = eid,
            target_type  = "HT GOAL CANDIDATE",
            reason       = (
                f"Pinnacle HT O0.5: {prob:.1%} > {HT_GOAL_HIGH_PROB:.0%} | "
                f"Ανοιχτό παράθυρο 5'-25'"
            ),
            key_prob     = prob,
            current_odds = best_ht_odds or 0.0,
            action       = (
                "Άνοιξε στο 5'-15' αν 0-0. "
                "Live O0.5 HT ανεβαίνει γρήγορα → value window πριν το 25'."
            ),
            priority     = prio,
            tags         = ["ht", "goals", "first-half"],
        ))

    return targets


def score_targets(targets: list[LiveTarget]) -> list[LiveTarget]:
    """Ταξινομεί targets: πρώτα priority=1, μετά κατά key_prob."""
    return sorted(targets, key=lambda t: (t.priority, -t.key_prob))
