"""
Greek Super League stats — χτίζεται από το The Odds API scores endpoint.
Αποθηκεύει τοπικά σε JSON και εμπλουτίζεται με κάθε εκτέλεση.

Στρατηγική:
  - Κάθε φορά που τρέχει, τραβάει αποτελέσματα των τελευταίων 3 ημερών
  - Τα αποθηκεύει στο data/processed/greek_results.json
  - Υπολογίζει rolling avg goals για κάθε ομάδα (τελευταία 6 παιχνίδια)
"""

import json
import os
import requests
from datetime import datetime, timezone
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

CACHE_FILE = Path("data/processed/greek_results.json")
BASE_URL   = "https://api.the-odds-api.com/v4"
API_KEY    = os.getenv("ODDS_API_KEY", "")


def _fetch_recent_scores(days: int = 3) -> list:
    if not API_KEY:
        return []
    r = requests.get(
        f"{BASE_URL}/sports/soccer_greece_super_league/scores/",
        params={"apiKey": API_KEY, "daysFrom": days, "dateFormat": "iso"},
        timeout=15,
    )
    remaining = r.headers.get("x-requests-remaining", "?")
    print(f"[GreekStats] scores fetch: {r.status_code} | remaining={remaining}")
    if r.status_code != 200:
        return []
    return r.json()


def _load_cache() -> dict:
    if CACHE_FILE.exists():
        return json.loads(CACHE_FILE.read_text(encoding="utf-8"))
    return {"results": [], "last_updated": None}


def _save_cache(data: dict):
    CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    CACHE_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def update_results_cache() -> int:
    """
    Τραβάει νέα αποτελέσματα και τα προσθέτει στο cache.
    Επιστρέφει πόσα νέα αποτελέσματα προστέθηκαν.
    """
    cache   = _load_cache()
    known   = {r["id"] for r in cache["results"]}
    fresh   = _fetch_recent_scores(days=3)
    added   = 0

    for event in fresh:
        if not event.get("completed"):
            continue
        if event["id"] in known:
            continue
        scores = event.get("scores") or []
        if len(scores) < 2:
            continue

        score_map = {s["name"]: int(s["score"]) for s in scores}
        home = event["home_team"]
        away = event["away_team"]

        cache["results"].append({
            "id":         event["id"],
            "date":       event["commence_time"][:10],
            "home_team":  home,
            "away_team":  away,
            "home_goals": score_map.get(home, 0),
            "away_goals": score_map.get(away, 0),
        })
        added += 1

    cache["last_updated"] = datetime.now(timezone.utc).isoformat()
    _save_cache(cache)
    print(f"[GreekStats] +{added} νέα αποτελέσματα | σύνολο={len(cache['results'])}")
    return added


def get_team_stats(team_name: str, last_n: int = 6) -> dict:
    """
    Υπολογίζει avg goals scored/conceded για ελληνική ομάδα
    από τα αποθηκευμένα αποτελέσματα.
    """
    cache   = _load_cache()
    results = cache.get("results", [])

    team_matches = [
        r for r in results
        if r["home_team"] == team_name or r["away_team"] == team_name
    ]
    # Πιο πρόσφατα πρώτα
    team_matches = sorted(team_matches, key=lambda x: x["date"], reverse=True)[:last_n]

    if not team_matches:
        return {"avg_goals_scored": 1.2, "avg_goals_conceded": 1.1, "games_analyzed": 0}

    scored    = []
    conceded  = []
    for m in team_matches:
        if m["home_team"] == team_name:
            scored.append(m["home_goals"])
            conceded.append(m["away_goals"])
        else:
            scored.append(m["away_goals"])
            conceded.append(m["home_goals"])

    n = len(scored)
    return {
        "avg_goals_scored":   round(sum(scored) / n, 3),
        "avg_goals_conceded": round(sum(conceded) / n, 3),
        "games_analyzed": n,
    }


def get_all_teams() -> list:
    """Λίστα με όλες τις ομάδες που έχουμε δεδομένα."""
    cache = _load_cache()
    teams = set()
    for r in cache.get("results", []):
        teams.add(r["home_team"])
        teams.add(r["away_team"])
    return sorted(teams)


def get_cache_summary() -> str:
    cache = _load_cache()
    results = cache.get("results", [])
    teams   = get_all_teams()
    updated = cache.get("last_updated", "ποτέ")[:10] if cache.get("last_updated") else "ποτέ"
    return (
        f"{len(results)} αποτελέσματα | "
        f"{len(teams)} ομάδες | "
        f"τελευταία ενημέρωση: {updated}"
    )
