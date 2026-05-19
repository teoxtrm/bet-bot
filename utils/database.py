"""
SQLite Database Manager.

Tables:
  bets_tracked     — every tracked bet with probabilities, odds, settlement
  settlements      — settlement audit log
  match_snapshots  — one row per scanned game: Pinnacle probs + actual result
                     This is the primary ML training dataset (grows over time)
  team_form        — cached api-football team form (avoid repeat API calls)
  league_stats     — rolling per-league goal/corner averages (replace hardcoded estimates)
"""

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from contextlib import contextmanager

DB_PATH = Path("data/bet_bot.db")  # default (single-user / legacy)

# ── Schema ────────────────────────────────────────────────────────────────────

SCHEMA = """
CREATE TABLE IF NOT EXISTS bets_tracked (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id         TEXT,
    match_date       TEXT    NOT NULL,
    league           TEXT    NOT NULL,
    home_team        TEXT    NOT NULL,
    away_team        TEXT    NOT NULL,
    bet_type         TEXT    NOT NULL,
    our_probability  REAL    NOT NULL,
    bookmaker        TEXT    NOT NULL,
    bookmaker_odds   REAL    NOT NULL,
    value_edge_pct   REAL    NOT NULL,
    kelly_stake      REAL    NOT NULL,
    is_live          INTEGER NOT NULL DEFAULT 0,
    live_minute      INTEGER,
    status           TEXT    NOT NULL DEFAULT 'Pending',
    final_home_goals INTEGER,
    final_away_goals INTEGER,
    ht_home_goals    INTEGER,
    ht_away_goals    INTEGER,
    corner_count     INTEGER,
    profit_loss      REAL,
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

CREATE TABLE IF NOT EXISTS match_snapshots (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id         TEXT    NOT NULL,
    match_date       TEXT    NOT NULL,
    league           TEXT    NOT NULL,
    sport_key        TEXT    NOT NULL,
    home_team        TEXT    NOT NULL,
    away_team        TEXT    NOT NULL,
    -- Pinnacle no-vig pre-game probabilities
    pin_home_prob    REAL,
    pin_draw_prob    REAL,
    pin_away_prob    REAL,
    pin_over25_prob  REAL,
    pin_under25_prob REAL,
    pin_ht05_prob    REAL,
    pin_ht15_prob    REAL,
    -- League context
    strategy_score   INTEGER,
    -- Actual results (filled at settlement)
    final_home_goals INTEGER,
    final_away_goals INTEGER,
    ht_home_goals    INTEGER,
    ht_away_goals    INTEGER,
    corner_count     INTEGER,
    -- Derived outcome labels (for ML)
    result_1x2       TEXT,    -- "1", "X", or "2"
    result_over25    INTEGER, -- 1=Win, 0=Loss, NULL=unsettled
    result_ht_over05 INTEGER,
    result_ht_over15 INTEGER,
    -- Metadata
    scan_date        TEXT    NOT NULL,
    settled_at       TEXT,
    created_at       TEXT    NOT NULL DEFAULT (datetime('now')),
    UNIQUE(event_id)
);

CREATE TABLE IF NOT EXISTS team_form (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    team_id             INTEGER NOT NULL,
    team_name           TEXT    NOT NULL,
    league_id           INTEGER,
    fetch_date          TEXT    NOT NULL,
    games_analyzed      INTEGER,
    avg_goals_scored    REAL,
    avg_goals_conceded  REAL,
    last_5_json         TEXT,   -- JSON array of last 5 result dicts
    created_at          TEXT    NOT NULL DEFAULT (datetime('now')),
    UNIQUE(team_id, fetch_date)
);

CREATE TABLE IF NOT EXISTS league_stats (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    league          TEXT    NOT NULL,
    season          TEXT    NOT NULL,
    sample_size     INTEGER NOT NULL DEFAULT 0,
    avg_goals       REAL,
    avg_ht_goals    REAL,
    avg_corners     REAL,
    over_25_rate    REAL,
    ht_over_05_rate REAL,
    ht_over_15_rate REAL,
    updated_at      TEXT    NOT NULL DEFAULT (datetime('now')),
    UNIQUE(league, season)
);

CREATE INDEX IF NOT EXISTS idx_bets_status    ON bets_tracked(status);
CREATE INDEX IF NOT EXISTS idx_bets_league    ON bets_tracked(league);
CREATE INDEX IF NOT EXISTS idx_bets_event_id  ON bets_tracked(event_id);
CREATE INDEX IF NOT EXISTS idx_bets_teams     ON bets_tracked(home_team, away_team, match_date);
CREATE INDEX IF NOT EXISTS idx_snaps_event    ON match_snapshots(event_id);
CREATE INDEX IF NOT EXISTS idx_snaps_date     ON match_snapshots(match_date);
CREATE INDEX IF NOT EXISTS idx_snaps_league   ON match_snapshots(league);
CREATE INDEX IF NOT EXISTS idx_form_team      ON team_form(team_id, fetch_date);
CREATE INDEX IF NOT EXISTS idx_lstats_league  ON league_stats(league, season);
"""


