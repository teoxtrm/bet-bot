"""
BetBot Web API — FastAPI multi-user backend
Run: uvicorn api:app --host 0.0.0.0 --port 8000
"""

import asyncio
import hashlib
import hmac
import json
import os
import pathlib
import sys
import threading
import time
from datetime import date, datetime
from typing import Optional

from dotenv import load_dotenv, dotenv_values
from fastapi import (BackgroundTasks, Cookie, Depends, FastAPI,
                     Form, HTTPException, Request, WebSocket, WebSocketDisconnect)
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

# ── Path setup ────────────────────────────────────────────────────────────────
BASE_DIR = pathlib.Path(__file__).parent
sys.path.insert(0, str(BASE_DIR))
load_dotenv(BASE_DIR / ".env")

from utils.database import (auto_settle_from_api, get_all_bets, get_pending_bets,
                              get_stats, init_db, settle_bet, track_value_bet)
from utils.scan_cache import (clear_league_cache, load_league_scan, load_scan,
                               save_league_scan, save_scan)

# ── App setup ─────────────────────────────────────────────────────────────────
app = FastAPI(title="BetBot", docs_url=None, redoc_url=None)
WEB_DIR = BASE_DIR / "web"
app.mount("/static", StaticFiles(directory=str(WEB_DIR / "static")), name="static")
templates = Jinja2Templates(directory=str(WEB_DIR / "templates"))

# ── User management ───────────────────────────────────────────────────────────
USERS_FILE   = BASE_DIR / "data" / "users.json"
SECRET_KEY   = os.getenv("SECRET_KEY", hashlib.sha256(os.urandom(32)).hexdigest())
COOKIE_NAME  = "bb_session"


