"""
Persist the last pre-game scan to disk so the GUI survives restarts.
Saved as data/last_scan.json.  Stale if scan_date != today.
"""
import json
import dataclasses
import pathlib
from datetime import date, datetime

CACHE_FILE = pathlib.Path("data/last_scan.json")


def _ensure_dir():
    CACHE_FILE.parent.mkdir(exist_ok=True)


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


def save_scan(rows: list, targets: list, tipster_picks: list, watchlist: list = None):
    _ensure_dir()
    try:
        data = {
            "saved_at":       datetime.now().isoformat(),
            "scan_date":      date.today().isoformat(),
            "rows":           [_row_to_dict(r) for r in rows],
            "targets":        [_target_to_dict(t) for t in targets],
            "tipster_picks":  [_pick_to_dict(p) for p in tipster_picks],
            "watchlist":      [_watchlist_to_dict(g) for g in (watchlist or [])],
        }
        CACHE_FILE.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except Exception as e:
        print(f"[ScanCache] save error: {e}")


def load_scan() -> dict | None:
    """Return cached scan if from today, else None."""
    try:
        data = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
        if data.get("scan_date") != date.today().isoformat():
            return None
        return data
    except Exception:
        return None