# ── Connection ────────────────────────────────────────────────────────────────

@contextmanager
def _conn(db_path=None):
    path = Path(db_path) if db_path else DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(path), timeout=20)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA busy_timeout=20000")
    try:
        yield con
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


def _migrate(con):
    """Add new columns to existing tables without dropping data."""
    # bets_tracked: add HT score and corner columns if missing
    existing = {row[1] for row in con.execute("PRAGMA table_info(bets_tracked)")}
    for col, dtype in [
        ("ht_home_goals", "INTEGER"),
        ("ht_away_goals", "INTEGER"),
        ("corner_count",  "INTEGER"),
    ]:
        if col not in existing:
            con.execute(f"ALTER TABLE bets_tracked ADD COLUMN {col} {dtype}")


def init_db(db_path=None):
    with _conn(db_path) as con:
        con.executescript(SCHEMA)
        _migrate(con)
    path = Path(db_path) if db_path else DB_PATH
    print(f"[DB] Initialized: {path.resolve()}")


# ── Settlement logic ──────────────────────────────────────────────────────────

def _determine_outcome(
    bet_type:       str,
    home_goals:     int,
    away_goals:     int,
    ht_home_goals:  int | None = None,
    ht_away_goals:  int | None = None,
    corner_count:   int | None = None,
) -> str:
    bt    = bet_type.lower().strip()
    total = home_goals + away_goals

    # Corner bets
    if "corner" in bt:
        if corner_count is None:
            return "Void"
        for thr in (8.5, 9.5, 10.5, 11.5, 12.5):
            thr_str = str(thr)
            if f"over {thr_str}" in bt:
                return "Win" if corner_count > thr else "Loss"
            if f"under {thr_str}" in bt:
                return "Win" if corner_count < thr else "Loss"
        return "Void"

    # HT bets — must have HT score; fall through to Void if missing
    if "ht" in bt:
        if ht_home_goals is None or ht_away_goals is None:
            return "Void"
        ht_total = ht_home_goals + ht_away_goals
        if "over 0.5" in bt:
            return "Win" if ht_total > 0 else "Loss"
        if "over 1.5" in bt:
            return "Win" if ht_total > 1 else "Loss"
        if "over 2.5" in bt:
            return "Win" if ht_total > 2 else "Loss"
        if "under 0.5" in bt:
            return "Win" if ht_total < 1 else "Loss"
        if "under 1.5" in bt:
            return "Win" if ht_total < 2 else "Loss"
        return "Void"

    # Full-time bets
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

    return "Void"