def _load_users() -> dict:
    try:
        return json.loads(USERS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_users(users: dict):
    USERS_FILE.parent.mkdir(parents=True, exist_ok=True)
    USERS_FILE.write_text(json.dumps(users, indent=2, ensure_ascii=False), encoding="utf-8")


def _hash_password(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()


def _make_token(username: str, pw_hash: str) -> str:
    return f"{username}:{hmac.new(SECRET_KEY.encode(), f'{username}:{pw_hash}'.encode(), 'sha256').hexdigest()}"


def _verify_token(token: str) -> Optional[str]:
    """Returns username if token is valid, else None."""
    try:
        username, sig = token.split(":", 1)
        users = _load_users()
        if username not in users:
            return None
        expected = hmac.new(SECRET_KEY.encode(),
                             f'{username}:{users[username]["password_hash"]}'.encode(),
                             "sha256").hexdigest()
        if hmac.compare_digest(sig, expected):
            return username
    except Exception:
        pass
    return None


def get_current_user(request: Request, bb_session: str = Cookie(default="")) -> str:
    username = _verify_token(bb_session)
    if not username:
        raise HTTPException(status_code=302,
                            headers={"Location": f"/login?next={request.url.path}"})
    return username


def get_current_user_api(bb_session: str = Cookie(default="")) -> str:
    username = _verify_token(bb_session)
    if not username:
        raise HTTPException(status_code=401, detail="Unauthorized")
    return username


def user_dir(username: str) -> pathlib.Path:
    """Per-user data directory."""
    d = BASE_DIR / "data" / "users" / username
    d.mkdir(parents=True, exist_ok=True)
    return d


def user_db(username: str) -> pathlib.Path:
    return user_dir(username) / "bet_bot.db"


def user_env(username: str) -> dict:
    """Load user's API keys from their .env file."""
    env_file = user_dir(username) / ".env"
    if env_file.exists():
        return dotenv_values(str(env_file))
    return {}


def user_has_keys(username: str) -> bool:
    env = user_env(username)
    return bool(env.get("ODDS_API_KEY"))


# ── Per-user in-memory state ──────────────────────────────────────────────────
_live_results:  dict = {}   # username → list
_scan_status:   dict = {}   # username → dict
_live_status:   dict = {}   # username → dict
_pregame_cache: dict = {}   # username → dict
_ws_clients:    dict = {}   # username → list[WebSocket]
_ws_lock        = asyncio.Lock()
_state_lock     = threading.Lock()


def _user_live(username: str) -> list:
    return _live_results.setdefault(username, [])


def _user_scan_status(username: str) -> dict:
    return _scan_status.setdefault(username,
           {"running": False, "text": "", "progress": 0.0})


def _user_live_status(username: str) -> dict:
    return _live_status.setdefault(username,
           {"running": False, "interval": 120, "mode": "auto",
            "sport_key": "", "max_tier": 2, "iteration": 0})


def _user_pregame(username: str) -> dict:
    return _pregame_cache.setdefault(username, {})


# ── WebSocket helpers ─────────────────────────────────────────────────────────
async def _broadcast(username: str, payload: dict):
    msg = json.dumps(payload, ensure_ascii=False, default=str)
    dead = []
    async with _ws_lock:
        clients = _ws_clients.get(username, [])
        for ws in list(clients):
            try:
                await ws.send_text(msg)
            except Exception:
                dead.append(ws)
        for ws in dead:
            try:
                clients.remove(ws)
            except ValueError:
                pass


def _broadcast_sync(username: str, payload: dict):
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            asyncio.run_coroutine_threadsafe(_broadcast(username, payload), loop)
    except Exception:
        pass


# ── Startup ───────────────────────────────────────────────────────────────────
@app.on_event("startup")
async def startup():
    (BASE_DIR / "data").mkdir(exist_ok=True)
    # Create default admin if no users exist
    users = _load_users()
    if not users:
        admin_pw = os.getenv("APP_PASSWORD", "betbot2024")
        users["admin"] = {
            "password_hash": _hash_password(admin_pw),
            "is_admin": True,
            "created_at": datetime.now().isoformat(),
        }
        _save_users(users)
        print(f"[API] Created default admin user")


# ══════════════════════════════════════════════════════════════════════════════
#  AUTH PAGES
# ══════════════════════════════════════════════════════════════════════════════

@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, next: str = "/pregame", error: str = ""):
    return templates.TemplateResponse(request=request, name="login.html",
                                       context={"next": next, "error": error})


@app.post("/login")
async def login_submit(username: str = Form(...), password: str = Form(...),
                        next: str = Form(default="/pregame")):
    users = _load_users()
    user  = users.get(username)
    if user and user["password_hash"] == _hash_password(password):
        token = _make_token(username, user["password_hash"])
        resp  = RedirectResponse(next if next.startswith("/") else "/pregame",
                                  status_code=303)
        resp.set_cookie(COOKIE_NAME, token,
                        httponly=True, samesite="lax", max_age=60*60*24*30)
        return resp
    return RedirectResponse(f"/login?error=1&next={next}", status_code=303)


@app.get("/logout")
async def logout():
    resp = RedirectResponse("/login", status_code=303)
    resp.delete_cookie(COOKIE_NAME)
    return resp


# ── Pages ─────────────────────────────────────────────────────────────────────
@app.get("/", response_class=HTMLResponse)
async def root():
    return RedirectResponse("/pregame")


@app.get("/pregame", response_class=HTMLResponse)
async def page_pregame(request: Request, username=Depends(get_current_user)):
    if not user_has_keys(username):
        return RedirectResponse("/settings?first=1")
    return templates.TemplateResponse(request=request, name="pregame.html",
                                       context={"username": username})


@app.get("/live", response_class=HTMLResponse)
async def page_live(request: Request, username=Depends(get_current_user)):
    if not user_has_keys(username):
        return RedirectResponse("/settings?first=1")
    return templates.TemplateResponse(request=request, name="live.html",
                                       context={"username": username})


@app.get("/tipster", response_class=HTMLResponse)
async def page_tipster(request: Request, username=Depends(get_current_user)):
    return templates.TemplateResponse(request=request, name="tipster.html",
                                       context={"username": username})


@app.get("/history", response_class=HTMLResponse)
async def page_history(request: Request, username=Depends(get_current_user)):
    return templates.TemplateResponse(request=request, name="history.html",
                                       context={"username": username})


@app.get("/settings", response_class=HTMLResponse)
async def page_settings(request: Request, username=Depends(get_current_user),
                         first: str = ""):
    env = user_env(username)
    return templates.TemplateResponse(request=request, name="settings.html",
                                       context={"username": username,
                                                "env": env, "first": first})


@app.post("/settings")
async def save_settings(
    username=Depends(get_current_user),
    odds_api_key:      str = Form(default=""),
    api_football_key:  str = Form(default=""),
    football_data_key: str = Form(default=""),
    bankroll:          str = Form(default="1000"),
):
    env_path = user_dir(username) / ".env"
    lines = [
        f"ODDS_API_KEY={odds_api_key.strip()}",
        f"API_FOOTBALL_KEY={api_football_key.strip()}",
        f"FOOTBALL_DATA_KEY={football_data_key.strip()}",
        f"BANKROLL={bankroll.strip()}",
    ]
    env_path.write_text("\n".join(lines), encoding="utf-8")
    return RedirectResponse("/pregame", status_code=303)


# ── Admin ─────────────────────────────────────────────────────────────────────
@app.get("/admin", response_class=HTMLResponse)
async def admin_page(request: Request, username=Depends(get_current_user)):
    users = _load_users()
    if not users.get(username, {}).get("is_admin"):
        raise HTTPException(status_code=403, detail="Forbidden")
    return templates.TemplateResponse(request=request, name="admin.html",
                                       context={"username": username, "users": users})


@app.post("/admin/create-user")
async def create_user(username=Depends(get_current_user),
                       new_username: str = Form(...),
                       new_password: str = Form(...)):
    users = _load_users()
    if not users.get(username, {}).get("is_admin"):
        raise HTTPException(status_code=403)
    if new_username in users:
        raise HTTPException(status_code=400, detail="User already exists")
    users[new_username] = {
        "password_hash": _hash_password(new_password),
        "is_admin": False,
        "created_at": datetime.now().isoformat(),
    }
    _save_users(users)
    return RedirectResponse("/admin", status_code=303)


@app.post("/admin/delete-user")
async def delete_user(username=Depends(get_current_user),
                       target: str = Form(...)):
    users = _load_users()
    if not users.get(username, {}).get("is_admin"):
        raise HTTPException(status_code=403)
    if target == username:
        raise HTTPException(status_code=400, detail="Cannot delete yourself")
    users.pop(target, None)
    _save_users(users)
    return RedirectResponse("/admin", status_code=303)


# ── WebSocket ─────────────────────────────────────────────────────────────────
@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket, bb_session: str = Cookie(default="")):
    username = _verify_token(bb_session)
    if not username:
        await ws.close(code=4001)
        return
    await ws.accept()
    async with _ws_lock:
        _ws_clients.setdefault(username, []).append(ws)
    try:
        current = list(_user_live(username))
        if current:
            await ws.send_text(json.dumps(
                {"type": "live_update", "data": current,
                 "iteration": _user_live_status(username)["iteration"]},
                ensure_ascii=False, default=str,
            ))
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        async with _ws_lock:
            try:
                _ws_clients.get(username, []).remove(ws)
            except ValueError:
                pass


