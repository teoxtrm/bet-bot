"""
Persist the last pre-game scan to disk so the GUI survives restarts.
Saved as data/last_scan.json.  Stale if scan_date != today.

Per-league cache in data/league_scans.json:
  {sport_key: {date, rows, events_data, targets}}
Allows ALL LEAGUES scan to skip leagues already scanned today (0 credits).
"""
import json
import dataclasses
import pathlib
from datetime import date, datetime

CACHE_FILE        = pathlib.Path("data/last_scan.json")
LEAGUE_CACHE_FILE = pathlib.Path("data/league_scans.json")


def _paths(user_dir=None):
    if user_dir:
        base = pathlib.Path(user_dir)
        return base / "last_scan.json", base / "league_scans.json"
    return CACHE_FILE, LEAGUE_CACHE_FILE


def _ensure_dir(user_dir=None):
    cache_file, _ = _paths(user_dir)
    cache_file.parent.mkdir(parents=True, exist_ok=True)


def _target_to_dict(t) -> dict:
    d = dataclasses.asdict(t)
    d.pop("tags", None)   # tags is a list — fine to keep but strip if needed
    return d


def _pick_to_dict(p) -> dict:
    return dataclasses.asdict(p)


def _row_to_dict(r: dict) -> dict:
    """Strip non-serializable 'event' key; keep display fields only."""
    return {k: v for k, v in r.items() if k != "event" and k != "value_result" and k != "kelly_result"}


def _watchlist_to_dict(g) -> dict:
    return dataclasses.asdict(g)


def save_scan(rows: list, targets: list, tipster_picks: list, watchlist: list = None,
              user_dir=None):
    _ensure_dir(user_dir)
    cache_file, _ = _paths(user_dir)
    try:
        data = {
            "saved_at":       datetime.now().isoformat(),
            "scan_date":      date.today().isoformat(),
            "rows":           [_row_to_dict(r) for r in rows],
            "targets":        [_target_to_dict(t) for t in targets],
            "tipster_picks":  [_pick_to_dict(p) for p in tipster_picks],
            "watchlist":      [_watchlist_to_dict(g) for g in (watchlist or [])],
        }
        cache_file.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except Exception as e:
        print(f"[ScanCache] save error: {e}")


def load_scan(user_dir=None) -> dict | None:
    """Return cached scan if from today, else None."""
    cache_file, _ = _paths(user_dir)
    try:
        data = json.loads(cache_file.read_text(encoding="utf-8"))
        if data.get("scan_date") != date.today().isoformat():
            return None
        return data
    except Exception:
        return None


# ── Per-league cache ──────────────────────────────────────────────────────────

def save_league_scan(sport_key: str, rows: list, events_data: list, targets: list,
                     user_dir=None):
    """Save scan results for one league. Merges into league_scans.json."""
    _ensure_dir(user_dir)
    _, league_file = _paths(user_dir)
    try:
        try:
            existing = json.loads(league_file.read_text(encoding="utf-8"))
        except Exception:
            existing = {}
        existing[sport_key] = {
            "date":        date.today().isoformat(),
            "rows":        [_row_to_dict(r) for r in rows],
            "events_data": events_data,
            "targets":     [dataclasses.asdict(t) for t in targets],
        }
        league_file.write_text(
            json.dumps(existing, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except Exception as e:
        print(f"[ScanCache] save_league error: {e}")


def load_league_scan(sport_key: str, user_dir=None) -> dict | None:
    """Return cached league scan if from today, else None."""
    _, league_file = _paths(user_dir)
    try:
        existing = json.loads(league_file.read_text(encoding="utf-8"))
        entry = existing.get(sport_key)
        if not entry or entry.get("date") != date.today().isoformat():
            return None
        return entry
    except Exception:
        return None


def load_all_league_scans(user_dir=None) -> dict:
    """Return all today's cached league scans as {sport_key: entry}."""
    _, league_file = _paths(user_dir)
    today = date.today().isoformat()
    try:
        existing = json.loads(league_file.read_text(encoding="utf-8"))
        return {sk: v for sk, v in existing.items() if v.get("date") == today}
    except Exception:
        return {}


def clear_league_cache(user_dir=None):
    """Wipe the per-league cache."""
    _, league_file = _paths(user_dir)
    try:
        league_file.write_text("{}", encoding="utf-8")
    except Exception:
        pass
