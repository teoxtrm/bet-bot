"""
Live Scanner — polling loop για in-play αγώνες.
Ανανεώνει scores + odds κάθε N δευτερόλεπτα και υπολογίζει live value.
"""

import os
import time
import requests
from datetime import datetime, timezone
from dotenv import load_dotenv

load_dotenv()

BASE_URL = "https://api.the-odds-api.com/v4"
API_KEY  = os.getenv("ODDS_API_KEY", "")


def _get(path: str, params: dict) -> list | None:
    params["apiKey"] = API_KEY
    try:
        r = requests.get(f"{BASE_URL}{path}", params=params, timeout=15)
        remaining = r.headers.get("x-requests-remaining", "?")
        if r.status_code == 200:
            print(f"[LiveScanner] {r.status_code} {path.split('?')[0]} | remaining={remaining}")
            return r.json()
        print(f"[LiveScanner] Error {r.status_code}: {r.text[:100]}")
    except requests.RequestException as e:
        print(f"[LiveScanner] Network error: {e}")
    return None


def get_live_scores(sport_key: str) -> list:
    """
    Επιστρέφει αγώνες που είναι in-play τώρα.
    In-play = commenced + not completed + scores not null.
    """
    now  = datetime.now(timezone.utc)
    data = _get(f"/sports/{sport_key}/scores/", {"daysFrom": 1, "dateFormat": "iso"})
    if not data:
        return []

    live = []
    for e in data:
        if e.get("completed"):
            continue
        try:
            start = datetime.fromisoformat(e["commence_time"].replace("Z", "+00:00"))
        except Exception:
            continue
        if start > now:
            continue  # δεν έχει ξεκινήσει ακόμα

        scores = e.get("scores") or []
        try:
            score_map = {s["name"]: int(s["score"]) for s in scores} if scores else {}
        except (ValueError, TypeError, KeyError):
            score_map = {}

        live.append({
            "id":         e["id"],
            "home_team":  e["home_team"],
            "away_team":  e["away_team"],
            "home_score": score_map.get(e["home_team"], 0),
            "away_score": score_map.get(e["away_team"], 0),
            "total_goals": sum(score_map.values()),
            "commence":   e["commence_time"],
            "last_update": e.get("last_update", ""),
        })
    return live


def get_live_odds_for_event(sport_key: str, event_id: str) -> dict | None:
    """
    Τραβάει τις τρέχουσες αποδόσεις για ένα συγκεκριμένο in-play event.
    """
    data = _get(
        f"/sports/{sport_key}/odds/",
        {"regions": "eu,uk", "markets": "h2h,totals,totals_h1", "oddsFormat": "decimal", "dateFormat": "iso"},
    )
    if not data:
        return None
    for e in data:
        if e.get("id") == event_id:
            return e
    return None


def estimate_minute(commence_time: str) -> int:
    """Εκτιμά το τρέχον λεπτό από την ώρα έναρξης."""
    try:
        start = datetime.fromisoformat(commence_time.replace("Z", "+00:00"))
        now   = datetime.now(timezone.utc)
        elapsed = int((now - start).total_seconds() / 60)
        # Υπολογισμός για 90 λεπτά + ~15 λεπτά ημίχρονο
        if elapsed > 45:
            elapsed = max(elapsed - 15, 45)  # αφαίρεσε ημίχρονο break
        return min(elapsed, 90)
    except Exception:
        return 45