# ══════════════════════════════════════════════════════════════════════════════
#  PRE-GAME SCAN
# ══════════════════════════════════════════════════════════════════════════════

class ScanRequest(BaseModel):
    league:      str  = "TIER 1 ONLY"
    clear_cache: bool = False


@app.post("/api/scan/start")
async def start_pregame_scan(req: ScanRequest, background_tasks: BackgroundTasks,
                              username=Depends(get_current_user_api)):
    if _user_scan_status(username)["running"]:
        raise HTTPException(status_code=409, detail="Scan already running")
    udir = str(user_dir(username))
    if req.clear_cache:
        clear_league_cache(udir)
    background_tasks.add_task(_run_pregame_scan, username, req.league)
    return {"status": "started"}


@app.get("/api/scan/status")
async def scan_status(username=Depends(get_current_user_api)):
    return dict(_user_scan_status(username))


@app.get("/api/scan/results")
async def scan_results(username=Depends(get_current_user_api)):
    return {k: v for k, v in _user_pregame(username).items() if k != "_value_rows"}


@app.get("/api/leagues")
async def get_leagues(username=Depends(get_current_user_api)):
    from scrapers.odds_api import SPORT_KEYS
    options = ["ALL LEAGUES", "TIER 1 ONLY", "TIER 2 ONLY", "TIER 3 ONLY"]
    options += list(SPORT_KEYS.keys())
    return {"leagues": options}


