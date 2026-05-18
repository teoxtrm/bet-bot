"""
Football-data.org scraper — αντικαθιστά το Sofascore για match stats.
Free tier: 100 req/day, χωρίς credit card.
Εγγραφή: https://www.football-data.org/client/register
"""

import os
import json
import pathlib
import requests
from datetime import date
from dotenv import load_dotenv

load_dotenv()

BASE_URL = "https://api.football-data.org/v4"
API_KEY  = os.getenv("FOOTBALL_DATA_KEY", "")
DAILY_LIMIT = 100

# Local counter — persisted to data/api_credits.json, reset each new day
_CREDITS_FILE = pathlib.Path("data/api_credits.json")
_requests_used: int = 0
_counter_date: str  = date.today().isoformat()


def _load_fd_counter():
    global _requests_used, _counter_date
    try:
        saved = json.loads(_CREDITS_FILE.read_text(encoding="utf-8"))
        fd = saved.get("football_data", {})
        if fd.get("date") == date.today().isoformat():
            _requests_used = int(fd.get("used", 0))
            _counter_date  = fd["date"]
    except Exception:
        pass


def _persist_fd_counter():
    try:
        _CREDITS_FILE.parent.mkdir(exist_ok=True)
        existing = {}
        if _CREDITS_FILE.exists():
            existing = json.loads(_CREDITS_FILE.read_text(encoding="utf-8"))
        existing["football_data"] = {"date": date.today().isoformat(), "used": _requests_used}
        _CREDITS_FILE.write_text(json.dumps(existing, indent=2), encoding="utf-8")
    except Exception:
        pass


def get_requests_used() -> int:
    return _requests_used


_load_fd_counter()

# Competition IDs — free tier διαθέσιμα
# Greek Super League ΔΕΝ είναι διαθέσιμο στο free tier
COMPETITIONS = {
    "premier_league":   "PL",
    "champions_league": "CL",
    "la_liga":          "PD",
    "bundesliga":       "BL1",
    "serie_a":          "SA",
    "ligue_1":          "FL1",
    "eredivisie":       "DED",
    "primeira_liga":    "PPL",
    "championship":     "ELC",
    "copa_libertadores": "CLI",
}


def _get(path: str, params: dict = None) -> dict | None:
    global _requests_used
    headers = {"X-Auth-Token": API_KEY} if API_KEY else {}
    try:
        r = requests.get(f"{BASE_URL}{path}", headers=headers, params=params or {}, timeout=15)
        print(f"[FootballData] {r.status_code} | {path}")
        if r.status_code == 200:
            _requests_used += 1
            _persist_fd_counter()
            return r.json()
        elif r.status_code == 403:
            if not API_KEY:
                print("[FootballData] Δεν βρέθηκε FOOTBALL_DATA_KEY στο .env")
            else:
                print("[FootballData] Ελέγξτε το API key")
        elif r.status_code == 429:
            print("[FootballData] Rate limit! (100 req/day για free tier)")
        else:
            print(f"[FootballData] Error {r.status_code}: {r.text[:150]}")
    except requests.RequestException as e:
        print(f"[FootballData] Network error: {e}")
    return None


def get_upcoming_matches(competition: str = "super_league", matchday: int = None) -> list:
    """
    Επερχόμενοι αγώνες για ένα πρωτάθλημα.
    competition: κλειδί από COMPETITIONS dict
    """
    comp_id = COMPETITIONS.get(competition, competition.upper())
    params = {"status": "SCHEDULED"}
    if matchday:
        params["matchday"] = matchday

    data = _get(f"/competitions/{comp_id}/matches", params)
    if not data:
        return []

    matches = []
    for m in data.get("matches", []):
        matches.append({
            "id":         m.get("id"),
            "home_team":  m["homeTeam"]["name"],
            "away_team":  m["awayTeam"]["name"],
            "home_id":    m["homeTeam"]["id"],
            "away_id":    m["awayTeam"]["id"],
            "date":       m.get("utcDate", "")[:10],
            "matchday":   m.get("matchday"),
            "status":     m.get("status"),
        })
    return matches


def get_team_stats(team_id: int, last_n: int = 6) -> dict:
    """
    Υπολογίζει μέσο όρο γκολ από τα τελευταία N παιχνίδια.
    Επιστρέφει dict συμβατό με TeamStats.
    """
    data = _get(f"/teams/{team_id}/matches", {"status": "FINISHED", "limit": last_n})
    if not data:
        return _default_stats()

    matches = data.get("matches", [])
    if not matches:
        return _default_stats()

    goals_scored   = []
    goals_conceded = []

    for m in matches:
        score = m.get("score", {}).get("fullTime", {})
        home_goals = score.get("home") or 0
        away_goals = score.get("away") or 0

        if m["homeTeam"]["id"] == team_id:
            goals_scored.append(home_goals)
            goals_conceded.append(away_goals)
        else:
            goals_scored.append(away_goals)
            goals_conceded.append(home_goals)

    n = len(goals_scored)
    return {
        "avg_goals_scored":   round(sum(goals_scored) / n, 3) if n else 1.2,
        "avg_goals_conceded": round(sum(goals_conceded) / n, 3) if n else 1.1,
        "games_analyzed":     n,
    }


def get_team_info(team_id: int) -> dict | None:
    data = _get(f"/teams/{team_id}")
    if not data:
        return None
    return {
        "id":   team_id,
        "name": data.get("name"),
        "short_name": data.get("shortName"),
    }


def _default_stats() -> dict:
    return {"avg_goals_scored": 1.2, "avg_goals_conceded": 1.1, "games_analyzed": 0}
