"""
The Odds API scraper — https://the-odds-api.com
Free tier: 500 requests/month

Διαθέσιμα για EU/Greek Super League:
  Pinnacle, Betsson, 888sport, William Hill, 1xBet, Betclic, κ.ά.

Στρατηγική value betting:
  Pinnacle = sharp reference line (χαμηλότατο margin ~2%)
  → Αφαίρεσε margin από Pinnacle → πραγματική πιθανότητα
  → Σύγκρινε με τα soft books για edge
"""

import os
import requests
from dotenv import load_dotenv

load_dotenv()

BASE_URL = "https://api.the-odds-api.com/v4"
API_KEY  = os.getenv("ODDS_API_KEY", "")

SPORT_KEYS = {
    "premier_league":    "soccer_epl",
    "champions_league":  "soccer_uefa_champs_league",
    "la_liga":           "soccer_spain_la_liga",
    "bundesliga":        "soccer_germany_bundesliga",
    "serie_a":           "soccer_italy_serie_a",
    "ligue_1":           "soccer_france_ligue_one",
    "eredivisie":        "soccer_netherlands_eredivisie",
    "primeira_liga":     "soccer_portugal_primeira_liga",
    "championship":      "soccer_efl_champ",
    "super_league":      "soccer_greece_super_league",   # odds μόνο
    "europa_league":     "soccer_uefa_europa_league",
    "conference":        "soccer_uefa_europa_conference_league",
}

# Bookmakers που επιστρέφει το API (EU region, free tier)
SHARP_BOOKS  = ["pinnacle"]
SOFT_BOOKS   = ["betsson", "sport888", "williamhill", "onexbet", "betclic_fr", "unibet_se"]
ALL_BOOKS    = SHARP_BOOKS + SOFT_BOOKS


def _get(path: str, params: dict) -> list | dict | None:
    if not API_KEY:
        print("[OddsAPI] Δεν βρέθηκε ODDS_API_KEY στο .env")
        return None
    params["apiKey"] = API_KEY
    try:
        r = requests.get(f"{BASE_URL}{path}", params=params, timeout=15)
        remaining = r.headers.get("x-requests-remaining", "?")
        used      = r.headers.get("x-requests-used", "?")
        print(f"[OddsAPI] {r.status_code} | χρησιμοποιήθηκαν={used} | απομένουν={remaining}/500")
        if r.status_code == 200:
            return r.json()
        elif r.status_code == 401:
            print("[OddsAPI] Λάθος API key.")
        elif r.status_code == 422:
            print(f"[OddsAPI] Μη υποστηριζόμενη παράμετρος: {r.json().get('message','')}")
        else:
            print(f"[OddsAPI] Error {r.status_code}: {r.text[:200]}")
    except requests.RequestException as e:
        print(f"[OddsAPI] Network error: {e}")
    return None


def get_available_sports() -> list:
    data = _get("/sports/", {"all": "false"})
    if not data:
        return []
    return [s for s in data if s.get("group") == "Soccer"]


def get_odds(sport_key: str, markets: list = None, bookmakers: list = None) -> list:
    """
    Τραβάει αποδόσεις για ένα sport.

    Args:
        sport_key: π.χ. "soccer_greece_super_league"
        markets: ["h2h", "totals"] — btts δεν υποστηρίζεται παντού
        bookmakers: None = όλα τα διαθέσιμα

    Returns:
        Λίστα parsed events
    """
    if markets is None:
        markets = ["h2h", "totals"]

    params = {
        "regions":    "eu",
        "markets":    ",".join(markets),
        "oddsFormat": "decimal",
        "dateFormat": "iso",
    }
    if bookmakers:
        params["bookmakers"] = ",".join(bookmakers)

    raw = _get(f"/sports/{sport_key}/odds/", params)
    if not raw:
        return []
    return [_parse_event(e) for e in raw]


def _parse_event(event: dict) -> dict:
    """Μετατρέπει raw API event σε καθαρό dict."""
    result = {
        "id":        event.get("id"),
        "sport":     event.get("sport_key"),
        "home_team": event.get("home_team"),
        "away_team": event.get("away_team"),
        "commence":  event.get("commence_time", ""),
        "odds":      {},
    }

    home = event.get("home_team", "")
    away = event.get("away_team", "")

    for bm in event.get("bookmakers", []):
        bm_key = bm.get("key")
        result["odds"][bm_key] = {"title": bm.get("title", bm_key)}

        for market in bm.get("markets", []):
            mkey = market.get("key")
            outcomes = market.get("outcomes", [])

            if mkey == "h2h":
                price_map = {o["name"]: o["price"] for o in outcomes}
                result["odds"][bm_key]["1x2"] = {
                    "home": price_map.get(home),
                    "draw": price_map.get("Draw"),
                    "away": price_map.get(away),
                }

            elif mkey == "totals":
                # Ομαδοποίηση ανά point (2.0, 2.25, 2.5, κ.λπ.)
                totals = {}
                for o in outcomes:
                    pt  = o.get("point", "")
                    key = f"over_{str(pt).replace('.','_')}" if o["name"] == "Over" \
                          else f"under_{str(pt).replace('.','_')}"
                    totals[key] = o["price"]
                result["odds"][bm_key]["totals"] = totals

            elif mkey == "btts":
                price_map = {o["name"]: o["price"] for o in outcomes}
                result["odds"][bm_key]["btts"] = {
                    "yes": price_map.get("Yes"),
                    "no":  price_map.get("No"),
                }

            elif mkey == "totals_h1":
                ht_totals = {}
                for o in outcomes:
                    pt  = o.get("point", "")
                    key = f"over_{str(pt).replace('.','_')}" if o["name"] == "Over" \
                          else f"under_{str(pt).replace('.','_')}"
                    ht_totals[key] = o["price"]
                result["odds"][bm_key]["totals_h1"] = ht_totals

    return result