def _run_pregame_scan(username: str, league_key: str):
    udir     = str(user_dir(username))
    db_path  = str(user_db(username))
    env      = user_env(username)
    status   = _user_scan_status(username)

    # Init user's DB
    init_db(db_path)

    status["running"]  = True
    status["text"]     = "Starting scan..."
    status["progress"] = 0.0
    _broadcast_sync(username, {"type": "scan_status", "data": dict(status)})

    # Inject user's API keys into environment for this thread
    for k, v in env.items():
        os.environ.setdefault(k, v)
    # Override with user's keys
    for k, v in env.items():
        os.environ[k] = v

    try:
        from scrapers.odds_api import (SPORT_KEYS, get_event_count_today, get_odds,
                                        get_pinnacle_no_vig_ht_totals,
                                        get_pinnacle_no_vig_probs,
                                        get_pinnacle_no_vig_totals)
        from models.live_targets import LiveTarget, classify, score_targets
        from models.value_calculator import compare_bookmakers, kelly_criterion
        from utils.league_map import ODDS_KEY_TO_LEAGUE as OKL

        bankroll  = float(env.get("BANKROLL", "1000"))
        markets   = ["h2h", "totals", "totals_h1"]
        today_str = date.today().isoformat()

        _TIER_OPTS  = {"ALL LEAGUES", "TIER 1 ONLY", "TIER 2 ONLY", "TIER 3 ONLY"}
        scan_all    = league_key in _TIER_OPTS
        tier_filter = {"TIER 1 ONLY": 1, "TIER 2 ONLY": 2, "TIER 3 ONLY": 3}.get(league_key)

        rows, value_rows, all_targets, events_data = [], [], [], []

        def _process_league(lkey, sport_key):
            _rows, _vrows, _tgts, _evdata = [], [], [], []
            try:
                events = get_odds(sport_key, markets=markets)
            except Exception:
                return _rows, _vrows, _tgts, _evdata
            events = [e for e in events if e.get("commence", "")[:10] == today_str]
            for ev in events:
                p_1x2  = get_pinnacle_no_vig_probs(ev)
                p_ou   = get_pinnacle_no_vig_totals(ev, 2.5)
                p_ht   = get_pinnacle_no_vig_ht_totals(ev, 0.5)
                p_ht15 = get_pinnacle_no_vig_ht_totals(ev, 1.5)
                _tier  = OKL.get(sport_key, {}).get("tier", 2)
                _evdata.append({"event": ev, "p_1x2": p_1x2, "p_ou": p_ou,
                                 "p_ht": p_ht, "p_ht15": p_ht15,
                                 "league": lkey, "tier": _tier})
                checks = []
                if p_ou:
                    pt = str(p_ou["point"]).replace(".", "_")
                    checks += [("Over 2.5",  p_ou["over_prob"],  "totals", "over",  pt),
                               ("Under 2.5", p_ou["under_prob"], "totals", "under", pt)]
                if p_1x2:
                    checks += [("Home Win", p_1x2["home"], "1x2", "home", None),
                               ("Draw",     p_1x2["draw"], "1x2", "draw", None),
                               ("Away Win", p_1x2["away"], "1x2", "away", None)]
                if p_ht:
                    pt_ht = str(p_ht["point"]).replace(".", "_")
                    checks += [("Over 0.5 HT",  p_ht["over_prob"],  "totals_h1", "over",  pt_ht),
                               ("Under 0.5 HT", p_ht["under_prob"], "totals_h1", "under", pt_ht)]
                if p_ht15:
                    pt15 = str(p_ht15["point"]).replace(".", "_")
                    checks += [("Over 1.5 HT",  p_ht15["over_prob"],  "totals_h1", "over",  pt15),
                               ("Under 1.5 HT", p_ht15["under_prob"], "totals_h1", "under", pt15)]
                has_value_ev = False
                best_over = best_home = best_away = best_btts = best_ht = None
                for mkt, prob, mkt_key, side, pt in checks:
                    bm_odds = {}
                    for bm, bd in ev.get("odds", {}).items():
                        if bm == "pinnacle":
                            continue
                        if mkt_key in ("totals", "totals_h1"):
                            o = bd.get(mkt_key, {}).get(f"{side}_{pt}")
                        else:
                            o = (bd.get("1x2") or {}).get(side)
                        if o:
                            bm_odds[bm] = o
                    if not bm_odds:
                        continue
                    comps = compare_bookmakers(prob, bm_odds)
                    best  = comps[0]
                    kelly = kelly_criterion(prob, best["bookmaker_odds"], bankroll)
                    row   = {
                        "league": lkey, "match": f"{ev['home_team']} vs {ev['away_team']}",
                        "date": ev["commence"][:10], "market": mkt, "prob": prob,
                        "bookmaker": best["bookmaker"], "odds": best["bookmaker_odds"],
                        "edge": best["value_edge"], "kelly": kelly["suggested_bet"],
                        "is_value": best["is_value_bet"],
                        "home_team": ev["home_team"], "away_team": ev["away_team"],
                        "event_id": ev.get("id", ""),
                        "value_result": best, "kelly_result": kelly,
                    }
                    _rows.append(row)
                    if best["is_value_bet"]:
                        _vrows.append(row)
                        has_value_ev = True
                    best_mkt = max(bm_odds.values())
                    if   mkt_key == "totals"    and side == "over":                   best_over = best_mkt
                    elif mkt_key == "1x2"       and side == "home":                   best_home = best_mkt
                    elif mkt_key == "1x2"       and side == "away":                   best_away = best_mkt
                    elif mkt_key == "totals_h1" and side == "over" and pt == "0_5":   best_ht   = best_mkt
                for bm, bd in ev.get("odds", {}).items():
                    if bm == "pinnacle":
                        continue
                    b = (bd.get("btts") or {}).get("yes")
                    if b and (best_btts is None or b > best_btts):
                        best_btts = b
                _tgts.extend(classify(ev, p_1x2, p_ou,
                    best_over_odds=best_over, best_home_odds=best_home,
                    best_away_odds=best_away, best_btts_odds=best_btts,
                    best_ht_odds=best_ht, p_ht_ou=p_ht, has_value_bet=has_value_ev))
            return _rows, _vrows, _tgts, _evdata

        if tier_filter is not None:
            items = [(lk, sk) for lk, sk in SPORT_KEYS.items()
                     if OKL.get(sk, {}).get("tier", 2) == tier_filter]
        elif scan_all:
            items = list(SPORT_KEYS.items())
        else:
            items = [(league_key, SPORT_KEYS.get(league_key, "soccer_epl"))]

        if scan_all:
            status["text"] = "Checking which leagues play today..."
            _broadcast_sync(username, {"type": "scan_status", "data": dict(status)})
            items = [(lk, sk) for lk, sk in items if get_event_count_today(sk) > 0]

        total = len(items)
        for idx, (lkey, sport_key) in enumerate(items):
            status["text"]     = f"[{idx+1}/{total}] {lkey.replace('_',' ').title()}..."
            status["progress"] = idx / total if total else 0
            _broadcast_sync(username, {"type": "scan_status", "data": dict(status)})

            cached = load_league_scan(sport_key, udir)
            if cached:
                rows.extend(cached["rows"])
                value_rows.extend([r for r in cached["rows"] if r.get("is_value")])
                all_targets.extend([LiveTarget(**t) for t in cached.get("targets", [])])
                events_data.extend(cached.get("events_data", []))
                continue

            r, vr, t, evd = _process_league(lkey, sport_key)
            rows.extend(r); value_rows.extend(vr)
            all_targets.extend(t); events_data.extend(evd)
            save_league_scan(sport_key, r, evd, t, udir)
            if scan_all and idx < total - 1:
                time.sleep(1)

        import dataclasses
        all_targets   = score_targets(all_targets)
        tipster_picks = []
        watchlist     = []
        if events_data:
            try:
                from models.tipster import generate_picks
                tipster_picks = generate_picks(events_data)
            except Exception as e:
                print(f"[API] tipster error: {e}")
            try:
                from models.watchlist import generate_watchlist
                watchlist = generate_watchlist(events_data)
            except Exception as e:
                print(f"[API] watchlist error: {e}")

        rows.sort(key=lambda x: (not x["is_value"], -x["edge"]))
        cache = {
            "scan_date":     today_str,
            "saved_at":      datetime.now().isoformat(),
            "rows":          [{k: v for k, v in r.items()
                               if k not in ("value_result","kelly_result")} for r in rows],
            "value_count":   len(value_rows),
            "targets":       [dataclasses.asdict(t) for t in all_targets],
            "tipster_picks": [dataclasses.asdict(p) for p in tipster_picks],
            "watchlist":     [dataclasses.asdict(g) for g in watchlist],
            "_value_rows":   value_rows,
        }
        _pregame_cache[username] = cache
        save_scan(rows, all_targets, tipster_picks, watchlist, udir)

        status["running"]  = False
        status["text"]     = f"✓ {len(value_rows)} value bets | {len(rows)} markets"
        status["progress"] = 1.0
        _broadcast_sync(username, {
            "type": "scan_done", "data": dict(status),
            "results": {k: v for k, v in cache.items() if k != "_value_rows"},
        })

    except Exception as e:
        import traceback; traceback.print_exc()
        status["running"] = False
        status["text"]    = f"Error: {e}"
        _broadcast_sync(username, {"type": "scan_error", "error": str(e)})


