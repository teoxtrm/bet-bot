"""
API-Football (api-sports.io) — Live match statistics.
Free tier: 100 requests/day.

Strategy: only called when a value bet is found — conserves quota.
Live fixtures list is cached for 2 min so one scan = 1 fixtures fetch + N stats fetches.

Env var required: APIFOOTBALL_KEY
Sign up free at: https://dashboard.api-football.com/register
"""

import os
import json
import pathlib
import time
import requests
from dotenv import load_dotenv

load_dotenv()

BASE_URL = "https://v3.football.api-sports.io"
API_KEY  = os.getenv("API_FOOTBALL_KEY") or os.getenv("APIFOOTBALL_KEY", "")

# In-memory cache for live fixtures (avoid repeat calls in same scan)
_fixture_cache: list = []
_cache_ts: float = 0.0
CACHE_TTL = 120  # seconds

# Credit tracking
_CREDITS_FILE = pathlib.Path("data/api_credits.json")
_remaining: int | None = None


def _load_remaining():
    global _remaining
    try:
        saved = json.loads(_CREDITS_FILE.read_text(encoding="utf-8"))
        v = saved.get("apifootball", {}).get("remaining")
        if v is not None:
            _remaining = int(v)
    except Exception:
        pass


def _persist_remaining():
    try:
        _CREDITS_FILE.parent.mkdir(exist_ok=True)
        existing = {}
        if _CREDITS_FILE.exists():
            existing = json.loads(_CREDITS_FILE.read_text(encoding="utf-8"))
        existing["apifootball"] = {"remaining": _remaining}
        _CREDITS_FILE.write_text(json.dumps(existing, indent=2), encoding="utf-8")
    except Exception:
        pass


def get_remaining() -> int | None:
    """Return latest known API-Football daily requests remaining."""
    return _remaining


_load_remaining()


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
        rem = r.headers.get("x-ratelimit-requests-remaining")
        if rem is not None:
            global _remaining
            try:
                _remaining = int(rem)
                _persist_remaining()
            except (ValueError, TypeError):
                pass
        if r.status_code == 200:
            print(f"[APIFootball] {path} | remaining={rem}/100")
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


def get_team_form(team_id: int, last_n: int = 6) -> dict:
    """
    Recent form for any team in any league globally.
    Returns same structure as football_data.get_team_stats() for compatibility.
    Costs 1 API-Football request.
    """
    data = _get("/fixtures", {"team": team_id, "last": last_n, "status": "FT"})
    if not data or not data.get("response"):
        return {"avg_goals_scored": 1.2, "avg_goals_conceded": 1.1, "games_analyzed": 0}

    scored:   list[int] = []
    conceded: list[int] = []

    for f in data["response"]:
        teams = f.get("teams", {})
        goals = f.get("goals", {})
        is_home = teams.get("home", {}).get("id") == team_id
        g_home  = goals.get("home") or 0
        g_away  = goals.get("away") or 0
        if is_home:
            scored.append(g_home)
            conceded.append(g_away)
        else:
            scored.append(g_away)
            conceded.append(g_home)

    n = len(scored)
    return {
        "avg_goals_scored":   round(sum(scored)   / n, 3) if n else 1.2,
        "avg_goals_conceded": round(sum(conceded) / n, 3) if n else 1.1,
        "games_analyzed":     n,
    }


def discover_live_matches(
    max_tier:    int = 2,
    min_minute:  int = 8,
    max_minute:  int = 78,
    max_score_diff: int = 2,
    max_matches: int = 6,
) -> list[dict]:
    """
    Returns filtered live matches worth analyzing across all quality leagues.
    Costs exactly 1 API-Football request.

    Filters applied (all free, no extra requests):
      • League must be in LEAGUE_MAP with tier <= max_tier
      • Match minute between min_minute and max_minute
      • Score difference <= max_score_diff (skip blowouts)

    Returns list sorted by (tier, |minute - 30|) — best leagues first,
    prefer matches in the middle of each half.
    """
    from utils.league_map import LEAGUE_MAP

    fixtures = _refresh_live_fixtures()
    if not fixtures:
        return []

    candidates = []
    for f in fixtures:
        league_id = f.get("league", {}).get("id")
        if league_id not in LEAGUE_MAP:
            continue

        league_info = LEAGUE_MAP[league_id]
        if league_info["tier"] > max_tier:
            continue

        elapsed = f.get("fixture", {}).get("status", {}).get("elapsed") or 0
        if elapsed < min_minute or elapsed > max_minute:
            continue

        goals   = f.get("goals", {})
        home_g  = goals.get("home") or 0
        away_g  = goals.get("away") or 0
        if abs(home_g - away_g) > max_score_diff:
            continue

        teams = f.get("teams", {})
        candidates.append({
            "fixture_id":  f["fixture"]["id"],
            "home_team":   teams["home"]["name"],
            "away_team":   teams["away"]["name"],
            "home_id":     teams["home"]["id"],
            "away_id":     teams["away"]["id"],
            "league_id":   league_id,
            "league_name": league_info["name"],
            "odds_key":    league_info["odds_key"],
            "minute":      elapsed,
            "home_score":  home_g,
            "away_score":  away_g,
            "tier":        league_info["tier"],
        })

    # Best leagues first; within same league, prefer matches around minute 30
    candidates.sort(key=lambda x: (x["tier"], abs(x["minute"] - 30)))
    return candidates[:max_matches]


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