def scan_once(sport_key: str, our_model_probs: dict = None,
              pregame_baseline: dict = None) -> list:
    """
    Μία σάρωση: βρίσκει live αγώνες, αποδόσεις, υπολογίζει value.

    Args:
        sport_key: π.χ. "soccer_greece_super_league"
        our_model_probs: {"match_id": {"over_2_5": 0.55, ...}} — προαιρετικό
        pregame_baseline: {event_id: {pin_*_prob fields}} from pre-game scan — for steam detection

    Returns:
        Λίστα live αγώνων με enriched δεδομένα
    """
    from scrapers.odds_api import (get_pinnacle_no_vig_totals, get_pinnacle_no_vig_probs,
                                    get_pinnacle_no_vig_ht_totals, _parse_event)
    from models.live_model import live_over_probability, live_ht_probability
    from models.value_calculator import compare_bookmakers
    from utils.steam import detect_steam

    live_scores  = get_live_scores(sport_key)
    if not live_scores:
        return []

    # Τράβα odds για όλο το sport (1 request αντί για N)
    raw_odds = _get(
        f"/sports/{sport_key}/odds/",
        {"regions": "eu,uk", "markets": "h2h,totals,totals_h1", "oddsFormat": "decimal", "dateFormat": "iso"},
    )
    odds_by_id = {}
    if raw_odds:
        for e in raw_odds:
            odds_by_id[e["id"]] = _parse_event(e)

    enriched = []
    for match in live_scores:
        minute  = estimate_minute(match["commence"])
        ev_odds = odds_by_id.get(match["id"])

        entry = {**match, "minute": minute, "value_bets": [], "steam_moves": []}

        p_ou_val  = None
        p_ht05_val = None
        p_ht15_val = None

        if ev_odds:
            # Pinnacle no-vig Over 2.5
            p_ou = get_pinnacle_no_vig_totals(ev_odds, 2.5)
            if p_ou:
                p_ou_val = p_ou["over_prob"]
                live_result = live_over_probability(
                    p_ou_val, match["total_goals"], minute, target_goals=2.5
                )
                live_prob = live_result["live_over_prob"]

                bm_odds = {}
                for bm_key, bm_data in ev_odds.get("odds", {}).items():
                    o = bm_data.get("totals", {}).get("over_2_5")
                    if o:
                        bm_odds[bm_key] = o

                if bm_odds:
                    comps = compare_bookmakers(live_prob, bm_odds)
                    value_hits = [c for c in comps if c["is_value_bet"]]
                    entry["pinnacle_over_prob"] = p_ou_val
                    entry["live_over_prob"]     = live_prob
                    entry["value_bets"]         = value_hits

        # HT markets — scan both O0.5 and O1.5 for the full 1st half
        entry["ht_05_prob"] = None
        entry["ht_05_bets"] = []
        entry["ht_15_prob"] = None
        entry["ht_15_bets"] = []
        if ev_odds and minute <= 45:
            ht_goals = match["total_goals"]
            for ht_target, prob_key, bets_key, pval_attr in [
                (0.5, "ht_05_prob", "ht_05_bets", "p_ht05_val"),
                (1.5, "ht_15_prob", "ht_15_bets", "p_ht15_val"),
            ]:
                p_ht = get_pinnacle_no_vig_ht_totals(ev_odds, ht_target)
                if not p_ht or abs(p_ht["point"] - ht_target) > 0.3:
                    continue
                if ht_target == 0.5:
                    p_ht05_val = p_ht["over_prob"]
                else:
                    p_ht15_val = p_ht["over_prob"]
                ht_result = live_ht_probability(p_ht["over_prob"], ht_goals, minute, ht_target)
                if ht_result.get("settled"):
                    continue
                live_ht_prob = ht_result["live_ht_prob"]
                entry[prob_key] = live_ht_prob
                pt_str = str(p_ht["point"]).replace(".", "_")
                bm_ht = {
                    bm: bd.get("totals_h1", {}).get(f"over_{pt_str}")
                    for bm, bd in ev_odds.get("odds", {}).items()
                    if bm != "pinnacle" and bd.get("totals_h1", {}).get(f"over_{pt_str}")
                }
                if bm_ht:
                    ht_comps = compare_bookmakers(live_ht_prob, bm_ht)
                    entry[bets_key] = [c for c in ht_comps if c["is_value_bet"]]

        # Steam detection: compare live Pinnacle probs vs pre-game baseline
        if pregame_baseline:
            prev = pregame_baseline.get(match["id"])
            if prev:
                entry["steam_moves"] = detect_steam(prev, {
                    "over25": p_ou_val,
                    "ht05":   p_ht05_val,
                    "ht15":   p_ht15_val,
                })

        # Fetch live stats from API-Football when any value bet is found
        entry["live_stats"] = None
        has_value = bool(entry["value_bets"] or entry["ht_05_bets"] or entry["ht_15_bets"])
        if has_value:
            try:
                from scrapers.apifootball import get_live_stats
                entry["live_stats"] = get_live_stats(match["home_team"], match["away_team"])
            except Exception:
                pass  # stats are supplementary — never block the main result

        enriched.append(entry)

    return enriched