@app.post("/api/scan/track")
async def track_bets(username=Depends(get_current_user_api)):
    value_rows = _user_pregame(username).get("_value_rows", [])
    if not value_rows:
        raise HTTPException(status_code=400, detail="No value bets to track")
    db_path = str(user_db(username))
    tracked = 0
    for r in value_rows:
        vr = r.get("value_result") or {
            "our_probability": r["prob"], "bookmaker": r["bookmaker"],
            "bookmaker_odds": r["odds"], "value_edge": r["edge"],
        }
        kr = r.get("kelly_result") or {"suggested_bet": r["kelly"]}
        bid = track_value_bet(
            value_result=vr, kelly_result=kr,
            match_info={"event_id": r.get("event_id",""), "match_date": r["date"],
                        "home_team": r["home_team"], "away_team": r["away_team"],
                        "bet_type": r["market"]},
            league=r["league"], db_path=db_path,
        )
        if bid > 0:
            tracked += 1
    return {"tracked": tracked}


# ══════════════════════════════════════════════════════════════════════════════
#  LIVE MONITOR
# ══════════════════════════════════════════════════════════════════════════════

class LiveStartRequest(BaseModel):
    mode:      str = "auto"
    sport_key: str = ""
    interval:  int = 120
    max_tier:  int = 2


