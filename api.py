"""
BetBot Web API — FastAPI backend
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

from dotenv import load_dotenv
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

# ── Project imports ───────────────────────────────────────────────────────────
from utils.database import (auto_settle_from_api, get_all_bets,
                              get_pending_bets, get_stats, init_db,
                              settle_bet, track_value_bet)
from utils.scan_cache import (clear_league_cache, load_league_scan,
                               load_scan, save_league_scan, save_scan)

# ── App setup ─────────────────────────────────────────────────────────────────
app = FastAPI(title="BetBot", docs_url=None, redoc_url=None)

WEB_DIR = BASE_DIR / "web"
app.mount("/static", StaticFiles(directory=str(WEB_DIR / "static")), name="static")
templates = Jinja2Templates(directory=str(WEB_DIR / "templates"))

# ── Auth ──────────────────────────────────────────────────────────────────────
APP_PASSWORD = os.getenv("APP_PASSWORD", "betbot2024")
APP_USERNAME = os.getenv("APP_USERNAME", "admin")
SESSION_SECRET = hashlib.sha256(APP_PASSWORD.encode()).hexdigest()[:32]

COOKIE_NAME = "bb_session"


def _make_token() -> str:
    return hmac.new(SESSION_SECRET.encode(), APP_PASSWORD.encode(), "sha256").hexdigest()


def _valid_token(token: str) -> bool:
    return hmac.compare_digest(token, _make_token())


def check_session(request: Request, bb_session: str = Cookie(default="")):
    if not _valid_token(bb_session):
        raise HTTPException(status_code=302,
                            headers={"Location": f"/login?next={request.url.path}"})
    return True


def check_session_api(bb_session: str = Cookie(default="")):
    if not _valid_token(bb_session):
        raise HTTPException(status_code=401, detail="Unauthorized")
    return True


# ── Global state ──────────────────────────────────────────────────────────────
_live_results:  list = []
_live_lock      = threading.Lock()
_scan_status:   dict = {"running": False, "text": "", "progress": 0.0}
_live_status:   dict = {"running": False, "interval": 120, "mode": "auto",
                         "sport_key": "", "max_tier": 2, "iteration": 0}
_pregame_cache: dict = {}
_ws_clients:    list = []
_ws_lock        = asyncio.Lock()


# ── WebSocket helpers ─────────────────────────────────────────────────────────
async def _broadcast(payload: dict):
    msg = json.dumps(payload, ensure_ascii=False, default=str)
    dead = []
    async with _ws_lock:
        for ws in list(_ws_clients):
            try:
                await ws.send_text(msg)
            except Exception:
                dead.append(ws)
        for ws in dead:
            try:
                _ws_clients.remove(ws)
            except ValueError:
                pass


def _broadcast_sync(payload: dict):
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            asyncio.run_coroutine_threadsafe(_broadcast(payload), loop)
    except Exception:
        pass


# ── Startup ───────────────────────────────────────────────────────────────────
@app.on_event("startup")
async def startup():
    pathlib.Path("data").mkdir(exist_ok=True)
    init_db()
    cached = load_scan()
    if cached:
        global _pregame_cache
        _pregame_cache = cached
        print("[API] Restored today's pre-game cache from disk")


# ── Login ─────────────────────────────────────────────────────────────────────
@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, next: str = "/pregame"):
    return templates.TemplateResponse(request=request, name="login.html", context={"next": next})


@app.post("/login")
async def login_submit(username: str = Form(...), password: str = Form(...),
                        next: str = Form(default="/pregame")):
    if username == APP_USERNAME and password == APP_PASSWORD:
        resp = RedirectResponse(next, status_code=303)
        resp.set_cookie(COOKIE_NAME, _make_token(),
                        httponly=True, samesite="lax", max_age=60*60*24*30)
        return resp
    return RedirectResponse("/login?error=1", status_code=303)


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
async def page_pregame(request: Request, auth=Depends(check_session)):
    return templates.TemplateResponse(request=request, name="pregame.html")


@app.get("/live", response_class=HTMLResponse)
async def page_live(request: Request, auth=Depends(check_session)):
    return templates.TemplateResponse(request=request, name="live.html")


@app.get("/tipster", response_class=HTMLResponse)
async def page_tipster(request: Request, auth=Depends(check_session)):
    return templates.TemplateResponse(request=request, name="tipster.html")


@app.get("/history", response_class=HTMLResponse)
async def page_history(request: Request, auth=Depends(check_session)):
    return templates.TemplateResponse(request=request, name="history.html")


# ── WebSocket — cookies sent automatically by browser ────────────────────────
@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket, bb_session: str = Cookie(default="")):
    if not _valid_token(bb_session):
        await ws.close(code=4001)
        return
    await ws.accept()
    async with _ws_lock:
        _ws_clients.append(ws)
    try:
        with _live_lock:
            current = list(_live_results)
        if current:
            await ws.send_text(json.dumps(
                {"type": "live_update", "data": current,
                 "iteration": _live_status["iteration"]},
                ensure_ascii=False, default=str,
            ))
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        async with _ws_lock:
            try:
                _ws_clients.remove(ws)
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
                              auth=Depends(check_session_api)):
    if _scan_status["running"]:
        raise HTTPException(status_code=409, detail="Scan already running")
    if req.clear_cache:
        clear_league_cache()
    background_tasks.add_task(_run_pregame_scan, req.league)
    return {"status": "started", "league": req.league}


@app.get("/api/scan/status")
async def scan_status(auth=Depends(check_session_api)):
    return dict(_scan_status)


@app.get("/api/scan/results")
async def scan_results(auth=Depends(check_session_api)):
    return {k: v for k, v in _pregame_cache.items() if k != "_value_rows"}


@app.get("/api/leagues")
async def get_leagues(auth=Depends(check_session_api)):
    from scrapers.odds_api import SPORT_KEYS
    options = ["ALL LEAGUES", "TIER 1 ONLY", "TIER 2 ONLY", "TIER 3 ONLY"]
    options += list(SPORT_KEYS.keys())
    return {"leagues": options}


def _run_pregame_scan(league_key: str):
    global _pregame_cache
    _scan_status["running"] = True
    _scan_status["text"]    = "Starting scan..."
    _scan_status["progress"] = 0.0
    _broadcast_sync({"type": "scan_status", "data": dict(_scan_status)})

    try:
        from scrapers.odds_api import (SPORT_KEYS, get_event_count_today,
                                        get_odds, get_pinnacle_no_vig_ht_totals,
                                        get_pinnacle_no_vig_probs,
                                        get_pinnacle_no_vig_totals)
        from models.live_targets import LiveTarget, classify, score_targets
        from models.value_calculator import compare_bookmakers, kelly_criterion
        from utils.league_map import ODDS_KEY_TO_LEAGUE as OKL

        bankroll  = float(os.getenv("BANKROLL", "1000"))
        markets   = ["h2h", "totals", "totals_h1"]
        today_str = date.today().isoformat()

        _TIER_OPTS  = {"ALL LEAGUES", "TIER 1 ONLY", "TIER 2 ONLY", "TIER 3 ONLY"}
        scan_all    = league_key in _TIER_OPTS
        tier_filter = {"TIER 1 ONLY": 1, "TIER 2 ONLY": 2, "TIER 3 ONLY": 3}.get(league_key)

        rows, value_rows, all_targets, events_data = [], [], [], []

        def _process_league(lkey: str, sport_key: str):
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
                        "league":       lkey,
                        "match":        f"{ev['home_team']} vs {ev['away_team']}",
                        "date":         ev["commence"][:10],
                        "market":       mkt,
                        "prob":         prob,
                        "bookmaker":    best["bookmaker"],
                        "odds":         best["bookmaker_odds"],
                        "edge":         best["value_edge"],
                        "kelly":        kelly["suggested_bet"],
                        "is_value":     best["is_value_bet"],
                        "home_team":    ev["home_team"],
                        "away_team":    ev["away_team"],
                        "event_id":     ev.get("id", ""),
                        "value_result": best,
                        "kelly_result": kelly,
                    }
                    _rows.append(row)
                    if best["is_value_bet"]:
                        _vrows.append(row)
                        has_value_ev = True

                    best_mkt = max(bm_odds.values())
                    if   mkt_key == "totals"    and side == "over":                       best_over = best_mkt
                    elif mkt_key == "1x2"       and side == "home":                       best_home = best_mkt
                    elif mkt_key == "1x2"       and side == "away":                       best_away = best_mkt
                    elif mkt_key == "totals_h1" and side == "over" and pt == "0_5":       best_ht   = best_mkt

                for bm, bd in ev.get("odds", {}).items():
                    if bm == "pinnacle":
                        continue
                    b = (bd.get("btts") or {}).get("yes")
                    if b and (best_btts is None or b > best_btts):
                        best_btts = b

                _tgts.extend(classify(
                    ev, p_1x2, p_ou,
                    best_over_odds=best_over, best_home_odds=best_home,
                    best_away_odds=best_away, best_btts_odds=best_btts,
                    best_ht_odds=best_ht,     p_ht_ou=p_ht,
                    has_value_bet=has_value_ev,
                ))
            return _rows, _vrows, _tgts, _evdata

        # ── Build items list ──────────────────────────────────────────────────
        if tier_filter is not None:
            items = [(lk, sk) for lk, sk in SPORT_KEYS.items()
                     if OKL.get(sk, {}).get("tier", 2) == tier_filter]
        elif scan_all:
            items = list(SPORT_KEYS.items())
        else:
            items = [(league_key, SPORT_KEYS.get(league_key, "soccer_epl"))]

        # ── Pre-filter ────────────────────────────────────────────────────────
        if scan_all:
            _scan_status["text"] = "Checking which leagues play today (0 credits)..."
            _broadcast_sync({"type": "scan_status", "data": dict(_scan_status)})
            items = [(lk, sk) for lk, sk in items if get_event_count_today(sk) > 0]

        # ── Scan ──────────────────────────────────────────────────────────────
        total = len(items)
        for idx, (lkey, sport_key) in enumerate(items):
            _scan_status["text"]     = f"[{idx+1}/{total}] {lkey.replace('_',' ').title()}..."
            _scan_status["progress"] = idx / total if total else 0
            _broadcast_sync({"type": "scan_status", "data": dict(_scan_status)})

            cached = load_league_scan(sport_key)
            if cached:
                rows.extend(cached["rows"])
                value_rows.extend([r for r in cached["rows"] if r.get("is_value")])
                all_targets.extend([LiveTarget(**t) for t in cached.get("targets", [])])
                events_data.extend(cached.get("events_data", []))
                continue

            r, vr, t, evd = _process_league(lkey, sport_key)
            rows.extend(r)
            value_rows.extend(vr)
            all_targets.extend(t)
            events_data.extend(evd)
            save_league_scan(sport_key, r, evd, t)
            if scan_all and idx < total - 1:
                time.sleep(1)

        # ── Tipster + Watchlist ───────────────────────────────────────────────
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

        _pregame_cache = {
            "scan_date":     today_str,
            "saved_at":      datetime.now().isoformat(),
            "rows":          [{k: v for k, v in r.items()
                               if k not in ("value_result","kelly_result")} for r in rows],
            "value_count":   len(value_rows),
            "targets":       [dataclasses.asdict(t) for t in all_targets],
            "tipster_picks": [dataclasses.asdict(p) for p in tipster_picks],
            "watchlist":     [dataclasses.asdict(g) for g in watchlist],
            "_value_rows":   value_rows,  # kept in memory only, not sent to client
        }

        save_scan(rows, all_targets, tipster_picks, watchlist)

        _scan_status["running"]  = False
        _scan_status["text"]     = f"✓ {len(value_rows)} value bets | {len(rows)} markets"
        _scan_status["progress"] = 1.0
        _broadcast_sync({
            "type":    "scan_done",
            "data":    dict(_scan_status),
            "results": {k: v for k, v in _pregame_cache.items() if k != "_value_rows"},
        })

    except Exception as e:
        import traceback; traceback.print_exc()
        _scan_status["running"] = False
        _scan_status["text"]    = f"Error: {e}"
        _broadcast_sync({"type": "scan_error", "error": str(e)})


@app.post("/api/scan/track")
async def track_bets(auth=Depends(check_session_api)):
    value_rows = _pregame_cache.get("_value_rows", [])
    if not value_rows:
        raise HTTPException(status_code=400, detail="No value bets to track")
    tracked = 0
    for r in value_rows:
        vr = r.get("value_result") or {
            "our_probability": r["prob"], "bookmaker": r["bookmaker"],
            "bookmaker_odds":  r["odds"], "value_edge": r["edge"],
        }
        kr = r.get("kelly_result") or {"suggested_bet": r["kelly"]}
        bid = track_value_bet(
            value_result=vr, kelly_result=kr,
            match_info={
                "event_id":   r.get("event_id", ""),
                "match_date": r["date"],
                "home_team":  r["home_team"],
                "away_team":  r["away_team"],
                "bet_type":   r["market"],
            },
            league=r["league"],
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
                     auth=Depends(check_session_api)):
    if _live_status["running"]:
        raise HTTPException(status_code=409, detail="Live scan already running")
    _live_status.update(
        running=True, mode=req.mode, sport_key=req.sport_key,
        interval=max(30, req.interval), max_tier=req.max_tier, iteration=0,
    )
    background_tasks.add_task(_live_loop)
    return {"status": "started"}


@app.post("/api/live/stop")
async def stop_live(auth=Depends(check_session_api)):
    _live_status["running"] = False
    return {"status": "stopped"}


@app.get("/api/live/results")
async def live_results(auth=Depends(check_session_api)):
    with _live_lock:
        return {"results": list(_live_results), "status": dict(_live_status)}


def _live_loop():
    while _live_status["running"]:
        try:
            _live_status["iteration"] += 1
            if _live_status["mode"] == "auto":
                from scrapers.live_scanner import scan_all_live
                results = scan_all_live(max_tier=_live_status["max_tier"])
            else:
                from scrapers.live_scanner import scan_once
                sk = _live_status["sport_key"] or "soccer_epl"
                results = scan_once(sk)

            with _live_lock:
                _live_results.clear()
                _live_results.extend(results)

            _broadcast_sync({
                "type":      "live_update",
                "data":      results,
                "iteration": _live_status["iteration"],
                "ts":        datetime.now().strftime("%H:%M:%S"),
            })
        except Exception as e:
            print(f"[LiveLoop] Error: {e}")
            _broadcast_sync({"type": "live_error", "error": str(e)})

        interval = _live_status["interval"]
        for _ in range(interval * 2):
            if not _live_status["running"]:
                break
            time.sleep(0.5)


# ══════════════════════════════════════════════════════════════════════════════
#  TIPSTER + WATCHLIST
# ══════════════════════════════════════════════════════════════════════════════

@app.get("/api/tipster/picks")
async def tipster_picks(auth=Depends(check_session_api)):
    return {
        "picks":     _pregame_cache.get("tipster_picks", []),
        "watchlist": _pregame_cache.get("watchlist", []),
        "scan_date": _pregame_cache.get("scan_date"),
    }


# ══════════════════════════════════════════════════════════════════════════════
#  HISTORY & PnL
# ══════════════════════════════════════════════════════════════════════════════

@app.get("/api/history/bets")
async def history_bets(status: str = "all", limit: int = 200,
                       auth=Depends(check_session_api)):
    bets = get_all_bets(limit=limit)
    if status != "all":
        bets = [b for b in bets if b["status"].lower() == status.lower()]
    return {"bets": bets}


@app.get("/api/history/stats")
async def history_stats(auth=Depends(check_session_api)):
    return get_stats()


@app.post("/api/history/settle/auto")
async def auto_settle(background_tasks: BackgroundTasks,
                      auth=Depends(check_session_api)):
    background_tasks.add_task(_do_auto_settle)
    return {"status": "started"}


def _do_auto_settle():
    result = auto_settle_from_api()
    _broadcast_sync({"type": "settle_done", "data": result})


class ManualSettleRequest(BaseModel):
    bet_id:     int
    home_goals: int
    away_goals: int


@app.post("/api/history/settle/manual")
async def manual_settle_endpoint(req: ManualSettleRequest,
                                  auth=Depends(check_session_api)):
    result = settle_bet(req.bet_id, req.home_goals, req.away_goals)
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@app.get("/api/history/pending")
async def pending_bets(auth=Depends(check_session_api)):
    return {"bets": get_pending_bets()}


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
async def api_credits(auth=Depends(check_session_api)):
    from scrapers.odds_api import get_credits
    return get_credits()