# ── Insert / track bets ───────────────────────────────────────────────────────

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
    db_path=None,
) -> int:
    """Insert a bet. Returns row ID, or -1 if duplicate within 4 hours."""
    with _conn(db_path) as con:
        existing = con.execute("""
            SELECT id FROM bets_tracked
            WHERE home_team=? AND away_team=? AND bet_type=? AND bookmaker=?
              AND status='Pending'
              AND datetime(created_at) > datetime('now', '-4 hours')
        """, (home_team, away_team, bet_type, bookmaker)).fetchone()
        if existing:
            return -1

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
                    is_live: bool = False, live_minute: int = None,
                    db_path=None) -> int:
    bet_id = insert_bet(
        event_id        = match_info.get("event_id", ""),
        match_date      = match_info.get("match_date", datetime.now().strftime("%Y-%m-%d")),
        league          = league,
        home_team       = match_info["home_team"],
        away_team       = match_info["away_team"],
        bet_type        = match_info["bet_type"],
        our_probability = value_result["our_probability"],
        bookmaker       = value_result.get("bookmaker", "unknown"),
        bookmaker_odds  = value_result["bookmaker_odds"],
        value_edge_pct  = value_result["value_edge"],
        kelly_stake     = kelly_result["suggested_bet"],
        is_live         = is_live,
        live_minute     = live_minute,
        db_path         = db_path,
    )
    if bet_id > 0:
        print(f"[DB] Tracked bet #{bet_id}: {match_info['home_team']} vs {match_info['away_team']} — {match_info['bet_type']}")
    return bet_id


# ── Queries ───────────────────────────────────────────────────────────────────

def get_pending_bets(db_path=None) -> list[dict]:
    with _conn(db_path) as con:
        rows = con.execute("""
            SELECT * FROM bets_tracked WHERE status='Pending'
            ORDER BY match_date ASC, created_at ASC
        """).fetchall()
    return [dict(r) for r in rows]


def get_all_bets(limit: int = 100, db_path=None) -> list[dict]:
    with _conn(db_path) as con:
        rows = con.execute("""
            SELECT * FROM bets_tracked ORDER BY created_at DESC LIMIT ?
        """, (limit,)).fetchall()
    return [dict(r) for r in rows]


def get_stats(db_path=None) -> dict:
    with _conn(db_path) as con:
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
    d["win_rate"] = (d["wins"] or 0) / settled if settled > 0 else 0.0
    d["roi"]      = ((d["total_pnl"] or 0) / d["total_staked"] * 100) if (d["total_staked"] or 0) > 0 else 0.0
    d["settled"]  = settled
    return d


def get_daily_pnl(db_path=None) -> list[dict]:
    """
    Returns daily and cumulative PnL for settled bets, ordered by match_date.
    Each row: {date, daily_pnl, cumulative_pnl, wins, losses}
    """
    with _conn(db_path) as con:
        rows = con.execute("""
            SELECT
                match_date                             AS date,
                SUM(COALESCE(profit_loss, 0))          AS daily_pnl,
                SUM(CASE WHEN status='Win'  THEN 1 ELSE 0 END) AS wins,
                SUM(CASE WHEN status='Loss' THEN 1 ELSE 0 END) AS losses
            FROM bets_tracked
            WHERE status IN ('Win','Loss')
            GROUP BY match_date
            ORDER BY match_date ASC
        """).fetchall()
    result = []
    cumulative = 0.0
    for r in rows:
        cumulative += r["daily_pnl"]
        result.append({
            "date":           r["date"],
            "daily_pnl":      round(r["daily_pnl"], 2),
            "cumulative_pnl": round(cumulative, 2),
            "wins":           r["wins"],
            "losses":         r["losses"],
        })
    return result


# ── Settlement ────────────────────────────────────────────────────────────────