@app.post("/api/live/start")
async def start_live(req: LiveStartRequest, background_tasks: BackgroundTasks,
                     username=Depends(get_current_user_api)):
    ls = _user_live_status(username)
    if ls["running"]:
        raise HTTPException(status_code=409, detail="Already running")
    ls.update(running=True, mode=req.mode, sport_key=req.sport_key,
               interval=max(30, req.interval), max_tier=req.max_tier, iteration=0)
    env = user_env(username)
    background_tasks.add_task(_live_loop, username, env)
    return {"status": "started"}


@app.post("/api/live/stop")
async def stop_live(username=Depends(get_current_user_api)):
    _user_live_status(username)["running"] = False
    return {"status": "stopped"}


@app.get("/api/live/results")
async def live_results(username=Depends(get_current_user_api)):
    return {"results": list(_user_live(username)),
            "status": dict(_user_live_status(username))}


def _live_loop(username: str, env: dict):
    for k, v in env.items():
        os.environ[k] = v
    ls = _user_live_status(username)
    while ls["running"]:
        try:
            ls["iteration"] += 1
            if ls["mode"] == "auto":
                from scrapers.live_scanner import scan_all_live
                results = scan_all_live(max_tier=ls["max_tier"])
            else:
                from scrapers.live_scanner import scan_once
                results = scan_once(ls["sport_key"] or "soccer_epl")

            with _state_lock:
                _live_results[username] = results

            _broadcast_sync(username, {
                "type": "live_update", "data": results,
                "iteration": ls["iteration"],
                "ts": datetime.now().strftime("%H:%M:%S"),
            })
        except Exception as e:
            print(f"[LiveLoop:{username}] {e}")
            _broadcast_sync(username, {"type": "live_error", "error": str(e)})

        interval = ls["interval"]
        for _ in range(interval * 2):
            if not ls["running"]:
                break
            time.sleep(0.5)


