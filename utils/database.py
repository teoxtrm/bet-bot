"""
SQLite Database Manager — data/bet_bot.db
=========================================
Πίνακες:
  bets_tracked  — κάθε value bet που εντοπίστηκε
  settlements   — ιστορικό settlement actions (audit log)
"""

import sqlite3
import os
from datetime import datetime, timezone
from pathlib import Path
from contextlib import contextmanager

DB_PATH = Path("data/bet_bot.db")

# ─── SCHEMA ──────────────────────────────────────────────────────────────────

SCHEMA = """
CREATE TABLE IF NOT EXISTS bets_tracked (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id         TEXT,
    match_date       TEXT    NOT NULL,
    league           TEXT    NOT NULL,
    home_team        TEXT    NOT NULL,
    away_team        TEXT    NOT NULL,
    bet_type         TEXT    NOT NULL,   -- "Over 2.5", "Home Win", "BTTS Yes", κ.ά.
    our_probability  REAL    NOT NULL,
    bookmaker        TEXT    NOT NULL,
    bookmaker_odds   REAL    NOT NULL,
    value_edge_pct   REAL    NOT NULL,
    kelly_stake      REAL    NOT NULL,   -- σε ευρώ
    is_live          INTEGER NOT NULL DEFAULT 0,
    live_minute      INTEGER,            -- NULL αν pre-game
    status           TEXT    NOT NULL DEFAULT 'Pending',  -- Pending/Win/Loss/Void
    final_home_goals INTEGER,
    final_away_goals INTEGER,
    profit_loss      REAL,               -- υπολογίζεται στο settlement
    settled_at       TEXT,
    created_at       TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS settlements (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    bet_id       INTEGER NOT NULL REFERENCES bets_tracked(id),
    old_status   TEXT    NOT NULL,
    new_status   TEXT    NOT NULL,
    home_goals   INTEGER,
    away_goals   INTEGER,
    profit_loss  REAL,
    settled_at   TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_bets_status   ON bets_tracked(status);
CREATE INDEX IF NOT EXISTS idx_bets_league   ON bets_tracked(league);
CREATE INDEX IF NOT EXISTS idx_bets_event_id ON bets_tracked(event_id);
CREATE INDEX IF NOT EXISTS idx_bets_teams    ON bets_tracked(home_team, away_team, match_date);
"""


# ─── CONNECTION ───────────────────────────────────────────────────────────────

@contextmanager
def _conn():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    try:
        yield con
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


def init_db():
    """Δημιουργεί τους πίνακες αν δεν υπάρχουν."""
    with _conn() as con:
        con.executescript(SCHEMA)
    print(f"[DB] Initialized: {DB_PATH.resolve()}")


# ─── INSERT ──────────────────────────────────────────────────────────────────