def settle_bet(
    bet_id:        int,
    home_goals:    int,
    away_goals:    int,
    ht_home_goals: int | None = None,
    ht_away_goals: int | None = None,
    corner_count:  int | None = None,
    db_path=None,
) -> dict:
    with _conn(db_path) as con:
        bet = con.execute("SELECT * FROM bets_tracked WHERE id=?", (bet_id,)).fetchone()
        if not bet:
            return {"error": f"Bet #{bet_id} not found"}
        if bet["status"] != "Pending":
            return {"error": f"Bet #{bet_id} already settled ({bet['status']})"}

        bet = dict(bet)
        new_status = _determine_outcome(
            bet["bet_type"], home_goals, away_goals,
            ht_home_goals, ht_away_goals, corner_count,
        )

        if new_status == "Win":
            pnl = round(bet["kelly_stake"] * (bet["bookmaker_odds"] - 1), 2)
        elif new_status == "Loss":
            pnl = -round(bet["kelly_stake"], 2)
        else:
            pnl = 0.0

        now = datetime.now(timezone.utc).isoformat()
        con.execute("""
            UPDATE bets_tracked
            SET status=?, final_home_goals=?, final_away_goals=?,
                ht_home_goals=?, ht_away_goals=?, corner_count=?,
                profit_loss=?, settled_at=?
            WHERE id=?
        """, (new_status, home_goals, away_goals,
              ht_home_goals, ht_away_goals, corner_count,
              pnl, now, bet_id))

        con.execute("""
            INSERT INTO settlements (bet_id, old_status, new_status, home_goals, away_goals, profit_loss)
            VALUES (?,?,?,?,?,?)
        """, (bet_id, "Pending", new_status, home_goals, away_goals, pnl))

    return {"status": new_status, "profit_loss": pnl}


def auto_settle_from_api(sport_key: str = None, db_path=None, api_key: str = None) -> dict:
    """Fetch completed scores from Odds API and settle matching pending bets."""
    from scrapers.odds_api import SPORT_KEYS
    import requests, os

    pending = get_pending_bets(db_path=db_path)
    if not pending:
        return {"settled": 0, "skipped": 0, "errors": 0}

    leagues_needed = {b["league"] for b in pending}
    results_by_teams: dict[tuple, dict] = {}

    API_KEY = api_key or os.getenv("ODDS_API_KEY", "")
    BASE    = "https://api.the-odds-api.com/v4"

    for league in leagues_needed:
        sk = SPORT_KEYS.get(league)
        if not sk:
            continue
        try:
            r = requests.get(
                f"{BASE}/sports/{sk}/scores/",
                params={"apiKey": API_KEY, "daysFrom": 3, "dateFormat": "iso"},
                timeout=15,
            )
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
                    "event_id":   ev.get("id", ""),
                }
        except Exception as e:
            print(f"[DB] Settlement fetch error ({league}): {e}")

    settled = skipped = errors = 0
    for bet in pending:
        # HT and corner bets need extra data — must be settled manually
        bt = bet["bet_type"].lower()
        if "ht" in bt or "corner" in bt:
            skipped += 1
            continue
        key = (bet["home_team"].lower(), bet["away_team"].lower())
        res = results_by_teams.get(key)
        if not res:
            skipped += 1
            continue
        try:
            outcome = settle_bet(bet["id"], res["home_goals"], res["away_goals"], db_path=db_path)
            if "error" not in outcome:
                settled += 1
                icon    = "W" if outcome["status"] == "Win" else ("L" if outcome["status"] == "Loss" else "V")
                pnl_str = f"+{outcome['profit_loss']:.2f}" if outcome["profit_loss"] >= 0 else f"{outcome['profit_loss']:.2f}"
                print(f"[DB] [{icon}] #{bet['id']} {bet['home_team']} vs {bet['away_team']} — {bet['bet_type']} | {pnl_str}")
                # Update snapshot result while we have the scores
                eid = bet.get("event_id") or res.get("event_id", "")
                if eid:
                    update_snapshot_result(eid, res["home_goals"], res["away_goals"], db_path=db_path)
            else:
                errors += 1
        except Exception as e:
            print(f"[DB] settle error bet #{bet['id']}: {e}")
            errors += 1

    return {"settled": settled, "skipped": skipped, "errors": errors}


def manual_settle(bet_id: int, home_goals: int, away_goals: int) -> dict:
    return settle_bet(bet_id, home_goals, away_goals)


