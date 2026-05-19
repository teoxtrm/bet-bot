"""
Team Form Fetcher — Phase 2.
Provides: fetch_team_form(home_team, away_team, sport_key, env, db_path)

Provider dispatch (config.FORM_PROVIDER):
  "football_data" — football-data.org (free, 100 req/day, 9 covered competitions)
  "api_football"  — api-football (free, 100 req/day, global; shares budget with live scanner)

Team name → ID resolution:
  football-data.org: /competitions/{comp}/teams  → cached to data/fd_teams_cache.json (7 days)
  api-football:      /teams?search={name}        → cached to data/apif_teams_cache.json (30 days)

Form data (avg goals, last 5 results):
  Cached in the team_form SQLite table (23 h max age — effectively once per day).
  Falls back gracefully; caller checks return values for None.
"""

import json
import os
import pathlib
import re
import tempfile
from datetime import date

from config import FORM_PROVIDER

_CACHE_DIR       = pathlib.Path("data")
_FD_TEAMS_FILE   = _CACHE_DIR / "fd_teams_cache.json"
_APIF_TEAMS_FILE = _CACHE_DIR / "apif_teams_cache.json"

# Odds API sport_key → football-data.org competition code
_FD_SPORT_TO_COMP: dict[str, str] = {
    "soccer_epl":                      "PL",
    "soccer_uefa_champs_league":        "CL",
    "soccer_spain_la_liga":            "PD",
    "soccer_germany_bundesliga":       "BL1",
    "soccer_italy_serie_a":            "SA",
    "soccer_france_ligue_one":         "FL1",
    "soccer_netherlands_eredivisie":   "DED",
    "soccer_portugal_primeira_liga":   "PPL",
    "soccer_efl_champ":                "ELC",
}


# ── Name normalisation & fuzzy matching ───────────────────────────────────────

def _norm(name: str) -> str:
    n = name.lower().strip()
    for sfx in (" fc", " cf", " sc", " ac", " afc", " fk", " sk", " bk", " if", " utd"):
        if n.endswith(sfx):
            n = n[: -len(sfx)].strip()
    return re.sub(r"\s+", " ", n)


def _best_id(target: str, name_to_id: dict) -> int | None:
    norm_t = _norm(target)
    norm_map = {_norm(k): v for k, v in name_to_id.items()}

    if norm_t in norm_map:
        return norm_map[norm_t]

    for k, v in norm_map.items():
        if norm_t in k or k in norm_t:
            return v

    words = [w for w in norm_t.split() if len(w) > 3]
    best, best_score = None, 0
    for k, v in norm_map.items():
        score = sum(1 for w in words if w in k)
        if score > best_score and score >= max(1, len(words) - 1):
            best_score, best = score, v
    return best


# ── football-data.org helpers ─────────────────────────────────────────────────

