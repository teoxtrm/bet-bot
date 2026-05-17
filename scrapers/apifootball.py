"""
API-Football (api-sports.io) — Live match statistics.
Free tier: 100 requests/day.

Strategy: only called when a value bet is found — conserves quota.
Live fixtures list is cached for 2 min so one scan = 1 fixtures fetch + N stats fetches.

Env var required: APIFOOTBALL_KEY
Sign up free at: https://dashboard.api-football.com/register
"""

import os
import time
import requests
from dotenv import load_dotenv

load_dotenv()

BASE_URL = "https://v3.football.api-sports.io"
API_KEY  = os.getenv("APIFOOTBALL_KEY", "")

# In-memory cache for live fixtures (avoid repeat calls in same scan)
_fixture_cache: list = []
_cache_ts: float = 0.0
CACHE_TTL = 120  # seconds


def _get(path: str, params: dict = None) -> dict | None:
    if not API_KEY:
        return None
    try:
        r = requests.get(
            f"{BASE_URL}{path}",
            headers={"x-apisports-key": API_KEY},
            params=params or {},
            timeout=10,
        )
        remaining = r.headers.get("x-ratelimit-requests-remaining", "?")
        if r.status_code == 200:
            print(f"[APIFootball] {path} | remaining={remaining}/100")
            return r.json()
        print(f"[APIFootball] Error {r.status_code}: {r.text[:120]}")
    except requests.RequestException as e:
        print(f"[APIFootball] Network error: {e}")
    return None


def _refresh_live_fixtures() -> list:
    """Fetch all currently live fixtures. Cached for CACHE_TTL seconds."""
    global _fixture_cache, _cache_ts
    if time.time() - _cache_ts < CACHE_TTL and _fixture_cache:
        return _fixture_cache
    data = _get("/fixtures", {"live": "all"})
    if data and data.get("response"):
        _fixture_cache = data["response"]
        _cache_ts = time.time()
    return _fixture_cache


def _fuzzy_match(name: str, candidate: str) -> bool:
    n, c = name.lower(), candidate.lower()
    if n in c or c in n:
        return True
    # word-level: any word longer than 3 chars appears in candidate
    return any(w in c for w in n.split() if len(w) > 3)


def _find_fixture_id(home_team: str, away_team: str) -> int | None:
    for f in _refresh_live_fixtures():
        teams = f.get("teams", {})
        h = teams.get("home", {}).get("name", "")
        a = teams.get("away", {}).get("name", "")
        if _fuzzy_match(home_team, h) and _fuzzy_match(away_team, a):
            return f["fixture"]["id"]
    return None


def get_live_stats(home_team: str, away_team: str) -> dict | None:
    """
    Returns live statistics for a match, or None if not found / key missing.

    Costs: 0 requests if fixture cache is warm; 1 request for statistics.
    Keys returned:
        shots_ot_home, shots_ot_away, shots_ot_total,
        corners_home, corners_away,
        possession_home, possession_away,
        shots_str, corners_str, possession_str
    """
    if not API_KEY:
        return None

    fixture_id = _find_fixture_id(home_team, away_team)
    if not fixture_id:
        return None

    data = _get("/fixtures/statistics", {"fixture": fixture_id})
    if not data or len(data.get("response", [])) < 2:
        return None

    def _stat(team_resp: dict, stat_type: str) -> str | None:
        for s in team_resp.get("statistics", []):
            if s["type"] == stat_type:
                return s["value"]
        return None

    def _int(v) -> int:
        try:
            return int(v or 0)
        except (ValueError, TypeError):
            return 0

    def _pct(v) -> int | None:
        if v is None:
            return None
        try:
            return int(str(v).replace("%", "").strip())
        except (ValueError, TypeError):
            return None

    home_r = data["response"][0]
    away_r = data["response"][1]

    home_sot = _int(_stat(home_r, "Shots on Target"))
    away_sot = _int(_stat(away_r, "Shots on Target"))
    home_cor = _int(_stat(home_r, "Corner Kicks"))
    away_cor = _int(_stat(away_r, "Corner Kicks"))
    home_pos = _pct(_stat(home_r, "Ball Possession"))

    return {
        "shots_ot_home":   home_sot,
        "shots_ot_away":   away_sot,
        "shots_ot_total":  home_sot + away_sot,
        "corners_home":    home_cor,
        "corners_away":    away_cor,
        "possession_home": home_pos,
        "shots_str":       f"{home_sot}-{away_sot}",
        "corners_str":     f"{home_cor}-{away_cor}",
        "possession_str":  f"{home_pos}%" if home_pos is not None else "—",
    }
