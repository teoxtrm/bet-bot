"""
Sofascore unofficial API scraper.
Δεν χρειάζεται login — τα endpoints επιστρέφουν JSON.
"""

import time
import requests
from config import SOFASCORE_BASE_URL, SOFASCORE_HEADERS


def _get(path: str, retries: int = 3) -> dict | None:
    url = f"{SOFASCORE_BASE_URL}{path}"
    for attempt in range(retries):
        try:
            resp = requests.get(url, headers=SOFASCORE_HEADERS, timeout=10)
            if resp.status_code == 200:
                return resp.json()
            elif resp.status_code == 429:
                time.sleep(2 ** attempt)  # exponential backoff
        except requests.RequestException as e:
            print(f"[Sofascore] Request error: {e}")
            time.sleep(1)
    return None


def get_matches_by_date(date_str: str) -> list:
    """
    Επιστρέφει αγώνες ποδοσφαίρου για συγκεκριμένη ημέρα.
    date_str format: "YYYY-MM-DD"
    """
    data = _get(f"/sport/football/scheduled-events/{date_str}")
    if not data:
        return []

    matches = []
    for event in data.get("events", []):
        matches.append({
            "id": event.get("id"),
            "home_team": event.get("homeTeam", {}).get("name"),
            "away_team": event.get("awayTeam", {}).get("name"),
            "home_team_id": event.get("homeTeam", {}).get("id"),
            "away_team_id": event.get("awayTeam", {}).get("id"),
            "tournament": event.get("tournament", {}).get("name"),
            "start_time": event.get("startTimestamp"),
            "status": event.get("status", {}).get("description"),
        })
    return matches


def get_team_last_matches(team_id: int, pages: int = 1) -> list:
    """
    Επιστρέφει τα τελευταία αποτελέσματα μιας ομάδας.
    Χρησιμοποιείται για υπολογισμό φόρμας.
    """
    all_events = []
    for page in range(pages):
        data = _get(f"/team/{team_id}/events/last/{page}")
        if not data:
            break
        events = data.get("events", [])
        for e in events:
            ht = e.get("homeScore", {})
            at = e.get("awayScore", {})
            all_events.append({
                "id": e.get("id"),
                "home_team": e.get("homeTeam", {}).get("name"),
                "away_team": e.get("awayTeam", {}).get("name"),
                "home_goals": ht.get("current", 0),
                "away_goals": at.get("current", 0),
                "total_goals": (ht.get("current", 0) or 0) + (at.get("current", 0) or 0),
            })
    return all_events


def get_live_matches() -> list:
    """Επιστρέφει live αγώνες ποδοσφαίρου."""
    data = _get("/sport/football/events/live")
    if not data:
        return []

    live = []
    for event in data.get("events", []):
        status = event.get("status", {})
        score_h = event.get("homeScore", {}).get("current", 0) or 0
        score_a = event.get("awayScore", {}).get("current", 0) or 0
        live.append({
            "id": event.get("id"),
            "home_team": event.get("homeTeam", {}).get("name"),
            "away_team": event.get("awayTeam", {}).get("name"),
            "score_home": score_h,
            "score_away": score_a,
            "total_goals": score_h + score_a,
            "minute": status.get("description", ""),
            "tournament": event.get("tournament", {}).get("name"),
        })
    return live


def build_team_stats_from_history(team_id: int, last_n: int = 6):
    """
    Υπολογίζει μέσο όρο γκολ από τα τελευταία N παιχνίδια.
    Επιστρέφει dict συμβατό με TeamStats.
    """
    matches = get_team_last_matches(team_id)[:last_n]
    if not matches:
        return None

    # Βρες σε ποια ομάδα ανήκει το team_id (home ή away)
    goals_scored = []
    goals_conceded = []
    for m in matches:
        # Δεν ξέρουμε το team name, οπότε ελέγχουμε και τις 2 πλευρές
        goals_scored.append(m["home_goals"])
        goals_conceded.append(m["away_goals"])

    avg_scored = sum(goals_scored) / len(goals_scored) if goals_scored else 1.2
    avg_conceded = sum(goals_conceded) / len(goals_conceded) if goals_conceded else 1.1

    return {
        "avg_goals_scored": round(avg_scored, 3),
        "avg_goals_conceded": round(avg_conceded, 3),
    }