def _load_fd_cache() -> dict:
    try:
        return json.loads(_FD_TEAMS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_fd_cache(data: dict):
    _CACHE_DIR.mkdir(exist_ok=True)
    text = json.dumps(data, ensure_ascii=False, indent=2)
    with tempfile.NamedTemporaryFile("w", dir=_CACHE_DIR, delete=False,
                                     suffix=".tmp", encoding="utf-8") as tf:
        tf.write(text)
    os.replace(tf.name, _FD_TEAMS_FILE)


def _resolve_fd_id(team_name: str, comp_code: str) -> int | None:
    """Return football-data.org team ID. Fetches /competitions/{comp}/teams at most once a week."""
    import requests

    api_key = os.environ.get("FOOTBALL_DATA_KEY", "")
    if not api_key:
        return None

    cache = _load_fd_cache()
    entry = cache.get(comp_code, {})
    try:
        age_days = (date.today() - date.fromisoformat(entry.get("date", "2000-01-01"))).days
        fresh = age_days < 7 and bool(entry.get("teams"))
    except Exception:
        fresh = False

    if not fresh:
        try:
            r = requests.get(
                f"https://api.football-data.org/v4/competitions/{comp_code}/teams",
                headers={"X-Auth-Token": api_key},
                timeout=10,
            )
            if r.status_code == 429:
                print(f"[TeamForm] FD rate limit — using stale cache for {comp_code}")
            elif r.status_code == 200:
                teams: dict[str, int] = {}
                for t in r.json().get("teams", []):
                    for field in ("name", "shortName", "tla"):
                        val = t.get(field)
                        if val:
                            teams[val] = t["id"]
                entry = {"date": date.today().isoformat(), "teams": teams}
                cache[comp_code] = entry
                _save_fd_cache(cache)
                print(f"[TeamForm] FD teams cached: {comp_code} ({len(teams)} teams)")
        except Exception as exc:
            print(f"[TeamForm] FD comp teams error ({comp_code}): {exc}")

    return _best_id(team_name, entry.get("teams", {}))


def _fetch_fd_form(team_id: int, team_name: str, db_path: str) -> dict | None:
    """Fetch form from football-data.org (DB-cached per day)."""
    import requests
    from utils.database import get_team_form_cached, upsert_team_form

    cached = get_team_form_cached(team_id, max_age_hours=23, db_path=db_path)
    if cached:
        return cached

    api_key = os.environ.get("FOOTBALL_DATA_KEY", "")
    if not api_key:
        return None

    try:
        r = requests.get(
            f"https://api.football-data.org/v4/teams/{team_id}/matches",
            headers={"X-Auth-Token": api_key},
            params={"status": "FINISHED", "limit": 6},
            timeout=12,
        )
        if r.status_code != 200:
            print(f"[TeamForm] FD form fetch HTTP {r.status_code} for team {team_id}")
            return None

        matches = r.json().get("matches", [])
        if not matches:
            return None

        scored, conceded, last_5 = [], [], []
        for m in matches:
            ft = m.get("score", {}).get("fullTime", {})
            h, a = ft.get("home") or 0, ft.get("away") or 0
            is_home = m.get("homeTeam", {}).get("id") == team_id
            gs, gc = (h, a) if is_home else (a, h)
            scored.append(gs)
            conceded.append(gc)
            result = "W" if gs > gc else ("D" if gs == gc else "L")
            opp_key = "awayTeam" if is_home else "homeTeam"
            last_5.append({
                "result":   result,
                "scored":   gs,
                "conceded": gc,
                "opponent": m.get(opp_key, {}).get("name", ""),
                "date":     m.get("utcDate", "")[:10],
            })

        n = len(scored)
        form = {
            "avg_goals_scored":   round(sum(scored)   / n, 3),
            "avg_goals_conceded": round(sum(conceded) / n, 3),
            "games_analyzed":     n,
            "last_5_results":     last_5[-5:],
        }
        upsert_team_form(
            team_id=team_id, team_name=team_name,
            avg_goals_scored=form["avg_goals_scored"],
            avg_goals_conceded=form["avg_goals_conceded"],
            games_analyzed=n,
            last_5_results=last_5[-5:],
            db_path=db_path,
        )
        print(f"[TeamForm] FD fetched: {team_name} | {form['avg_goals_scored']}g / {form['avg_goals_conceded']}ga")
        return form
    except Exception as exc:
        print(f"[TeamForm] FD form error for {team_name}: {exc}")
        return None


# ── api-football helpers ──────────────────────────────────────────────────────

def _load_apif_cache() -> dict:
    try:
        return json.loads(_APIF_TEAMS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_apif_cache(data: dict):
    _CACHE_DIR.mkdir(exist_ok=True)
    text = json.dumps(data, ensure_ascii=False, indent=2)
    with tempfile.NamedTemporaryFile("w", dir=_CACHE_DIR, delete=False,
                                     suffix=".tmp", encoding="utf-8") as tf:
        tf.write(text)
    os.replace(tf.name, _APIF_TEAMS_FILE)


def _resolve_apif_id(team_name: str, league_id: int) -> int | None:
    """Return api-football team ID (cached 30 days)."""
    import requests

    cache     = _load_apif_cache()
    cache_key = f"{_norm(team_name)}__{league_id}"
    entry     = cache.get(cache_key, {})
    if entry.get("id"):
        try:
            age = (date.today() - date.fromisoformat(entry["date"])).days
            if age < 30:
                return entry["id"]
        except Exception:
            pass

    api_key = os.environ.get("API_FOOTBALL_KEY") or os.environ.get("APIFOOTBALL_KEY", "")
    if not api_key:
        return None

    try:
        # api-football does not allow search + league together — search by name only
        r = requests.get(
            "https://v3.football.api-sports.io/teams",
            headers={"x-apisports-key": api_key},
            params={"search": team_name[:30]},
            timeout=8,
        )
        if r.status_code != 200:
            return None
        resp = r.json().get("response", [])
        if not resp:
            return None

        name_to_id = {t["team"]["name"]: t["team"]["id"] for t in resp}
        team_id = _best_id(team_name, name_to_id) or resp[0]["team"]["id"]

        cache[cache_key] = {"id": team_id, "date": date.today().isoformat()}
        _save_apif_cache(cache)
        return team_id
    except Exception as exc:
        print(f"[TeamForm] APIF team search error for '{team_name}': {exc}")
        return None


def _fetch_apif_form(team_id: int, team_name: str, league_id: int, db_path: str) -> dict | None:
    """Fetch form from api-football (DB-cached per day)."""
    import requests
    from utils.database import get_team_form_cached, upsert_team_form

    cached = get_team_form_cached(team_id, max_age_hours=23, db_path=db_path)
    if cached:
        return cached

    api_key = os.environ.get("API_FOOTBALL_KEY") or os.environ.get("APIFOOTBALL_KEY", "")
    if not api_key:
        return None

    try:
        # Free plan: no "last" param — fetch by season, filter FT in Python
        today = date.today()
        season = today.year - 1 if today.month <= 7 else today.year
        r = requests.get(
            "https://v3.football.api-sports.io/fixtures",
            headers={"x-apisports-key": api_key},
            params={"team": team_id, "season": season},
            timeout=10,
        )
        if r.status_code != 200:
            print(f"[TeamForm] APIF fixtures HTTP {r.status_code} for {team_name}")
            return None

        resp = r.json()
        if resp.get("errors"):
            print(f"[TeamForm] APIF error for {team_name}: {resp['errors']}")
            return None

        # Keep only finished matches, most recent first, take last 6
        all_fixtures = resp.get("response", [])
        finished = [f for f in all_fixtures
                    if f.get("fixture", {}).get("status", {}).get("short") == "FT"]
        finished.sort(key=lambda f: f["fixture"]["date"], reverse=True)
        fixtures = finished[:6]

        if not fixtures:
            return None

        scored, conceded, last_5 = [], [], []
        for f in fixtures:
            teams = f.get("teams", {})
            goals = f.get("goals", {})
            is_home = teams.get("home", {}).get("id") == team_id
            gh, ga  = goals.get("home") or 0, goals.get("away") or 0
            gs, gc  = (gh, ga) if is_home else (ga, gh)
            scored.append(gs)
            conceded.append(gc)
            result  = "W" if gs > gc else ("D" if gs == gc else "L")
            opp_key = "away" if is_home else "home"
            last_5.append({
                "result":   result,
                "scored":   gs,
                "conceded": gc,
                "opponent": teams.get(opp_key, {}).get("name", ""),
                "date":     f.get("fixture", {}).get("date", "")[:10],
            })

        n = len(scored)
        form = {
            "avg_goals_scored":   round(sum(scored)   / n, 3),
            "avg_goals_conceded": round(sum(conceded) / n, 3),
            "games_analyzed":     n,
            "last_5_results":     last_5,
        }
        upsert_team_form(
            team_id=team_id, team_name=team_name,
            avg_goals_scored=form["avg_goals_scored"],
            avg_goals_conceded=form["avg_goals_conceded"],
            games_analyzed=n, league_id=league_id,
            last_5_results=last_5,
            db_path=db_path,
        )
        print(f"[TeamForm] APIF fetched: {team_name} | {form['avg_goals_scored']}g / {form['avg_goals_conceded']}ga")
        return form
    except Exception as exc:
        print(f"[TeamForm] APIF form error for {team_name}: {exc}")
        return None


# ── Public API ─────────────────────────────────────────────────────────────────

def fetch_team_form(
    home_team: str,
    away_team: str,
    sport_key: str,
    env:       dict,
    db_path:   str,
) -> tuple[dict | None, dict | None, str | None]:
    """
    Returns (home_form, away_form, source_name).
    home/away_form keys: avg_goals_scored, avg_goals_conceded, games_analyzed, last_5_results
    source_name: "football_data" | "api_football" | None (league not supported)

    Provider logic (dual mode):
      1. Always try football-data.org first for its 9 covered competitions.
      2. For all other leagues, fall back to api-football — but only if the
         daily budget has at least 60 requests remaining (live scanner priority).
    """
    for k, v in env.items():
        os.environ[k] = v

    # ── football-data.org (9 competitions, no budget conflict) ────────────────
    comp_code = _FD_SPORT_TO_COMP.get(sport_key)
    if comp_code:
        home_id = _resolve_fd_id(home_team, comp_code)
        away_id = _resolve_fd_id(away_team, comp_code)
        home_form = _fetch_fd_form(home_id, home_team, db_path) if home_id else None
        away_form = _fetch_fd_form(away_id, away_team, db_path) if away_id else None
        if home_form is not None or away_form is not None:
            return home_form, away_form, "football_data"

    # api-football free plan only covers seasons 2022–2024, not the current season.
    # Fallback disabled until a working free source is found.
    return None, None, None