def _fuzzy_event_match(parsed_event: dict, home: str, away: str) -> bool:
    """Check if a parsed Odds API event matches the given team names."""
    ph = parsed_event.get("home_team", "").lower()
    pa = parsed_event.get("away_team", "").lower()
    h, a = home.lower(), away.lower()
    home_match = h in ph or ph in h or any(w in ph for w in h.split() if len(w) > 3)
    away_match = a in pa or pa in a or any(w in pa for w in a.split() if len(w) > 3)
    return home_match and away_match


def scan_all_live(max_tier: int = 2, max_matches: int = 6,
                  sport_keys_filter: set[str] | None = None,
                  pregame_baseline: dict = None) -> list:
    """
    Scans quality leagues for live matches.

    sport_keys_filter: if provided (Watchlist Only mode), only fetch odds for
    those specific Odds API sport_keys — ignores max_tier league filter.
    pregame_baseline: {event_id: {pin_*_prob fields}} for steam detection.

    Step 1 — Discover  (1 API-Football request):
        /fixtures?live=all → filter by league quality + minute + score
    Step 2 — Odds       (1 Odds API credit per unique league found):
        fetch odds once per league, fuzzy-match to discovered fixtures
    Step 3 — Analyse    (0 extra requests):
        same Over 2.5 + HT 0.5 + HT 1.5 value logic as scan_once()

    Typical cost for 5 matches in 3 leagues: ~11 API-Football + 3 Odds API credits.
    """
    from collections import defaultdict
    from scrapers.apifootball import discover_live_matches, get_live_stats
    from scrapers.odds_api import (_parse_event, get_pinnacle_no_vig_totals,
                                    get_pinnacle_no_vig_ht_totals)
    from models.live_model import live_over_probability, live_ht_probability
    from models.value_calculator import compare_bookmakers
    from utils.steam import detect_steam

    # ── Step 1: Discover live candidates ─────────────────────────────────────
    candidates = discover_live_matches(max_tier=max_tier, max_matches=max_matches)
    if not candidates:
        return []

    # ── Step 3: Fetch Odds API once per unique league ─────────────────────────
    by_odds_key: dict[str, list] = defaultdict(list)
    for c in candidates:
        # In watchlist-only mode skip leagues not in the filter
        if sport_keys_filter and c["odds_key"] not in sport_keys_filter:
            continue
        by_odds_key[c["odds_key"]].append(c)

    odds_by_fixture: dict[int, dict] = {}  # fixture_id → parsed Odds API event

    for odds_key, matches in by_odds_key.items():
        raw = _get(
            f"/sports/{odds_key}/odds/",
            {
                "regions":    "eu,uk",
                "markets":    "h2h,totals,totals_h1",
                "oddsFormat": "decimal",
                "dateFormat": "iso",
            },
        )
        if not raw:
            continue
        for event_raw in raw:
            parsed = _parse_event(event_raw)
            for m in matches:
                if m["fixture_id"] in odds_by_fixture:
                    continue
                if _fuzzy_event_match(parsed, m["home_team"], m["away_team"]):
                    odds_by_fixture[m["fixture_id"]] = parsed
                    m["odds_event_id"] = parsed.get("id", "")
                    break

    # ── Step 4: Value analysis for each match ─────────────────────────────────
    enriched = []
    for m in candidates:
        ev_odds     = odds_by_fixture.get(m["fixture_id"])
        minute      = m["minute"]
        total_goals = m["home_score"] + m["away_score"]

        pin_over25_live = None
        pin_ht05_live   = None
        pin_ht15_live   = None

        entry: dict = {
            "id":          m.get("odds_event_id", str(m["fixture_id"])),
            "home_team":   m["home_team"],
            "away_team":   m["away_team"],
            "home_score":  m["home_score"],
            "away_score":  m["away_score"],
            "total_goals": total_goals,
            "minute":      minute,
            "league":      m["league_name"],
            "commence":    "",
            "last_update": "",
            # value outputs
            "value_bets":      [],
            "ht_05_prob":      None,
            "ht_05_bets":      [],
            "ht_15_prob":      None,
            "ht_15_bets":      [],
            "live_over_prob":  None,
            "live_stats":      None,
            "steam_moves":     [],
        }

        if ev_odds:
            # Over 2.5
            p_ou = get_pinnacle_no_vig_totals(ev_odds, 2.5)
            if p_ou:
                pin_over25_live = p_ou["over_prob"]
                live_result  = live_over_probability(pin_over25_live, total_goals, minute, 2.5)
                live_prob    = live_result["live_over_prob"]

                bm_odds = {
                    bm: bd.get("totals", {}).get("over_2_5")
                    for bm, bd in ev_odds.get("odds", {}).items()
                    if bm != "pinnacle" and bd.get("totals", {}).get("over_2_5")
                }
                if bm_odds:
                    comps = compare_bookmakers(live_prob, bm_odds)
                    entry["value_bets"]         = [c for c in comps if c["is_value_bet"]]
                    entry["pinnacle_over_prob"]  = pin_over25_live
                    entry["live_over_prob"]      = live_prob

            # HT markets — first half only
            if minute <= 45:
                for ht_target, prob_key, bets_key in [
                    (0.5, "ht_05_prob", "ht_05_bets"),
                    (1.5, "ht_15_prob", "ht_15_bets"),
                ]:
                    p_ht = get_pinnacle_no_vig_ht_totals(ev_odds, ht_target)
                    if not p_ht or abs(p_ht["point"] - ht_target) > 0.3:
                        continue
                    if ht_target == 0.5:
                        pin_ht05_live = p_ht["over_prob"]
                    else:
                        pin_ht15_live = p_ht["over_prob"]
                    ht_result = live_ht_probability(p_ht["over_prob"], total_goals, minute, ht_target)
                    if ht_result.get("settled"):
                        continue
                    live_ht_prob = ht_result["live_ht_prob"]
                    entry[prob_key] = live_ht_prob

                    pt_str = str(p_ht["point"]).replace(".", "_")
                    bm_ht = {
                        bm: bd.get("totals_h1", {}).get(f"over_{pt_str}")
                        for bm, bd in ev_odds.get("odds", {}).items()
                        if bm != "pinnacle" and bd.get("totals_h1", {}).get(f"over_{pt_str}")
                    }
                    if bm_ht:
                        ht_comps = compare_bookmakers(live_ht_prob, bm_ht)
                        entry[bets_key] = [c for c in ht_comps if c["is_value_bet"]]

        # Steam detection: compare live Pinnacle probs vs pre-game baseline
        if pregame_baseline:
            prev = pregame_baseline.get(entry["id"])
            if prev:
                entry["steam_moves"] = detect_steam(prev, {
                    "over25": pin_over25_live,
                    "ht05":   pin_ht05_live,
                    "ht15":   pin_ht15_live,
                })

        # Live stats from API-Football — only when value found
        has_value = bool(entry["value_bets"] or entry["ht_05_bets"] or entry["ht_15_bets"])
        if has_value:
            try:
                entry["live_stats"] = get_live_stats(m["home_team"], m["away_team"])
            except Exception:
                pass

        enriched.append(entry)

    return enriched