def void_bet(bet_id: int, db_path=None) -> bool:
    with _conn(db_path) as con:
        con.execute(
            "UPDATE bets_tracked SET status='Void', profit_loss=0, settled_at=datetime('now') WHERE id=?",
            (bet_id,)
        )
    return True


# ── Match snapshots (ML training data) ───────────────────────────────────────

def save_match_snapshot(
    event_id:        str,
    match_date:      str,
    league:          str,
    sport_key:       str,
    home_team:       str,
    away_team:       str,
    scan_date:       str,
    strategy_score:  int   = 6,
    pin_home_prob:   float = None,
    pin_draw_prob:   float = None,
    pin_away_prob:   float = None,
    pin_over25_prob: float = None,
    pin_under25_prob:float = None,
    pin_ht05_prob:   float = None,
    pin_ht15_prob:   float = None,
    db_path=None,
) -> int:
    """
    Save or refresh the pre-game probability snapshot for a match.
    One row per event_id (UPSERT). Returns row ID or -1 if event_id is empty.
    """
    if not event_id:
        return -1
    with _conn(db_path) as con:
        cur = con.execute("""
            INSERT INTO match_snapshots
              (event_id, match_date, league, sport_key, home_team, away_team,
               scan_date, strategy_score,
               pin_home_prob, pin_draw_prob, pin_away_prob,
               pin_over25_prob, pin_under25_prob, pin_ht05_prob, pin_ht15_prob)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(event_id) DO UPDATE SET
              scan_date        = excluded.scan_date,
              pin_home_prob    = excluded.pin_home_prob,
              pin_draw_prob    = excluded.pin_draw_prob,
              pin_away_prob    = excluded.pin_away_prob,
              pin_over25_prob  = excluded.pin_over25_prob,
              pin_under25_prob = excluded.pin_under25_prob,
              pin_ht05_prob    = excluded.pin_ht05_prob,
              pin_ht15_prob    = excluded.pin_ht15_prob,
              strategy_score   = excluded.strategy_score
        """, (
            event_id, match_date, league, sport_key, home_team, away_team,
            scan_date, strategy_score,
            pin_home_prob, pin_draw_prob, pin_away_prob,
            pin_over25_prob, pin_under25_prob, pin_ht05_prob, pin_ht15_prob,
        ))
        return cur.lastrowid


def get_event_prev_probs(event_id: str, db_path=None) -> dict | None:
    """Return stored Pinnacle probs for an event (for steam detection). None if not found."""
    if not event_id:
        return None
    with _conn(db_path) as con:
        row = con.execute("""
            SELECT pin_home_prob, pin_draw_prob, pin_away_prob,
                   pin_over25_prob, pin_ht05_prob, pin_ht15_prob
            FROM match_snapshots WHERE event_id = ?
        """, (event_id,)).fetchone()
    if not row:
        return None
    return {
        "pin_home_prob":   row[0],
        "pin_draw_prob":   row[1],
        "pin_away_prob":   row[2],
        "pin_over25_prob": row[3],
        "pin_ht05_prob":   row[4],
        "pin_ht15_prob":   row[5],
    }


def get_today_snapshot_probs(db_path=None) -> dict:
    """
    Return all today's snapshots as {event_id: {pin_*_prob fields}}.
    Used by live scanner to compare live Pinnacle lines against pre-game baseline.
    """
    from datetime import date
    today = date.today().isoformat()
    with _conn(db_path) as con:
        rows = con.execute("""
            SELECT event_id, pin_home_prob, pin_draw_prob, pin_away_prob,
                   pin_over25_prob, pin_ht05_prob, pin_ht15_prob
            FROM match_snapshots WHERE scan_date = ?
        """, (today,)).fetchall()
    result = {}
    for row in rows:
        result[row[0]] = {
            "pin_home_prob":   row[1],
            "pin_draw_prob":   row[2],
            "pin_away_prob":   row[3],
            "pin_over25_prob": row[4],
            "pin_ht05_prob":   row[5],
            "pin_ht15_prob":   row[6],
        }
    return result