def get_live_odds(sport_key: str) -> list:
    """
    Live αγώνες = events με commence_time στο παρελθόν.
    """
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)

    events = get_odds(sport_key)
    live = []
    for e in events:
        try:
            start = datetime.fromisoformat(e["commence"].replace("Z", "+00:00"))
            if start <= now:
                live.append(e)
        except Exception:
            continue
    return live


def get_scores(sport_key: str, days_from: int = 1) -> list:
    """Τελευταία αποτελέσματα."""
    params = {"daysFrom": days_from, "dateFormat": "iso"}
    raw = _get(f"/sports/{sport_key}/scores/", params)
    if not raw:
        return []
    results = []
    for e in raw:
        sc = {s["name"]: s["score"] for s in (e.get("scores") or [])}
        results.append({
            "home_team":  e.get("home_team"),
            "away_team":  e.get("away_team"),
            "home_score": sc.get(e.get("home_team"), "-"),
            "away_score": sc.get(e.get("away_team"), "-"),
            "completed":  e.get("completed", False),
        })
    return results


def get_pinnacle_no_vig_probs(event: dict) -> dict | None:
    """
    Αφαιρεί το margin (vig) από τις Pinnacle αποδόσεις
    για να πάρουμε την 'αληθινή' πιθανότητα.

    Αυτή η πιθανότητα χρησιμοποιείται ως input στο value calculator
    αντί για το δικό μας model — είναι πιο ακριβής για αγώνες
    που δεν έχουμε βαθιά ιστορικά δεδομένα.
    """
    pin = event.get("odds", {}).get("pinnacle", {})
    x2  = pin.get("1x2", {})

    if not all([x2.get("home"), x2.get("draw"), x2.get("away")]):
        return None

    # Implied probs (με margin)
    ip_h = 1 / x2["home"]
    ip_d = 1 / x2["draw"]
    ip_a = 1 / x2["away"]
    total = ip_h + ip_d + ip_a  # π.χ. 1.04 = 4% margin

    # No-vig (normalize)
    return {
        "home": round(ip_h / total, 4),
        "draw": round(ip_d / total, 4),
        "away": round(ip_a / total, 4),
        "pinnacle_margin_pct": round((total - 1) * 100, 2),
    }


def get_pinnacle_no_vig_totals(event: dict, point: float = 2.5) -> dict | None:
    """
    No-vig πιθανότητες Over/Under από Pinnacle για συγκεκριμένο point.
    """
    pin    = event.get("odds", {}).get("pinnacle", {})
    totals = pin.get("totals", {})

    pt_str = str(point).replace(".", "_")
    over_key  = f"over_{pt_str}"
    under_key = f"under_{pt_str}"

    over_odds  = totals.get(over_key)
    under_odds = totals.get(under_key)

    if not over_odds or not under_odds:
        # Βρες τον πιο κοντινό point
        available = [float(k.replace("over_","").replace("_","."))
                     for k in totals if k.startswith("over_")]
        if not available:
            return None
        closest = min(available, key=lambda x: abs(x - point))
        pt_str    = str(closest).replace(".", "_")
        over_odds  = totals.get(f"over_{pt_str}")
        under_odds = totals.get(f"under_{pt_str}")
        point = closest

    if not over_odds or not under_odds:
        return None

    ip_o = 1 / over_odds
    ip_u = 1 / under_odds
    total = ip_o + ip_u

    return {
        "point":       point,
        "over_prob":   round(ip_o / total, 4),
        "under_prob":  round(ip_u / total, 4),
        "over_odds_pinnacle":  over_odds,
        "under_odds_pinnacle": under_odds,
        "pinnacle_margin_pct": round((total - 1) * 100, 2),
    }


def get_pinnacle_no_vig_ht_totals(event: dict, point: float = 0.5) -> dict | None:
    """
    No-vig πιθανότητες 1ου Ημιχρόνου Over/Under από Pinnacle.
    Ίδια λογική με get_pinnacle_no_vig_totals αλλά διαβάζει totals_h1.
    """
    pin    = event.get("odds", {}).get("pinnacle", {})
    totals = pin.get("totals_h1", {})

    pt_str    = str(point).replace(".", "_")
    over_odds  = totals.get(f"over_{pt_str}")
    under_odds = totals.get(f"under_{pt_str}")

    if not over_odds or not under_odds:
        available = [float(k.replace("over_", "").replace("_", "."))
                     for k in totals if k.startswith("over_")]
        if not available:
            return None
        closest    = min(available, key=lambda x: abs(x - point))
        pt_str     = str(closest).replace(".", "_")
        over_odds  = totals.get(f"over_{pt_str}")
        under_odds = totals.get(f"under_{pt_str}")
        point      = closest

    if not over_odds or not under_odds:
        return None

    ip_o  = 1 / over_odds
    ip_u  = 1 / under_odds
    total = ip_o + ip_u

    return {
        "point":               point,
        "over_prob":           round(ip_o / total, 4),
        "under_prob":          round(ip_u / total, 4),
        "over_odds_pinnacle":  over_odds,
        "under_odds_pinnacle": under_odds,
        "pinnacle_margin_pct": round((total - 1) * 100, 2),
    }


def find_match_odds(events: list, home: str, away: str) -> dict | None:
    """Fuzzy match αγώνα από λίστα events."""
    home_l, away_l = home.lower(), away.lower()
    for e in events:
        eh = e["home_team"].lower()
        ea = e["away_team"].lower()
        if home_l in eh or eh in home_l:
            if away_l in ea or ea in away_l:
                return e
    return None