# ══════════════════════════════════════════════════════════════════════════════
#  TIPSTER
# ══════════════════════════════════════════════════════════════════════════════

@app.get("/api/tipster/picks")
async def tipster_picks(username=Depends(get_current_user_api)):
    cache = _user_pregame(username)
    return {"picks": cache.get("tipster_picks", []),
            "watchlist": cache.get("watchlist", []),
            "scan_date": cache.get("scan_date")}


# ══════════════════════════════════════════════════════════════════════════════
#  HISTORY & PnL
# ══════════════════════════════════════════════════════════════════════════════

@app.get("/api/history/bets")
async def history_bets(status: str = "all", limit: int = 200,
                       username=Depends(get_current_user_api)):
    db_path = str(user_db(username))
    init_db(db_path)
    bets = get_all_bets(limit=limit, db_path=db_path)
    if status != "all":
        bets = [b for b in bets if b["status"].lower() == status.lower()]
    return {"bets": bets}


@app.get("/api/history/stats")
async def history_stats(username=Depends(get_current_user_api)):
    db_path = str(user_db(username))
    init_db(db_path)
    return get_stats(db_path=db_path)


@app.post("/api/history/settle/auto")
async def auto_settle(background_tasks: BackgroundTasks,
                      username=Depends(get_current_user_api)):
    env = user_env(username)
    background_tasks.add_task(_do_auto_settle, username, env)
    return {"status": "started"}


def _do_auto_settle(username: str, env: dict):
    for k, v in env.items():
        os.environ[k] = v
    result = auto_settle_from_api(
        db_path=str(user_db(username)),
        api_key=env.get("ODDS_API_KEY", ""),
    )
    _broadcast_sync(username, {"type": "settle_done", "data": result})


class ManualSettleRequest(BaseModel):
    bet_id:     int
    home_goals: int
    away_goals: int


@app.post("/api/history/settle/manual")
async def manual_settle_endpoint(req: ManualSettleRequest,
                                  username=Depends(get_current_user_api)):
    result = settle_bet(req.bet_id, req.home_goals, req.away_goals,
                        db_path=str(user_db(username)))
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@app.get("/api/history/pending")
async def pending_bets(username=Depends(get_current_user_api)):
    db_path = str(user_db(username))
    init_db(db_path)
    return {"bets": get_pending_bets(db_path=db_path)}


# ══════════════════════════════════════════════════════════════════════════════
#  UTILITIES
# ══════════════════════════════════════════════════════════════════════════════

@app.get("/api/version")
async def version():
    try:
        v = (BASE_DIR / "version.txt").read_text(encoding="utf-8").strip()
    except Exception:
        v = "?"
    return {"version": v}


@app.get("/api/credits")
async def api_credits(username=Depends(get_current_user_api)):
    env = user_env(username)
    for k, v in env.items():
        os.environ[k] = v
    from scrapers.odds_api import get_credits
    return get_credits()