def update_snapshot_result(
    event_id:        str,
    final_home_goals: int,
    final_away_goals: int,
    ht_home_goals:   int | None = None,
    ht_away_goals:   int | None = None,
    corner_count:    int | None = None,
    db_path=None,
):
    """Fill in actual results and compute outcome labels for ML."""
    if not event_id:
        return
    total    = final_home_goals + final_away_goals
    ht_total = (ht_home_goals or 0) + (ht_away_goals or 0)
    result_1x2 = ("1" if final_home_goals > final_away_goals
                  else ("2" if final_away_goals > final_home_goals else "X"))
    result_over25    = int(total > 2)
    result_ht_over05 = int(ht_total > 0) if ht_home_goals is not None else None
    result_ht_over15 = int(ht_total > 1) if ht_home_goals is not None else None

    with _conn(db_path) as con:
        con.execute("""
            UPDATE match_snapshots SET
              final_home_goals = ?,
              final_away_goals = ?,
              ht_home_goals    = COALESCE(?, ht_home_goals),
              ht_away_goals    = COALESCE(?, ht_away_goals),
              corner_count     = COALESCE(?, corner_count),
              result_1x2       = ?,
              result_over25    = ?,
              result_ht_over05 = COALESCE(?, result_ht_over05),
              result_ht_over15 = COALESCE(?, result_ht_over15),
              settled_at       = datetime('now')
            WHERE event_id = ?
        """, (
            final_home_goals, final_away_goals,
            ht_home_goals, ht_away_goals, corner_count,
            result_1x2, result_over25,
            result_ht_over05, result_ht_over15,
            event_id,
        ))


def get_snapshot_stats(db_path=None) -> dict:
    """Return high-level ML dataset stats."""
    with _conn(db_path) as con:
        row = con.execute("""
            SELECT
                COUNT(*)                                        AS total,
                SUM(CASE WHEN settled_at IS NOT NULL THEN 1 END) AS settled,
                SUM(result_over25)                              AS over25_wins,
                SUM(CASE WHEN result_over25 = 0 THEN 1 END)    AS over25_losses,
                SUM(result_ht_over05)                           AS ht05_wins,
                AVG(pin_over25_prob)                            AS avg_pin_over25
            FROM match_snapshots
        """).fetchone()
    return dict(row)


# ── Team form cache ───────────────────────────────────────────────────────────

def upsert_team_form(
    team_id:           int,
    team_name:         str,
    avg_goals_scored:  float,
    avg_goals_conceded: float,
    games_analyzed:    int,
    league_id:         int   = None,
    last_5_results:    list  = None,
    db_path=None,
):
    """Cache api-football team form. Keyed by (team_id, today's date)."""
    from datetime import date
    fetch_date = date.today().isoformat()
    with _conn(db_path) as con:
        con.execute("""
            INSERT INTO team_form
              (team_id, team_name, league_id, fetch_date,
               games_analyzed, avg_goals_scored, avg_goals_conceded, last_5_json)
            VALUES (?,?,?,?,?,?,?,?)
            ON CONFLICT(team_id, fetch_date) DO UPDATE SET
              avg_goals_scored   = excluded.avg_goals_scored,
              avg_goals_conceded = excluded.avg_goals_conceded,
              games_analyzed     = excluded.games_analyzed,
              last_5_json        = excluded.last_5_json
        """, (
            team_id, team_name, league_id, fetch_date,
            games_analyzed, avg_goals_scored, avg_goals_conceded,
            json.dumps(last_5_results or []),
        ))


def get_team_form_cached(team_id: int, max_age_hours: int = 24, db_path=None) -> dict | None:
    """Return cached form if fresh, else None (caller should fetch from API)."""
    with _conn(db_path) as con:
        row = con.execute("""
            SELECT * FROM team_form
            WHERE team_id = ?
              AND datetime(fetch_date) >= datetime('now', ? || ' hours')
            ORDER BY fetch_date DESC LIMIT 1
        """, (team_id, f"-{max_age_hours}")).fetchone()
    if not row:
        return None
    d = dict(row)
    try:
        d["last_5_results"] = json.loads(d.pop("last_5_json") or "[]")
    except Exception:
        d["last_5_results"] = []
    return d