def insert_bet(
    event_id: str,
    match_date: str,
    league: str,
    home_team: str,
    away_team: str,
    bet_type: str,
    our_probability: float,
    bookmaker: str,
    bookmaker_odds: float,
    value_edge_pct: float,
    kelly_stake: float,
    is_live: bool = False,
    live_minute: int = None,
) -> int:
    """
    Καταχωρεί ένα value bet. Αποφεύγει duplicate (ίδιο event+bet_type+bookmaker εντός 4ωρου).
    Επιστρέφει το ID του record ή -1 αν είναι duplicate.
    """
    with _conn() as con:
        # Duplicate check
        existing = con.execute("""
            SELECT id FROM bets_tracked
            WHERE home_team = ? AND away_team = ? AND bet_type = ? AND bookmaker = ?
              AND status = 'Pending'
              AND datetime(created_at) > datetime('now', '-4 hours')
        """, (home_team, away_team, bet_type, bookmaker)).fetchone()

        if existing:
            return -1  # duplicate

        cur = con.execute("""
            INSERT INTO bets_tracked
              (event_id, match_date, league, home_team, away_team,
               bet_type, our_probability, bookmaker, bookmaker_odds,
               value_edge_pct, kelly_stake, is_live, live_minute)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            event_id, match_date, league, home_team, away_team,
            bet_type, our_probability, bookmaker, bookmaker_odds,
            value_edge_pct, kelly_stake, int(is_live), live_minute,
        ))
        return cur.lastrowid


def track_value_bet(value_result: dict, kelly_result: dict,
                    match_info: dict, league: str,
                    is_live: bool = False, live_minute: int = None) -> int:
    """
    Wrapper για εύκολη καταγραφή από value_calculator output.

    Args:
        value_result: output από calculate_value()
        kelly_result: output από kelly_criterion()
        match_info: {"event_id", "match_date", "home_team", "away_team", "bet_type"}
    """
    bet_id = insert_bet(
        event_id       = match_info.get("event_id", ""),
        match_date     = match_info.get("match_date", datetime.now().strftime("%Y-%m-%d")),
        league         = league,
        home_team      = match_info["home_team"],
        away_team      = match_info["away_team"],
        bet_type       = match_info["bet_type"],
        our_probability= value_result["our_probability"],
        bookmaker      = value_result.get("bookmaker", "unknown"),
        bookmaker_odds = value_result["bookmaker_odds"],
        value_edge_pct = value_result["value_edge"],
        kelly_stake    = kelly_result["suggested_bet"],
        is_live        = is_live,
        live_minute    = live_minute,
    )
    if bet_id > 0:
        print(f"[DB] Tracked bet #{bet_id}: {match_info['home_team']} vs {match_info['away_team']} — {match_info['bet_type']}")
    return bet_id


# ─── QUERIES ─────────────────────────────────────────────────────────────────

def get_pending_bets() -> list[dict]:
    with _conn() as con:
        rows = con.execute("""
            SELECT * FROM bets_tracked WHERE status = 'Pending'
            ORDER BY match_date ASC, created_at ASC
        """).fetchall()
    return [dict(r) for r in rows]


def get_all_bets(limit: int = 100) -> list[dict]:
    with _conn() as con:
        rows = con.execute("""
            SELECT * FROM bets_tracked ORDER BY created_at DESC LIMIT ?
        """, (limit,)).fetchall()
    return [dict(r) for r in rows]


def get_stats() -> dict:
    with _conn() as con:
        row = con.execute("""
            SELECT
                COUNT(*)                                     AS total_bets,
                SUM(CASE WHEN status='Pending' THEN 1 END)  AS pending,
                SUM(CASE WHEN status='Win'     THEN 1 END)  AS wins,
                SUM(CASE WHEN status='Loss'    THEN 1 END)  AS losses,
                SUM(CASE WHEN status='Void'    THEN 1 END)  AS voids,
                SUM(kelly_stake)                             AS total_staked,
                SUM(COALESCE(profit_loss, 0))                AS total_pnl,
                AVG(CASE WHEN status IN ('Win','Loss') THEN value_edge_pct END) AS avg_edge,
                AVG(CASE WHEN status IN ('Win','Loss') THEN bookmaker_odds END) AS avg_odds,
                MAX(profit_loss)                             AS best_win,
                MIN(profit_loss)                             AS worst_loss
            FROM bets_tracked
        """).fetchone()
    d = dict(row)
    settled = (d["wins"] or 0) + (d["losses"] or 0)
    d["win_rate"]   = (d["wins"] or 0) / settled if settled > 0 else 0.0
    d["roi"]        = ((d["total_pnl"] or 0) / d["total_staked"] * 100) if (d["total_staked"] or 0) > 0 else 0.0
    d["settled"]    = settled
    return d


# ─── SETTLEMENT ──────────────────────────────────────────────────────────────

def _determine_outcome(bet_type: str, home_goals: int, away_goals: int) -> str:
    """Καθορίζει Win/Loss βάσει bet_type και τελικού σκορ."""
    total = home_goals + away_goals
    bt    = bet_type.lower().strip()

    rules = {
        "over 0.5":  lambda: total > 0,
        "over 1.5":  lambda: total > 1,
        "over 2.5":  lambda: total > 2,
        "over 3.5":  lambda: total > 3,
        "over 4.5":  lambda: total > 4,
        "under 0.5": lambda: total < 1,
        "under 1.5": lambda: total < 2,
        "under 2.5": lambda: total < 3,
        "under 3.5": lambda: total < 4,
        "under 4.5": lambda: total < 5,
        "btts yes":  lambda: home_goals > 0 and away_goals > 0,
        "btts no":   lambda: home_goals == 0 or away_goals == 0,
        "home win":  lambda: home_goals > away_goals,
        "draw":      lambda: home_goals == away_goals,
        "away win":  lambda: away_goals > home_goals,
        "1":         lambda: home_goals > away_goals,
        "x":         lambda: home_goals == away_goals,
        "2":         lambda: away_goals > home_goals,
    }

    for key, check in rules.items():
        if key in bt:
            return "Win" if check() else "Loss"

    return "Void"  # αγνωστος τύπος


def settle_bet(bet_id: int, home_goals: int, away_goals: int) -> dict:
    """
    Κλείνει ένα στοίχημα με το τελικό σκορ.
    Επιστρέφει {"status", "profit_loss"}.
    """
    with _conn() as con:
        bet = con.execute("SELECT * FROM bets_tracked WHERE id=?", (bet_id,)).fetchone()
        if not bet:
            return {"error": f"Bet #{bet_id} not found"}
        if bet["status"] != "Pending":
            return {"error": f"Bet #{bet_id} already settled ({bet['status']})"}

        bet = dict(bet)
        new_status = _determine_outcome(bet["bet_type"], home_goals, away_goals)

        if new_status == "Win":
            pnl = round(bet["kelly_stake"] * (bet["bookmaker_odds"] - 1), 2)
        elif new_status == "Loss":
            pnl = -round(bet["kelly_stake"], 2)
        else:
            pnl = 0.0  # Void = επιστροφή χαρτζιλικιού

        now = datetime.now(timezone.utc).isoformat()
        con.execute("""
            UPDATE bets_tracked
            SET status=?, final_home_goals=?, final_away_goals=?,
                profit_loss=?, settled_at=?
            WHERE id=?
        """, (new_status, home_goals, away_goals, pnl, now, bet_id))

        con.execute("""
            INSERT INTO settlements (bet_id, old_status, new_status, home_goals, away_goals, profit_loss)
            VALUES (?,?,?,?,?,?)
        """, (bet_id, "Pending", new_status, home_goals, away_goals, pnl))

    return {"status": new_status, "profit_loss": pnl}


def auto_settle_from_api(sport_key: str = None) -> dict:
    """
    Αυτόματο settlement: τραβάει αποτελέσματα από The Odds API
    και κλείνει όλα τα Pending bets που έχουν τελειώσει.
    """
    from scrapers.odds_api import SPORT_KEYS
    import requests, os

    pending = get_pending_bets()
    if not pending:
        return {"settled": 0, "skipped": 0, "errors": 0}

    # Μάζεψε όλα τα leagues που χρειάζονται settlement
    leagues_needed = {b["league"] for b in pending}
    results_by_teams: dict[tuple, dict] = {}

    API_KEY = os.getenv("ODDS_API_KEY", "")
    BASE    = "https://api.the-odds-api.com/v4"

    for league in leagues_needed:
        sk = SPORT_KEYS.get(league)
        if not sk:
            continue
        try:
            r = requests.get(f"{BASE}/sports/{sk}/scores/",
                params={"apiKey": API_KEY, "daysFrom": 3, "dateFormat": "iso"}, timeout=15)
            if r.status_code != 200:
                continue
            for ev in r.json():
                if not ev.get("completed"):
                    continue
                scores = ev.get("scores") or []
                if len(scores) < 2:
                    continue
                sm = {s["name"]: int(s["score"]) for s in scores}
                h  = ev["home_team"]
                a  = ev["away_team"]
                results_by_teams[(h.lower(), a.lower())] = {
                    "home_goals": sm.get(h, 0),
                    "away_goals": sm.get(a, 0),
                    "home_team":  h,
                    "away_team":  a,
                }
        except Exception as e:
            print(f"[DB] Settlement fetch error ({league}): {e}")

    settled = skipped = errors = 0
    for bet in pending:
        key = (bet["home_team"].lower(), bet["away_team"].lower())
        res = results_by_teams.get(key)
        if not res:
            skipped += 1
            continue
        try:
            outcome = settle_bet(bet["id"], res["home_goals"], res["away_goals"])
            if "error" not in outcome:
                settled += 1
                icon = "W" if outcome["status"] == "Win" else ("L" if outcome["status"] == "Loss" else "V")
                pnl_str = f"+{outcome['profit_loss']:.2f}" if outcome['profit_loss'] >= 0 else f"{outcome['profit_loss']:.2f}"
                print(f"[DB] [{icon}] #{bet['id']} {bet['home_team']} vs {bet['away_team']} — {bet['bet_type']} | PnL: {pnl_str}")
            else:
                errors += 1
        except Exception as e:
            print(f"[DB] settle error bet #{bet['id']}: {e}")
            errors += 1

    return {"settled": settled, "skipped": skipped, "errors": errors}


def manual_settle(bet_id: int, home_goals: int, away_goals: int) -> dict:
    """Χειροκίνητο settlement για έναν συγκεκριμένο αγώνα."""
    return settle_bet(bet_id, home_goals, away_goals)


def void_bet(bet_id: int) -> bool:
    """Ακυρώνει ένα στοίχημα (π.χ. αγώνας δεν παίχτηκε)."""
    with _conn() as con:
        con.execute(
            "UPDATE bets_tracked SET status='Void', profit_loss=0, settled_at=datetime('now') WHERE id=?",
            (bet_id,)
        )
    return True