# ── League stats ──────────────────────────────────────────────────────────────

def upsert_league_stats(league: str, season: str, stats: dict, db_path=None):
    """
    Update rolling league averages from accumulated snapshot data.
    stats keys: avg_goals, avg_ht_goals, avg_corners, over_25_rate,
                ht_over_05_rate, ht_over_15_rate, sample_size
    """
    with _conn(db_path) as con:
        con.execute("""
            INSERT INTO league_stats
              (league, season, sample_size, avg_goals, avg_ht_goals, avg_corners,
               over_25_rate, ht_over_05_rate, ht_over_15_rate, updated_at)
            VALUES (?,?,?,?,?,?,?,?,?,datetime('now'))
            ON CONFLICT(league, season) DO UPDATE SET
              sample_size     = excluded.sample_size,
              avg_goals       = excluded.avg_goals,
              avg_ht_goals    = excluded.avg_ht_goals,
              avg_corners     = excluded.avg_corners,
              over_25_rate    = excluded.over_25_rate,
              ht_over_05_rate = excluded.ht_over_05_rate,
              ht_over_15_rate = excluded.ht_over_15_rate,
              updated_at      = excluded.updated_at
        """, (
            league, season,
            stats.get("sample_size", 0),
            stats.get("avg_goals"),
            stats.get("avg_ht_goals"),
            stats.get("avg_corners"),
            stats.get("over_25_rate"),
            stats.get("ht_over_05_rate"),
            stats.get("ht_over_15_rate"),
        ))


def get_league_stats(league: str, db_path=None) -> dict | None:
    """Return most recent season stats for a league, or None if no data yet."""
    with _conn(db_path) as con:
        row = con.execute("""
            SELECT * FROM league_stats
            WHERE league = ?
            ORDER BY updated_at DESC LIMIT 1
        """, (league,)).fetchone()
    return dict(row) if row else None


def compute_and_save_league_stats(league: str, db_path=None):
    """
    Compute rolling averages from settled match_snapshots and save to league_stats.
    Called periodically (e.g. after each auto-settle batch).
    Requires at least 10 settled games before writing.
    """
    from datetime import date
    season = _current_season()
    with _conn(db_path) as con:
        row = con.execute("""
            SELECT
                COUNT(*)                              AS n,
                AVG(final_home_goals + final_away_goals)             AS avg_goals,
                AVG(COALESCE(ht_home_goals,0) + COALESCE(ht_away_goals,0)) AS avg_ht_goals,
                AVG(corner_count)                     AS avg_corners,
                AVG(CAST(result_over25 AS REAL))      AS over_25_rate,
                AVG(CAST(result_ht_over05 AS REAL))   AS ht_over_05_rate,
                AVG(CAST(result_ht_over15 AS REAL))   AS ht_over_15_rate
            FROM match_snapshots
            WHERE league = ? AND settled_at IS NOT NULL
        """, (league,)).fetchone()
    if not row or (row["n"] or 0) < 10:
        return
    upsert_league_stats(league, season, {
        "sample_size":     row["n"],
        "avg_goals":       row["avg_goals"],
        "avg_ht_goals":    row["avg_ht_goals"],
        "avg_corners":     row["avg_corners"],
        "over_25_rate":    row["over_25_rate"],
        "ht_over_05_rate": row["ht_over_05_rate"],
        "ht_over_15_rate": row["ht_over_15_rate"],
    }, db_path=db_path)
    print(f"[DB] League stats updated: {league} ({row['n']} games)")


def _current_season() -> str:
    """Return current season string e.g. '2025-26'."""
    from datetime import date
    y = date.today().year
    m = date.today().month
    start = y if m >= 7 else y - 1
    return f"{start}-{str(start + 1)[-2:]}"
