"""
Value Betting Bot — GUI
Dark Mode με customtkinter
python gui.py
"""

import customtkinter as ctk
import tkinter as tk
from tkinter import ttk, messagebox
import threading
import traceback
import queue
import os
import pathlib
from datetime import datetime
from dotenv import load_dotenv

_ERROR_LOG = pathlib.Path("data/error.log")

def _read_version() -> str:
    for p in (pathlib.Path(__file__).parent / "version.txt",
              pathlib.Path("version.txt")):
        if p.exists():
            return p.read_text(encoding="utf-8").strip()
    return "?"

_VERSION = _read_version()


def _log_error(context: str, exc: Exception):
    """Write full traceback to data/error.log and print to console."""
    try:
        _ERROR_LOG.parent.mkdir(exist_ok=True)
        entry = (
            f"\n{'='*60}\n"
            f"{datetime.now().isoformat()}  [{context}]\n"
            f"{traceback.format_exc()}"
        )
        with _ERROR_LOG.open("a", encoding="utf-8") as f:
            f.write(entry)
        print(f"[ERROR] {context}: {exc}")
    except Exception:
        pass

load_dotenv()

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

# ── Palette ──────────────────────────────────────────────────────────────────
C_BG       = "#1a1a2e"
C_CARD     = "#16213e"
C_SIDEBAR  = "#0d0d1a"
C_ACCENT   = "#1f538d"
C_GREEN    = "#00b894"
C_RED      = "#d63031"
C_YELLOW   = "#fdcb6e"
C_TEXT     = "#dfe6e9"
C_DIM      = "#636e72"
C_ROW_ALT  = "#1e1e30"
C_TREE_BG  = "#141428"
C_TREE_HDR = "#252540"

LEAGUE_ABBREV = {
    "premier_league":    "EPL",   "champions_league":  "UCL",
    "la_liga":           "ESP",   "bundesliga":         "GER",
    "serie_a":           "ITA",   "ligue_1":            "FRA",
    "eredivisie":        "NED",   "primeira_liga":      "POR",
    "championship":      "CH",    "super_league":       "GRE",
    "europa_league":     "UEL",   "conference":         "UECL",
    "super_lig":         "TUR",   "pro_league":         "BEL",
    "scottish_prem":     "SCO",   "la_liga_2":          "ESP2",
    "bundesliga_2":      "GER2",  "serie_b":            "ITA2",
    "ligue_2":           "FRA2",  "league_one":         "ENG3",
    "allsvenskan":       "SWE",   "superligaen":        "DEN",
    "eliteserien":       "NOR",   "ekstraklasa":        "POL",
    "brasileirao":       "BRA",   "argentina_primera":  "ARG",
    "liga_mx":           "MEX",   "mls":                "MLS",
    "j1_league":         "JPN",
}


# ── Treeview dark style (shared) ─────────────────────────────────────────────
def _apply_tree_style(style_name: str):
    s = ttk.Style()
    s.theme_use("clam")
    s.configure(f"{style_name}.Treeview",
        background=C_TREE_BG, foreground=C_TEXT,
        rowheight=30, fieldbackground=C_TREE_BG,
        borderwidth=0, font=("Segoe UI", 11),
    )
    s.map(f"{style_name}.Treeview",
        background=[("selected", C_ACCENT)],
        foreground=[("selected", "white")],
    )
    s.configure(f"{style_name}.Treeview.Heading",
        background=C_TREE_HDR, foreground="#74b9ff",
        relief="flat", font=("Segoe UI", 11, "bold"),
    )
    s.map(f"{style_name}.Treeview.Heading",
        background=[("active", "#2d2d50")],
    )
    s.configure("Vertical.TScrollbar",
        background=C_TREE_HDR, troughcolor=C_TREE_BG,
        borderwidth=0, arrowsize=12,
    )


def _make_tree(parent, columns: dict, style_name: str) -> tuple[ttk.Treeview, ttk.Scrollbar]:
    """Helper: δημιουργεί styled Treeview + scrollbar."""
    _apply_tree_style(style_name)
    tree = ttk.Treeview(
        parent, columns=list(columns.keys()),
        show="headings", style=f"{style_name}.Treeview",
        selectmode="browse",
    )
    for col, (heading, width, anchor) in columns.items():
        tree.heading(col, text=heading)
        tree.column(col, width=width, anchor=anchor, minwidth=width)
    tree.tag_configure("value",   foreground=C_GREEN,  font=("Segoe UI", 11, "bold"))
    tree.tag_configure("alt",     background=C_ROW_ALT)
    tree.tag_configure("win",     foreground=C_GREEN)
    tree.tag_configure("loss",    foreground=C_RED)
    tree.tag_configure("pending", foreground=C_YELLOW)
    tree.tag_configure("void",    foreground=C_DIM)

    sb = ttk.Scrollbar(parent, orient="vertical", command=tree.yview)
    tree.configure(yscrollcommand=sb.set)
    return tree, sb


# ═══════════════════════════════════════════════════════════════════════════════
#  PRE-GAME FRAME
# ═══════════════════════════════════════════════════════════════════════════════
class PregameFrame(ctk.CTkFrame):
    def __init__(self, parent, app):
        super().__init__(parent, corner_radius=12, fg_color=C_CARD)
        self.app       = app
        self._scanning = False
        self._results  = []   # value bets found
        self._build()

    def _build(self):
        # ── Header ────────────────────────────────────────────────────────────
        hdr = ctk.CTkFrame(self, fg_color="transparent")
        hdr.pack(fill="x", padx=20, pady=(16, 4))

        ctk.CTkLabel(hdr, text="Pre-game Value Scanner",
                     font=ctk.CTkFont(size=22, weight="bold")).pack(side="left")

        # ── Controls ──────────────────────────────────────────────────────────
        ctrl = ctk.CTkFrame(self, fg_color="transparent")
        ctrl.pack(fill="x", padx=20, pady=8)

        ctk.CTkLabel(ctrl, text="Πρωτάθλημα:",
                     font=ctk.CTkFont(size=13)).pack(side="left")

        from scrapers.odds_api import SPORT_KEYS
        _league_opts = ["ALL LEAGUES", "TIER 1 ONLY", "TIER 2 ONLY", "TIER 3 ONLY"] + list(SPORT_KEYS.keys())
        self._league_var = ctk.StringVar(value="TIER 1 ONLY")
        ctk.CTkComboBox(
            ctrl, values=_league_opts,
            variable=self._league_var, width=220,
            font=ctk.CTkFont(size=12),
        ).pack(side="left", padx=(8, 16))

        self._scan_btn = ctk.CTkButton(
            ctrl, text="🔍  SCAN", command=self._start_scan,
            width=140, height=38,
            font=ctk.CTkFont(size=14, weight="bold"),
            fg_color=C_ACCENT, hover_color="#174a82",
        )
        self._scan_btn.pack(side="left")

        self._track_btn = ctk.CTkButton(
            ctrl, text="💾  Track Value Bets", command=self._track_all,
            width=180, height=38,
            font=ctk.CTkFont(size=12),
            fg_color="#00695c", hover_color="#004d40",
            state="disabled",
        )
        self._track_btn.pack(side="left", padx=12)

        self._status = ctk.CTkLabel(ctrl, text="",
                                    font=ctk.CTkFont(size=12), text_color=C_DIM)
        self._status.pack(side="right")

        # ── Progress bar ──────────────────────────────────────────────────────
        self._progress = ctk.CTkProgressBar(self, mode="indeterminate", height=5,
                                             progress_color=C_ACCENT)

        # ── Value Bets Table ──────────────────────────────────────────────────
        cols = {
            "match":     ("Αγώνας",         260, "w"),
            "date":      ("Ημ/νία",          88, "center"),
            "market":    ("Αγορά",          108, "center"),
            "prob":      ("Πιθανότητα",     100, "center"),
            "bookmaker": ("Bookmaker",      130, "center"),
            "odds":      ("Απόδοση",         80, "center"),
            "edge":      ("Edge %",          80, "center"),
            "kelly":     ("Kelly Stake",    100, "center"),
        }
        tbl = ctk.CTkFrame(self, fg_color=C_TREE_BG, corner_radius=8)
        tbl.pack(fill="both", expand=True, padx=20, pady=(0, 4))

        self._tree, sb = _make_tree(tbl, cols, "PG")
        self._tree.pack(side="left", fill="both", expand=True, padx=(6, 0), pady=6)
        sb.pack(side="right", fill="y", pady=6, padx=(0, 4))

        # ── Live Targets Section ──────────────────────────────────────────────
        ctk.CTkFrame(self, height=1, fg_color="#2d2d50").pack(fill="x", padx=20, pady=(4, 0))

        tgt_hdr = ctk.CTkFrame(self, fg_color="transparent")
        tgt_hdr.pack(fill="x", padx=20, pady=(6, 2))
        self._targets_lbl = ctk.CTkLabel(
            tgt_hdr, text="Σημερινά Live Targets",
            font=ctk.CTkFont(size=15, weight="bold"),
            text_color=C_YELLOW,
        )
        self._targets_lbl.pack(side="left")
        ctk.CTkLabel(
            tgt_hdr,
            text="Αγώνες χωρίς pre-game value αξίζει να φορτωθούν στο Live Monitor",
            font=ctk.CTkFont(size=11), text_color=C_DIM,
        ).pack(side="left", padx=12)

        tgt_cols = {
            "prio":   ("Priority",          82, "center"),
            "match":  ("Αγώνας",           220, "w"),
            "type":   ("Target Type",      138, "center"),
            "prob":   ("Πιθανότητα",        90, "center"),
            "odds":   ("Τρέχ. Απόδοση",    100, "center"),
            "action": ("Action / Οδηγία",  380, "w"),
        }
        tgt_frame = ctk.CTkFrame(self, fg_color=C_TREE_BG, corner_radius=8)
        tgt_frame.pack(fill="x", padx=20, pady=(0, 16))

        self._targets_tree, tgt_sb = _make_tree(tgt_frame, tgt_cols, "TGT")
        self._targets_tree.configure(height=5)
        self._targets_tree.pack(side="left", fill="both", expand=True, padx=(6, 0), pady=6)
        tgt_sb.pack(side="right", fill="y", pady=6, padx=(0, 4))

        self._targets_tree.tag_configure("target_high", foreground=C_RED,    font=("Segoe UI", 11, "bold"))
        self._targets_tree.tag_configure("target_med",  foreground=C_YELLOW, font=("Segoe UI", 11))
        self._targets_tree.tag_configure("target_low",  foreground=C_DIM,    font=("Segoe UI", 11))

    # ── Scan logic ────────────────────────────────────────────────────────────
    def _start_scan(self):
        if self._scanning:
            return
        self._scanning = True
        self._scan_btn.configure(state="disabled", text="⏳  Scanning...")
        self._track_btn.configure(state="disabled")
        self._status.configure(text="")
        self._progress.pack(fill="x", padx=20, pady=(0, 4))
        self._progress.start()
        for i in self._tree.get_children():
            self._tree.delete(i)
        for i in self._targets_tree.get_children():
            self._targets_tree.delete(i)
        self._targets_lbl.configure(text="Σημερινά Live Targets")

        t = threading.Thread(target=self._worker,
                             args=(self._league_var.get(),), daemon=True)
        t.start()

    def _worker(self, league_key: str):
        import time as _time
        try:
            from scrapers.odds_api import (get_odds, get_pinnacle_no_vig_probs,
                                           get_pinnacle_no_vig_totals,
                                           get_pinnacle_no_vig_ht_totals, SPORT_KEYS)
            from models.value_calculator import compare_bookmakers, kelly_criterion
            from models.live_targets import classify, score_targets

            bankroll = float(os.getenv("BANKROLL", "1000"))
            _TIER_OPTS = {"ALL LEAGUES", "TIER 1 ONLY", "TIER 2 ONLY", "TIER 3 ONLY"}
            scan_all   = league_key in _TIER_OPTS
            tier_filter = None
            if league_key == "TIER 1 ONLY":
                tier_filter = 1
            elif league_key == "TIER 2 ONLY":
                tier_filter = 2
            elif league_key == "TIER 3 ONLY":
                tier_filter = 3
            # Always include totals_h1 — adding markets to a single request costs 0 extra credits
            markets  = ["h2h", "totals", "totals_h1"]
            rows, value_rows, all_targets = [], [], []
            events_data = []   # fed into AI Tipster + Watchlist after scan

            # Tier lookup: sport_key → tier (for watchlist scoring)
            from utils.league_map import ODDS_KEY_TO_LEAGUE as _OKL

            # ── Inner helper: process one league's events ─────────────────
            from datetime import date as _date
            _today = _date.today().isoformat()

            def _process_league(lkey, sport_key_inner):
                _rows, _vrows, _tgts, _evdata = [], [], [], []
                try:
                    events = get_odds(sport_key_inner, markets=markets)
                except Exception:
                    return _rows, _vrows, _tgts, _evdata

                # Today-only filter
                events = [e for e in events if e.get("commence", "")[:10] == _today]

                for ev in events:
                    p_1x2  = get_pinnacle_no_vig_probs(ev)
                    p_ou   = get_pinnacle_no_vig_totals(ev, 2.5)
                    p_ht   = get_pinnacle_no_vig_ht_totals(ev, 0.5)
                    p_ht15 = get_pinnacle_no_vig_ht_totals(ev, 1.5)

                    # Tier from league_map (default 2 if league unknown)
                    _tier = _OKL.get(sport_key_inner, {}).get("tier", 2)

                    # Collect for AI Tipster + Watchlist
                    _evdata.append({
                        "event":  ev,
                        "p_1x2":  p_1x2,
                        "p_ou":   p_ou,
                        "p_ht":   p_ht,
                        "p_ht15": p_ht15,
                        "league": lkey,
                        "tier":   _tier,
                    })

                    checks = []
                    if p_ou:
                        _pt = str(p_ou["point"]).replace(".", "_")
                        checks += [("Over 2.5",  p_ou["over_prob"],  "totals", "over",  _pt),
                                   ("Under 2.5", p_ou["under_prob"], "totals", "under", _pt)]
                    if p_1x2:
                        checks += [("Home Win", p_1x2["home"], "1x2", "home", None),
                                   ("Draw",     p_1x2["draw"], "1x2", "draw", None),
                                   ("Away Win", p_1x2["away"], "1x2", "away", None)]
                    if p_ht:
                        _ht_pt = str(p_ht["point"]).replace(".", "_")
                        checks += [("Over 0.5 HT",  p_ht["over_prob"],  "totals_h1", "over",  _ht_pt),
                                   ("Under 0.5 HT", p_ht["under_prob"], "totals_h1", "under", _ht_pt)]
                    if p_ht15:
                        _ht15_pt = str(p_ht15["point"]).replace(".", "_")
                        checks += [("Over 1.5 HT",  p_ht15["over_prob"],  "totals_h1", "over",  _ht15_pt),
                                   ("Under 1.5 HT", p_ht15["under_prob"], "totals_h1", "under", _ht15_pt)]

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
                        row = {
                            "event": ev, "league": lkey,
                            "match": f"{ev['home_team']} vs {ev['away_team']}",
                            "date":  ev["commence"][:10],
                            "market": mkt, "prob": prob,
                            "bookmaker": best["bookmaker"],
                            "odds": best["bookmaker_odds"],
                            "edge": best["value_edge"],
                            "kelly": kelly["suggested_bet"],
                            "is_value": best["is_value_bet"],
                            "value_result": best, "kelly_result": kelly,
                        }
                        _rows.append(row)
                        if best["is_value_bet"]:
                            _vrows.append(row)
                            has_value_ev = True

                        best_mkt = max(bm_odds.values())
                        if mkt_key == "totals" and side == "over":
                            best_over = best_mkt
                        elif mkt_key == "1x2" and side == "home":
                            best_home = best_mkt
                        elif mkt_key == "1x2" and side == "away":
                            best_away = best_mkt
                        elif mkt_key == "totals_h1" and side == "over" and pt == "0_5":
                            best_ht = best_mkt

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

            # ── Step 1: Football-Data.org fixtures pre-fetch (Tier 1 / ALL only) ─
            if scan_all and tier_filter in (None, 1):
                try:
                    from scrapers.football_data import COMPETITIONS, get_upcoming_matches
                    fd_list = list(COMPETITIONS.keys())
                    n_fd    = len(fd_list)
                    for fi, comp in enumerate(fd_list):
                        self.app.q(lambda fi=fi, n=n_fd: self._status.configure(
                            text=f"Football-Data.org [{fi+1}/{n}] fixtures...",
                            text_color=C_DIM,
                        ))
                        try:
                            get_upcoming_matches(comp)
                        except Exception:
                            pass
                        if fi < n_fd - 1:
                            _time.sleep(1)
                except Exception:
                    pass
                # Refresh Greek Super League results cache (uses Odds API key, no extra cost)
                try:
                    from scrapers.greek_stats import update_results_cache
                    update_results_cache()
                except Exception:
                    pass

            # ── Step 2: The Odds API scan ─────────────────────────────────
            if tier_filter is not None:
                items = [(lk, sk) for lk, sk in SPORT_KEYS.items()
                         if _OKL.get(sk, {}).get("tier", 2) == tier_filter]
            elif scan_all:
                items = list(SPORT_KEYS.items())
            else:
                items = [(league_key, SPORT_KEYS.get(league_key, "soccer_epl"))]
            total = len(items)

            # ── Pre-filter: skip leagues with no games today (0 credits) ──
            if scan_all:  # covers both ALL LEAGUES and TIER 1 ONLY
                from scrapers.odds_api import get_event_count_today
                self.app.q(lambda: self._status.configure(
                    text="Ελέγχω ποια leagues παίζουν σήμερα (0 credits)...",
                    text_color=C_DIM,
                ))
                active_items = []
                for lkey, sport_key in items:
                    n_today = get_event_count_today(sport_key)
                    if n_today > 0:
                        active_items.append((lkey, sport_key))
                        print(f"[Scan] {lkey}: {n_today} games today ✓")
                    else:
                        print(f"[Scan] {lkey}: 0 games today — skip")
                skipped = len(items) - len(active_items)
                items = active_items
                total = len(items)
                self.app.q(lambda s=skipped, a=len(active_items): self._status.configure(
                    text=f"Leagues με παιχνίδια σήμερα: {a}  (παράλειψη {s} χωρίς παιχνίδια)",
                    text_color=C_DIM,
                ))

            from utils.scan_cache import load_league_scan, save_league_scan
            from models.live_targets import LiveTarget as _LiveTarget

            for idx, (lkey, sport_key) in enumerate(items):
                # ── Check per-league cache first (saves credits) ──────────
                cached_league = load_league_scan(sport_key)
                if cached_league:
                    print(f"[Scan] {lkey}: cached today ✓ (0 credits)")
                    _cr = cached_league["rows"]
                    _ct = [_LiveTarget(**t) for t in cached_league.get("targets", [])]
                    _ce = cached_league.get("events_data", [])
                    rows.extend(_cr)
                    value_rows.extend([r for r in _cr if r.get("is_value")])
                    all_targets.extend(_ct)
                    events_data.extend(_ce)
                    continue

                if scan_all:
                    self.app.q(lambda i=idx, k=lkey, n=total: self._status.configure(
                        text=f"The Odds API [{i+1}/{n}]  {k.replace('_',' ').title()}...",
                        text_color=C_DIM,
                    ))
                r, vr, t, evd = _process_league(lkey, sport_key)
                rows.extend(r)
                value_rows.extend(vr)
                all_targets.extend(t)
                events_data.extend(evd)
                save_league_scan(sport_key, r, evd, t)
                if scan_all and idx < total - 1:
                    _time.sleep(1)

            all_targets = score_targets(all_targets)
            self.app.q(lambda r=rows, vr=value_rows, t=all_targets, ed=events_data:
                       self._done(r, vr, t, ed))
        except Exception as e:
            _log_error("PregameScan", e)
            self.app.q(lambda err=str(e): self._error(err))

    def _done(self, rows: list, value_rows: list, targets: list, events_data: list = None):
        self._progress.stop()
        self._progress.pack_forget()
        self._scanning = False
        self._scan_btn.configure(state="normal", text="🔍  SCAN")
        self._results = value_rows
        cnt          = len(value_rows)
        n_leagues    = len(set(r["league"] for r in rows)) if rows else 0
        multi_league = n_leagues > 1
        league_info  = f"  |  {n_leagues} leagues" if multi_league else ""
        self._status.configure(
            text=f"✓ {cnt} value bets  |  {len(rows)} αγορές{league_info}",
            text_color=C_GREEN if cnt else C_DIM,
        )
        if cnt:
            self._track_btn.configure(state="normal")

        # Sort: value bets πρώτα, μετά κατά edge descending
        rows.sort(key=lambda x: (not x["is_value"], -x["edge"]))
        for i, r in enumerate(rows):
            tag   = "value" if r["is_value"] else ("alt" if i % 2 else "")
            abbr  = LEAGUE_ABBREV.get(r["league"], r["league"][:4].upper())
            match = f"[{abbr}]  {r['match']}" if multi_league else r["match"]
            self._tree.insert("", "end", tags=(tag,), values=(
                match, r["date"], r["market"],
                f"{r['prob']:.1%}", r["bookmaker"], r["odds"],
                f"{r['edge']*100:+.1f}%",
                f"€{r['kelly']:.2f}" if r["is_value"] else "—",
            ))

        # ── AI Tipster + Watchlist: generate + display ───────────────────────
        tipster_picks   = []
        watchlist_games = []
        if events_data:
            try:
                from models.tipster import generate_picks
                tipster_picks = generate_picks(events_data)
            except Exception as e:
                _log_error("generate_picks", e)
            try:
                from models.watchlist import generate_watchlist
                watchlist_games = generate_watchlist(events_data)
            except Exception as e:
                _log_error("generate_watchlist", e)
            if "tipster" in self.app.frames:
                try:
                    self.app.frames["tipster"].update_picks(tipster_picks)
                    # Only overwrite watchlist if we actually got new games
                    if watchlist_games:
                        self.app.frames["tipster"].update_watchlist(watchlist_games)
                except Exception as e:
                    _log_error("TipsterFrame.update", e)
        try:
            from utils.scan_cache import save_scan
            save_scan(rows, targets, tipster_picks, watchlist_games)
        except Exception as e:
            _log_error("save_scan", e)

        # ── Populate Live Targets ─────────────────────────────────────────────
        n = len(targets)
        self._targets_lbl.configure(
            text=f"Σημερινά Live Targets  ({n})" if n else "Σημερινά Live Targets  (κανένα)",
        )
        for t in targets:
            tag = {1: "target_high", 2: "target_med", 3: "target_low"}.get(t.priority, "target_low")
            odds_str = f"{t.current_odds:.2f}" if t.current_odds else "—"
            self._targets_tree.insert("", "end", tags=(tag,), values=(
                t.priority_label,
                t.match,
                t.target_type,
                f"{t.key_prob:.1%}",
                odds_str,
                t.action,
            ))

    def _error(self, msg: str):
        self._progress.stop()
        self._progress.pack_forget()
        self._scanning = False
        self._scan_btn.configure(state="normal", text="🔍  SCAN")
        self._status.configure(text=f"⚠ {msg}", text_color=C_RED)

    def _track_all(self):
        if not self._results:
            return
        from utils.database import track_value_bet
        tracked = 0
        for r in self._results:
            bid = track_value_bet(
                value_result = r["value_result"],
                kelly_result = r["kelly_result"],
                match_info   = {
                    "event_id":   r["event"].get("id", ""),
                    "match_date": r["date"],
                    "home_team":  r["event"]["home_team"],
                    "away_team":  r["event"]["away_team"],
                    "bet_type":   r["market"],
                },
                league = r["league"],
            )
            if bid > 0:
                tracked += 1
        messagebox.showinfo("Tracking", f"✓ {tracked} value bets αποθηκεύτηκαν!")
        self.app.frames["history"].refresh()


# ═══════════════════════════════════════════════════════════════════════════════
#  LIVE FRAME
# ═══════════════════════════════════════════════════════════════════════════════
class LiveFrame(ctk.CTkFrame):
    def __init__(self, parent, app):
        super().__init__(parent, corner_radius=12, fg_color=C_CARD)
        self.app       = app
        self._polling  = False
        self._thread   = None
        self._stop_evt = threading.Event()
        self._build()

    def _build(self):
        # ── Header ────────────────────────────────────────────────────────────
        hdr = ctk.CTkFrame(self, fg_color="transparent")
        hdr.pack(fill="x", padx=20, pady=(16, 4))
        ctk.CTkLabel(hdr, text="Live Monitor",
                     font=ctk.CTkFont(size=22, weight="bold")).pack(side="left")
        self._dot = ctk.CTkLabel(hdr, text="⬤  OFFLINE",
                                  font=ctk.CTkFont(size=12), text_color=C_DIM)
        self._dot.pack(side="left", padx=16)

        # ── Controls row 1: mode + league ────────────────────────────────────
        ctrl = ctk.CTkFrame(self, fg_color="transparent")
        ctrl.pack(fill="x", padx=20, pady=(8, 2))

        self._auto_var = ctk.BooleanVar(value=True)
        self._auto_sw  = ctk.CTkSwitch(
            ctrl, text="Auto (All Leagues)", variable=self._auto_var,
            font=ctk.CTkFont(size=13), command=self._on_mode_toggle,
            onvalue=True, offvalue=False,
        )
        self._auto_sw.pack(side="left", padx=(0, 16))

        self._league_lbl = ctk.CTkLabel(ctrl, text="Πρωτάθλημα:",
                                         font=ctk.CTkFont(size=13))
        self._league_lbl.pack(side="left")
        from scrapers.odds_api import SPORT_KEYS
        self._sport_var = ctk.StringVar(value="super_league")
        self._sport_cb  = ctk.CTkComboBox(ctrl, values=list(SPORT_KEYS.keys()),
                                           variable=self._sport_var, width=200,
                                           font=ctk.CTkFont(size=12))
        self._sport_cb.pack(side="left", padx=(8, 0))

        # Tier limit for auto mode
        self._tier_lbl = ctk.CTkLabel(ctrl, text="  Max Tier:",
                                       font=ctk.CTkFont(size=13))
        self._tier_lbl.pack(side="left")
        self._tier_var = ctk.StringVar(value="2")
        self._tier_cb  = ctk.CTkComboBox(ctrl, values=["1", "2", "3"],
                                          variable=self._tier_var, width=60,
                                          font=ctk.CTkFont(size=12))
        self._tier_cb.pack(side="left", padx=(4, 0))

        # Apply initial state (auto mode = hide league selector)
        self._on_mode_toggle()

        # ── Controls row 2: interval + buttons ───────────────────────────────
        ctrl2 = ctk.CTkFrame(self, fg_color="transparent")
        ctrl2.pack(fill="x", padx=20, pady=(2, 8))

        ctk.CTkLabel(ctrl2, text="Interval (s):", font=ctk.CTkFont(size=13)).pack(side="left")
        self._interval_var = ctk.StringVar(value="120")
        ctk.CTkEntry(ctrl2, textvariable=self._interval_var,
                     width=70, font=ctk.CTkFont(size=12)).pack(side="left", padx=(6, 16))

        self._start_btn = ctk.CTkButton(
            ctrl2, text="▶  Start Polling", command=self._start,
            width=150, height=38, font=ctk.CTkFont(size=13, weight="bold"),
            fg_color=C_GREEN, hover_color="#009e7f", text_color="black",
        )
        self._start_btn.pack(side="left")

        self._stop_btn = ctk.CTkButton(
            ctrl2, text="■  Stop", command=self._stop,
            width=100, height=38, font=ctk.CTkFont(size=13),
            fg_color=C_RED, hover_color="#b71c1c",
            state="disabled",
        )
        self._stop_btn.pack(side="left", padx=10)

        self._clear_btn = ctk.CTkButton(
            ctrl2, text="🗑  Clear", command=self._clear_log,
            width=90, height=38, font=ctk.CTkFont(size=12),
            fg_color="#2d2d44", hover_color="#3d3d5c",
        )
        self._clear_btn.pack(side="left")

        # ── Live table ────────────────────────────────────────────────────────
        cols = {
            "time":      ("Ώρα",          58, "center"),
            "match":     ("Αγώνας",      185, "w"),
            "score":     ("Σκορ",         50, "center"),
            "minute":    ("Λεπτό",        50, "center"),
            "market":    ("Αγορά",        82, "center"),
            "live_p":    ("Live Prob",    78, "center"),
            "shots":     ("SoT",          60, "center"),
            "corners":   ("Corners",      68, "center"),
            "poss":      ("Poss%",        60, "center"),
            "bookmaker": ("Bookmaker",   110, "center"),
            "odds":      ("Odds",         62, "center"),
            "edge":      ("Edge",         62, "center"),
            "status":    ("Status",      105, "center"),
        }
        tbl = ctk.CTkFrame(self, fg_color=C_TREE_BG, corner_radius=8)
        tbl.pack(fill="both", expand=True, padx=20, pady=(0, 16))

        self._tree, sb = _make_tree(tbl, cols, "LV")
        self._tree.pack(side="left", fill="both", expand=True, padx=(6, 0), pady=6)
        sb.pack(side="right", fill="y", pady=6, padx=(0, 4))
        # HIGH CONF! = magenta row (edge + shots on target >= 3)
        self._tree.tag_configure("highconf",
                                  foreground="#e056fd",
                                  font=("Segoe UI", 11, "bold"),
                                  background="#1a0026")

        # ── Log / alerts area ─────────────────────────────────────────────────
        self._log = ctk.CTkTextbox(self, height=110, corner_radius=8,
                                    font=ctk.CTkFont(family="Consolas", size=11),
                                    fg_color="#0d0d1a", text_color=C_TEXT)
        self._log.pack(fill="x", padx=20, pady=(0, 16))
        self._log_msg("Σύστημα έτοιμο. Πάτα 'Start Polling' για να ξεκινήσει η παρακολούθηση.")

    # ── Mode toggle ───────────────────────────────────────────────────────────
    def _on_mode_toggle(self):
        auto = self._auto_var.get()
        state = "disabled" if auto else "normal"
        self._sport_cb.configure(state=state)
        self._league_lbl.configure(text_color=C_DIM if auto else C_TEXT)
        self._tier_cb.configure(state="normal" if auto else "disabled")
        self._tier_lbl.configure(text_color=C_TEXT if auto else C_DIM)

    # ── Polling ───────────────────────────────────────────────────────────────
    def _start(self):
        if self._polling:
            return
        self._polling = True
        self._stop_evt.clear()
        self._start_btn.configure(state="disabled")
        self._stop_btn.configure(state="normal")

        auto     = self._auto_var.get()
        interval = int(self._interval_var.get() or "120")
        mode_lbl = "ALL LEAGUES" if auto else self._sport_var.get().upper()
        self._dot.configure(text=f"⬤  LIVE — {mode_lbl}", text_color=C_GREEN)

        if auto:
            max_tier = int(self._tier_var.get() or "2")
            self._thread = threading.Thread(
                target=self._poll_loop_auto, args=(interval, max_tier), daemon=True
            )
        else:
            from scrapers.odds_api import SPORT_KEYS
            sport_key = SPORT_KEYS.get(self._sport_var.get(), "soccer_greece_super_league")
            self._thread = threading.Thread(
                target=self._poll_loop, args=(sport_key, interval), daemon=True
            )
        self._thread.start()

    def _stop(self):
        self._stop_evt.set()
        self._polling = False
        self._start_btn.configure(state="normal")
        self._stop_btn.configure(state="disabled")
        self._dot.configure(text="⬤  OFFLINE", text_color=C_DIM)
        self._log_msg("Polling σταμάτησε.")

    def _poll_loop(self, sport_key: str, interval: int):
        import time
        iteration = 0
        while not self._stop_evt.is_set():
            iteration += 1
            self.app.q(lambda i=iteration: self._log_msg(
                f"[Scan #{i}] {datetime.now().strftime('%H:%M:%S')} — σάρωση {sport_key}..."
            ))
            try:
                from scrapers.live_scanner import scan_once
                results = scan_once(sport_key)
                self.app.q(lambda r=results, i=iteration: self._update_live(r, i))
            except Exception as e:
                self.app.q(lambda err=str(e): self._log_msg(f"⚠ Error: {err}"))

            self._stop_evt.wait(interval)

    def _poll_loop_auto(self, interval: int, max_tier: int):
        iteration = 0
        while not self._stop_evt.is_set():
            iteration += 1
            self.app.q(lambda i=iteration: self._log_msg(
                f"[Auto #{i}] {datetime.now().strftime('%H:%M:%S')} — σάρωση όλων των leagues (tier ≤ {max_tier})..."
            ))
            try:
                from scrapers.live_scanner import scan_all_live
                results = scan_all_live(max_tier=max_tier)
                self.app.q(lambda r=results, i=iteration: self._update_live(r, i))
            except Exception as e:
                self.app.q(lambda err=str(e): self._log_msg(f"⚠ Error: {err}"))

            self._stop_evt.wait(interval)

    def _update_live(self, results: list, iteration: int):
        # Keep value rows pinned; remove non-value rows between scans
        for item in self._tree.get_children():
            vals = self._tree.item(item, "values")
            if len(vals) >= 13 and vals[12] not in ("VALUE!", "HIGH CONF!"):
                self._tree.delete(item)

        now_str = datetime.now().strftime("%H:%M")

        if not results:
            self._log_msg("→ Δεν υπάρχουν in-play αγώνες αυτή τη στιγμή.")
            return

        self._log_msg(f"→ {len(results)} in-play αγώνες:")
        for r in results:
            league_tag = f" [{r['league']}]" if r.get("league") else ""
            match_name = f"{r['home_team']} vs {r['away_team']}{league_tag}"
            score      = f"{r['home_score']}-{r['away_score']}"
            minute_n   = r.get("minute", 0)
            minute_str = f"{minute_n}'"

            # Live stats (populated only when value was found)
            stats  = r.get("live_stats") or {}
            shots  = stats.get("shots_str", "—")
            corners = stats.get("corners_str", "—")
            poss   = stats.get("possession_str", "—")
            sot    = stats.get("shots_ot_total", 0)

            def _status(is_value: bool) -> str:
                if not is_value:
                    return "—"
                return "HIGH CONF!" if sot >= 3 else "VALUE!"

            def _tag(is_value: bool) -> str:
                if not is_value:
                    return "alt"
                return "highconf" if sot >= 3 else "value"

            # Helper: build one row tuple (13 values)
            def _row(now, name, sc, mn, mkt, prob, sh, cor, ps, bm, odds, edge, status):
                return (now, name, sc, mn, mkt, prob, sh, cor, ps, bm, odds, edge, status)

            # ── Row 1: Over 2.5 ───────────────────────────────────────────
            live_p = f"{r['live_over_prob']:.1%}" if r.get("live_over_prob") else "—"
            vbets  = r.get("value_bets", [])
            if vbets:
                for vb in vbets:
                    st  = _status(True)
                    tag = _tag(True)
                    vals = _row(
                        now_str, match_name, score, minute_str,
                        "Over 2.5", live_p, shots, corners, poss,
                        vb["bookmaker"], vb["bookmaker_odds"],
                        f"{vb['value_edge']*100:+.1f}%", st,
                    )
                    self._tree.insert("", 0, tags=(tag,), values=vals)
                    self._log_msg(
                        f"  {'★ HIGH CONF' if st == 'HIGH CONF!' else '🔔 VALUE'}: "
                        f"{match_name} [{minute_str}] Over 2.5 @{vb['bookmaker_odds']} "
                        f"({vb['bookmaker']}) edge={vb['value_edge_pct']}"
                        + (f" | SoT={shots}" if stats else "")
                    )
            else:
                self._tree.insert("", "end", tags=("alt",), values=_row(
                    now_str, match_name, score, minute_str,
                    "Over 2.5", live_p, "—", "—", "—", "—", "—", "—", "—",
                ))

            # ── Rows 2-3: HT markets (1st half only) ──────────────────────
            if minute_n <= 45:
                for ht_label, prob_key, bets_key in [
                    ("O0.5 HT", "ht_05_prob", "ht_05_bets"),
                    ("O1.5 HT", "ht_15_prob", "ht_15_bets"),
                ]:
                    ht_prob  = r.get(prob_key)
                    ht_p     = f"{ht_prob:.1%}" if ht_prob is not None else "—"
                    ht_bets  = r.get(bets_key, [])
                    sub_name = f"  ↳ {ht_label}"
                    if ht_bets:
                        for vb in ht_bets:
                            st  = _status(True)
                            tag = _tag(True)
                            vals = _row(
                                "", sub_name, "", "",
                                ht_label, ht_p, shots, corners, poss,
                                vb["bookmaker"], vb["bookmaker_odds"],
                                f"{vb['value_edge']*100:+.1f}%", st,
                            )
                            self._tree.insert("", 0, tags=(tag,), values=vals)
                            self._log_msg(
                                f"  {'★ HIGH CONF' if st == 'HIGH CONF!' else '⚡ HT VALUE'}: "
                                f"{match_name} [{minute_str}] {ht_label} @{vb['bookmaker_odds']} "
                                f"({vb['bookmaker']}) edge={vb['value_edge_pct']}"
                                + (f" | SoT={shots}" if stats else "")
                            )
                    else:
                        self._tree.insert("", "end", tags=("alt",), values=_row(
                            "", sub_name, "", "",
                            ht_label, ht_p, "—", "—", "—", "—", "—", "—", "—",
                        ))

    def _log_msg(self, msg: str):
        self._log.configure(state="normal")
        self._log.insert("end", f"{msg}\n")
        self._log.see("end")
        self._log.configure(state="disabled")

    def _clear_log(self):
        self._log.configure(state="normal")
        self._log.delete("1.0", "end")
        self._log.configure(state="disabled")
        for i in self._tree.get_children():
            self._tree.delete(i)


# ═══════════════════════════════════════════════════════════════════════════════
#  AI TIPSTER FRAME
# ═══════════════════════════════════════════════════════════════════════════════
class TipsterFrame(ctk.CTkFrame):
    def __init__(self, parent, app):
        super().__init__(parent, corner_radius=12, fg_color=C_CARD)
        self.app        = app
        self._picks     = []
        self._watchlist = []
        self._wl_inner  = None   # recreated on each update_watchlist() call
        self._build()

    def _build(self):
        # ── Header ────────────────────────────────────────────────────────────
        hdr = ctk.CTkFrame(self, fg_color="transparent")
        hdr.pack(fill="x", padx=20, pady=(16, 4))

        ctk.CTkLabel(hdr, text="AI Tipster",
                     font=ctk.CTkFont(size=22, weight="bold")).pack(side="left")
        ctk.CTkLabel(hdr, text="High Probability Selections",
                     font=ctk.CTkFont(size=12), text_color=C_DIM).pack(side="left", padx=12)

        self._update_lbl = ctk.CTkLabel(hdr, text="",
                                         font=ctk.CTkFont(size=11), text_color=C_DIM)
        self._update_lbl.pack(side="right")

        # ── Info banner ───────────────────────────────────────────────────────
        info = ctk.CTkFrame(self, fg_color="#0d0d1a", corner_radius=8)
        info.pack(fill="x", padx=20, pady=(0, 10))
        ctk.CTkLabel(
            info,
            text=(
                "ℹ  Τρέξε το Pre-game Scan (Tab 1) για να γεμίσουν τα picks  ·  "
                "Αποδόσεις ≥ 1.40  ·  Combo = Win + Over 2.5 για καλύτερη απόδοση"
            ),
            font=ctk.CTkFont(size=11), text_color=C_DIM,
        ).pack(pady=7, padx=14)

        # ── Watch Live Today section ──────────────────────────────────────────
        wl_hdr = ctk.CTkFrame(self, fg_color="transparent")
        wl_hdr.pack(fill="x", padx=20, pady=(0, 4))
        ctk.CTkLabel(wl_hdr, text="Watch Live Today",
                     font=ctk.CTkFont(size=15, weight="bold"),
                     text_color="#00b894").pack(side="left")
        ctk.CTkLabel(wl_hdr, text="  — αγώνες με το υψηλότερο HT betting potential",
                     font=ctk.CTkFont(size=11), text_color=C_DIM).pack(side="left")

        self._wl_frame = ctk.CTkFrame(self, fg_color="#0d0d1a", corner_radius=8, height=110)
        self._wl_frame.pack(fill="x", padx=20, pady=(0, 12))
        self._wl_frame.pack_propagate(False)

        self._wl_empty = ctk.CTkLabel(
            self._wl_frame,
            text="Τρέξε Pre-game Scan για να εμφανιστούν οι αγώνες της ημέρας",
            font=ctk.CTkFont(size=11), text_color=C_DIM,
        )
        self._wl_empty.pack(expand=True)

        # ── Tier legend ───────────────────────────────────────────────────────
        legend = ctk.CTkFrame(self, fg_color="transparent")
        legend.pack(fill="x", padx=20, pady=(0, 8))
        for label, color, desc in [
            ("LOCK",       "#00b894", "≥ 88% — Σιδερένιο"),
            ("STRONG",     "#fdcb6e", "78–88% — Δυνατό"),
            ("VALUE PLAY", "#74b9ff", "68–78% — Καλή επιλογή"),
            ("COMBO",      "#e17055", "Win + O2.5 — Απόδοση ≥ 1.40"),
        ]:
            pill = ctk.CTkFrame(legend, fg_color="#1e1e30", corner_radius=6)
            pill.pack(side="left", padx=4)
            ctk.CTkLabel(pill, text=f"  {label}  ",
                         font=ctk.CTkFont(size=11, weight="bold"),
                         text_color=color).pack(side="left")
            ctk.CTkLabel(pill, text=f"{desc}  ",
                         font=ctk.CTkFont(size=10), text_color=C_DIM).pack(side="left")

        # ── Scrollable picks cards area ───────────────────────────────────────
        self._scroll = ctk.CTkScrollableFrame(self, fg_color="transparent")
        self._scroll.pack(fill="both", expand=True, padx=20, pady=(0, 16))

        self._empty_lbl = ctk.CTkLabel(
            self._scroll,
            text="Δεν υπάρχουν picks ακόμα.\nΤρέξε το Pre-game Scan (Tab 1) πρώτα.",
            font=ctk.CTkFont(size=14), text_color=C_DIM,
        )
        self._empty_lbl.pack(pady=80)

    # ── Public API ────────────────────────────────────────────────────────────
    def update_picks(self, picks: list):
        """Called automatically after pre-game scan completes."""
        self._picks = picks
        for w in self._scroll.winfo_children():
            w.destroy()

        if not picks:
            ctk.CTkLabel(
                self._scroll,
                text="Κανένα pick δεν πληροί τα κριτήρια σήμερα.\n"
                     "(Χρειάζεται Confidence ≥ 68% + διαθέσιμες αποδόσεις)",
                font=ctk.CTkFont(size=13), text_color=C_DIM,
            ).pack(pady=60)
            self._update_lbl.configure(text="")
            return

        self._update_lbl.configure(
            text=f"Ενημερώθηκε: {datetime.now().strftime('%H:%M')}  |  {len(picks)} picks"
        )
        for pick in picks:
            self._make_card(pick)

    def update_watchlist(self, games: list):
        """Called after pre-game scan with scored watchlist games."""
        self._watchlist = games

        # Destroy only the previously created inner widget (not CTkFrame internals)
        if self._wl_inner is not None:
            try:
                self._wl_inner.destroy()
            except Exception:
                pass
            self._wl_inner = None

        if not games:
            self._wl_inner = ctk.CTkLabel(
                self._wl_frame,
                text="Δεν βρέθηκαν αγώνες με επαρκή HT potential σήμερα.",
                font=ctk.CTkFont(size=11), text_color=C_DIM,
            )
            self._wl_inner.pack(expand=True)
            return

        # Horizontal scrollable strip of mini-cards
        strip = ctk.CTkScrollableFrame(
            self._wl_frame, fg_color="transparent",
            orientation="horizontal", height=95,
        )
        strip.pack(fill="both", expand=True, padx=8, pady=6)
        self._wl_inner = strip

        for g in games:
            self._make_watchlist_card(strip, g)

    def _make_watchlist_card(self, parent, game):
        color = game.rating_color
        card  = ctk.CTkFrame(
            parent, fg_color="#1a1a2e", corner_radius=10,
            border_width=2, border_color=color, width=190,
        )
        card.pack(side="left", padx=6, pady=4)
        card.pack_propagate(False)

        # Rating pill (top)
        pill = ctk.CTkFrame(card, fg_color=color, corner_radius=4)
        pill.pack(fill="x", padx=8, pady=(6, 3))
        ctk.CTkLabel(
            pill,
            text=f"  {game.rating}  {game.kickoff_time}  ",
            font=ctk.CTkFont(size=9, weight="bold"),
            text_color="black",
        ).pack()

        # Match name
        abbr = LEAGUE_ABBREV.get(game.league, game.league[:4].upper())
        ctk.CTkLabel(
            card,
            text=f"[{abbr}]  {game.home_team[:10]} vs {game.away_team[:10]}",
            font=ctk.CTkFont(size=10, weight="bold"),
            text_color=C_TEXT,
        ).pack(padx=8, pady=(2, 1))

        # Stats row
        ht_str  = f"{game.ht_05_prob:.0%}" if game.ht_05_prob is not None else "—"
        ou_str  = f"{game.over_25_prob:.0%}"
        ctk.CTkLabel(
            card,
            text=f"HT O0.5: {ht_str}   O2.5: {ou_str}",
            font=ctk.CTkFont(size=9), text_color=C_DIM,
        ).pack(padx=8, pady=(1, 6))

    def _make_card(self, pick):
        from models.tipster import TIER_COLORS
        tier_color = pick.tier_color

        card = ctk.CTkFrame(
            self._scroll,
            fg_color="#1a1a2e",
            corner_radius=10,
            border_width=2,
            border_color=tier_color,
        )
        card.pack(fill="x", pady=5)
        card.grid_columnconfigure(1, weight=1)

        # ── Left: confidence badge ─────────────────────────────────────────
        badge = ctk.CTkFrame(card, fg_color="#0d0d1a", corner_radius=8, width=96)
        badge.grid(row=0, column=0, rowspan=3, padx=(12, 0), pady=12, sticky="ns")
        badge.grid_propagate(False)

        ctk.CTkLabel(badge, text=pick.confidence_pct,
                     font=ctk.CTkFont(size=28, weight="bold"),
                     text_color=tier_color).pack(expand=True, pady=(12, 4))

        tier_pill = ctk.CTkFrame(badge, fg_color=tier_color, corner_radius=4)
        tier_pill.pack(padx=8, pady=(0, 12), fill="x")
        ctk.CTkLabel(tier_pill, text=pick.tier,
                     font=ctk.CTkFont(size=9, weight="bold"),
                     text_color="black").pack()

        # ── Right: details ─────────────────────────────────────────────────
        # Row 1: Match name + date
        abbr       = LEAGUE_ABBREV.get(pick.league, pick.league[:4].upper())
        match_text = f"[{abbr}]  {pick.match}"
        r1 = ctk.CTkFrame(card, fg_color="transparent")
        r1.grid(row=0, column=1, padx=12, pady=(10, 2), sticky="w")
        ctk.CTkLabel(r1, text=match_text,
                     font=ctk.CTkFont(size=14, weight="bold"),
                     text_color=C_TEXT).pack(side="left")
        ctk.CTkLabel(r1, text=f"  {pick.date}",
                     font=ctk.CTkFont(size=11), text_color=C_DIM).pack(side="left")

        # Row 2: Market + odds
        r2 = ctk.CTkFrame(card, fg_color="transparent")
        r2.grid(row=1, column=1, padx=12, pady=2, sticky="w")
        ctk.CTkLabel(r2, text=f"Αγορά:  {pick.market}",
                     font=ctk.CTkFont(size=13, weight="bold"),
                     text_color="#74b9ff").pack(side="left")
        if pick.best_odds > 1.0:
            ctk.CTkLabel(r2,
                         text=f"     @{pick.best_odds:.2f}   {pick.best_bookmaker}",
                         font=ctk.CTkFont(size=12), text_color=C_YELLOW).pack(side="left")

        # Row 3: Signal badges
        r3 = ctk.CTkFrame(card, fg_color="transparent")
        r3.grid(row=2, column=1, padx=12, pady=(2, 10), sticky="w")
        for sig in pick.signals:
            b = ctk.CTkFrame(r3, fg_color="#252540", corner_radius=4)
            b.pack(side="left", padx=(0, 5))
            ctk.CTkLabel(b, text=f"  ✓ {sig}  ",
                         font=ctk.CTkFont(size=10), text_color="#a0aec0").pack()


# ═══════════════════════════════════════════════════════════════════════════════
#  HISTORY & PnL FRAME
# ═══════════════════════════════════════════════════════════════════════════════
class HistoryFrame(ctk.CTkFrame):
    def __init__(self, parent, app):
        super().__init__(parent, corner_radius=12, fg_color=C_CARD)
        self.app = app
        self._build()
        self.refresh()

    def _build(self):
        # ── Header ────────────────────────────────────────────────────────────
        hdr = ctk.CTkFrame(self, fg_color="transparent")
        hdr.pack(fill="x", padx=20, pady=(16, 4))
        ctk.CTkLabel(hdr, text="History & PnL",
                     font=ctk.CTkFont(size=22, weight="bold")).pack(side="left")
        ctk.CTkButton(hdr, text="⟳  Refresh", command=self.refresh,
                      width=110, height=32, font=ctk.CTkFont(size=12),
                      fg_color="#2d2d44", hover_color="#3d3d5c").pack(side="right")

        # ── KPI Cards ─────────────────────────────────────────────────────────
        kpi_row = ctk.CTkFrame(self, fg_color="transparent")
        kpi_row.pack(fill="x", padx=20, pady=(4, 12))
        kpi_row.grid_columnconfigure((0,1,2,3,4,5), weight=1)

        self._kpi_widgets = {}
        kpi_defs = [
            ("total",    "Σύνολο Bets",  "—",    C_TEXT),
            ("pending",  "Pending",      "—",    C_YELLOW),
            ("winrate",  "Win Rate",     "—",    C_GREEN),
            ("pnl",      "Total PnL",    "—",    C_GREEN),
            ("roi",      "ROI",          "—",    C_GREEN),
            ("avgedge",  "Avg Edge",     "—",    C_TEXT),
        ]
        for col, (key, label, val, color) in enumerate(kpi_defs):
            card = ctk.CTkFrame(kpi_row, corner_radius=10,
                                fg_color="#1e1e30", border_width=1, border_color="#2d2d50")
            card.grid(row=0, column=col, padx=5, sticky="nsew", ipady=8)
            val_lbl = ctk.CTkLabel(card, text=val,
                                    font=ctk.CTkFont(size=24, weight="bold"),
                                    text_color=color)
            val_lbl.pack(pady=(10, 2))
            ctk.CTkLabel(card, text=label,
                          font=ctk.CTkFont(size=11), text_color=C_DIM).pack(pady=(0, 10))
            self._kpi_widgets[key] = val_lbl

        # ── Action buttons ────────────────────────────────────────────────────
        act = ctk.CTkFrame(self, fg_color="transparent")
        act.pack(fill="x", padx=20, pady=(0, 8))

        ctk.CTkButton(act, text="⚡  Auto-Settle (API)", command=self._auto_settle,
                      width=200, height=36, font=ctk.CTkFont(size=13, weight="bold"),
                      fg_color="#e67e22", hover_color="#ca6f1e").pack(side="left")

        ctk.CTkButton(act, text="✏  Manual Settle", command=self._manual_settle_dialog,
                      width=160, height=36, font=ctk.CTkFont(size=12),
                      fg_color="#2d2d44", hover_color="#3d3d5c").pack(side="left", padx=8)

        self._settle_status = ctk.CTkLabel(act, text="",
                                            font=ctk.CTkFont(size=12), text_color=C_DIM)
        self._settle_status.pack(side="left", padx=10)

        # ── Filter bar ────────────────────────────────────────────────────────
        filt = ctk.CTkFrame(self, fg_color="transparent")
        filt.pack(fill="x", padx=20, pady=(0, 6))
        ctk.CTkLabel(filt, text="Φίλτρο:", font=ctk.CTkFont(size=12)).pack(side="left")
        self._filter_var = ctk.StringVar(value="All")
        for val in ("All", "Pending", "Win", "Loss", "Void"):
            ctk.CTkRadioButton(
                filt, text=val, variable=self._filter_var, value=val,
                command=self.refresh, font=ctk.CTkFont(size=12),
            ).pack(side="left", padx=8)

        # ── Bets table ────────────────────────────────────────────────────────
        cols = {
            "id":       ("#",            40, "center"),
            "date":     ("Ημ/νία",       90, "center"),
            "league":   ("League",      110, "center"),
            "match":    ("Αγώνας",      230, "w"),
            "market":   ("Αγορά",       100, "center"),
            "odds":     ("Odds",         65, "center"),
            "stake":    ("Stake",        80, "center"),
            "score":    ("Σκορ",         65, "center"),
            "pnl":      ("PnL",          80, "center"),
            "status":   ("Status",       80, "center"),
        }
        tbl = ctk.CTkFrame(self, fg_color=C_TREE_BG, corner_radius=8)
        tbl.pack(fill="both", expand=True, padx=20, pady=(0, 16))

        self._tree, sb = _make_tree(tbl, cols, "HI")
        self._tree.pack(side="left", fill="both", expand=True, padx=(6, 0), pady=6)
        sb.pack(side="right", fill="y", pady=6, padx=(0, 4))

    # ── Data ──────────────────────────────────────────────────────────────────
    def refresh(self):
        from utils.database import get_stats, get_all_bets
        s    = get_stats()
        bets = get_all_bets(200)

        # Update KPIs
        total   = s.get("total_bets") or 0
        pending = s.get("pending") or 0
        wins    = s.get("wins") or 0
        losses  = s.get("losses") or 0
        pnl     = s.get("total_pnl") or 0
        roi     = s.get("roi") or 0
        wr      = s.get("win_rate", 0) * 100
        ae      = (s.get("avg_edge") or 0) * 100

        pnl_col = C_GREEN if pnl >= 0 else C_RED
        roi_col = C_GREEN if roi >= 0 else C_RED
        wr_col  = C_GREEN if wr >= 50 else (C_YELLOW if wr >= 35 else C_RED)

        self._kpi_widgets["total"].configure(text=str(total))
        self._kpi_widgets["pending"].configure(text=str(pending))
        self._kpi_widgets["winrate"].configure(
            text=f"{wr:.1f}%  ({wins}W/{losses}L)", text_color=wr_col)
        self._kpi_widgets["pnl"].configure(
            text=f"€{pnl:+.2f}", text_color=pnl_col)
        self._kpi_widgets["roi"].configure(
            text=f"{roi:+.1f}%", text_color=roi_col)
        self._kpi_widgets["avgedge"].configure(text=f"{ae:.1f}%")

        # Filter & repopulate table
        filt = self._filter_var.get()
        for i in self._tree.get_children():
            self._tree.delete(i)

        for b in bets:
            if filt != "All" and b["status"] != filt:
                continue
            pnl_val = b.get("profit_loss") or 0
            score   = (f"{b['final_home_goals']}-{b['final_away_goals']}"
                       if b.get("final_home_goals") is not None else "—")
            tag = {"Win": "win", "Loss": "loss",
                   "Pending": "pending", "Void": "void"}.get(b["status"], "")
            self._tree.insert("", "end", tags=(tag,), values=(
                b["id"],
                b["match_date"],
                b["league"].replace("_", " ").title()[:12],
                f"{b['home_team']} vs {b['away_team']}",
                b["bet_type"],
                b["bookmaker_odds"],
                f"€{b['kelly_stake']:.2f}",
                score,
                f"€{pnl_val:+.2f}" if b["status"] != "Pending" else "—",
                b["status"],
            ))

    # ── Settlement ────────────────────────────────────────────────────────────
    def _auto_settle(self):
        self._settle_status.configure(text="⏳ Fetching results...", text_color=C_YELLOW)
        self.update()
        t = threading.Thread(target=self._auto_settle_worker, daemon=True)
        t.start()

    def _auto_settle_worker(self):
        from utils.database import auto_settle_from_api
        result = auto_settle_from_api()
        self.app.q(lambda r=result: self._settle_done(r))

    def _settle_done(self, result: dict):
        s = result["settled"]
        msg = (f"✓ {s} settled  |  {result['skipped']} skipped  |  {result['errors']} errors")
        col = C_GREEN if s > 0 else C_DIM
        self._settle_status.configure(text=msg, text_color=col)
        self.refresh()

    def _manual_settle_dialog(self):
        from utils.database import get_pending_bets, manual_settle
        pending = get_pending_bets()
        if not pending:
            messagebox.showinfo("Manual Settle", "Δεν υπάρχουν Pending bets.")
            return

        dlg = ctk.CTkToplevel(self)
        dlg.title("Manual Settlement")
        dlg.geometry("500x380")
        dlg.resizable(False, False)
        dlg.grab_set()

        ctk.CTkLabel(dlg, text="Επίλεξε bet και εισάγαι σκορ",
                     font=ctk.CTkFont(size=14, weight="bold")).pack(pady=(16, 4))

        # Listbox με pending
        options = [f"#{b['id']}  {b['home_team']} vs {b['away_team']}  [{b['bet_type']}]"
                   for b in pending]
        bet_var = ctk.StringVar(value=options[0])
        combo = ctk.CTkComboBox(dlg, values=options, variable=bet_var, width=440,
                                 font=ctk.CTkFont(size=12))
        combo.pack(padx=20, pady=8)

        score_row = ctk.CTkFrame(dlg, fg_color="transparent")
        score_row.pack(pady=8)
        ctk.CTkLabel(score_row, text="Γκολ γηπεδούχου:").pack(side="left")
        home_ent = ctk.CTkEntry(score_row, width=60, font=ctk.CTkFont(size=14))
        home_ent.pack(side="left", padx=8)
        ctk.CTkLabel(score_row, text=" — ").pack(side="left")
        ctk.CTkLabel(score_row, text="Φιλοξενούμενου:").pack(side="left")
        away_ent = ctk.CTkEntry(score_row, width=60, font=ctk.CTkFont(size=14))
        away_ent.pack(side="left", padx=8)

        result_lbl = ctk.CTkLabel(dlg, text="", font=ctk.CTkFont(size=13))
        result_lbl.pack(pady=6)

        def do_settle():
            sel = bet_var.get()
            bid = int(sel.split()[0].replace("#", ""))
            try:
                hg = int(home_ent.get())
                ag = int(away_ent.get())
            except ValueError:
                result_lbl.configure(text="⚠ Μη έγκυρο σκορ", text_color=C_RED)
                return
            res = manual_settle(bid, hg, ag)
            if "error" in res:
                result_lbl.configure(text=f"⚠ {res['error']}", text_color=C_RED)
            else:
                pnl = res["profit_loss"]
                col = C_GREEN if pnl >= 0 else C_RED
                result_lbl.configure(
                    text=f"{res['status']}  |  PnL: €{pnl:+.2f}", text_color=col)
                self.refresh()

        ctk.CTkButton(dlg, text="✓  Settle", command=do_settle,
                      width=160, height=38, font=ctk.CTkFont(size=13, weight="bold"),
                      fg_color=C_ACCENT).pack(pady=12)
        ctk.CTkButton(dlg, text="Κλείσιμο", command=dlg.destroy,
                      width=120, height=32, fg_color="#2d2d44").pack()


# ═══════════════════════════════════════════════════════════════════════════════
#  MAIN APP
# ═══════════════════════════════════════════════════════════════════════════════
class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title(f"Value Betting Bot  v{_VERSION}")
        self.minsize(1050, 650)
        self.configure(fg_color=C_BG)
        # Center on screen
        self.update_idletasks()
        sw = self.winfo_screenwidth()
        sh = self.winfo_screenheight()
        w, h = min(1280, sw - 40), min(780, sh - 80)
        x = (sw - w) // 2
        y = (sh - h) // 2
        self.geometry(f"{w}x{h}+{x}+{y}")
        self.lift()
        self.focus_force()

        self._queue = queue.Queue()
        self._build()
        self._show("pregame")
        self.after(100, self._drain_queue)

    def q(self, fn):
        """Thread-safe UI update."""
        self._queue.put(fn)

    def _drain_queue(self):
        try:
            while True:
                fn = self._queue.get_nowait()
                try:
                    fn()
                except Exception as e:
                    _log_error("drain_queue callback", e)
        except queue.Empty:
            pass
        self.after(100, self._drain_queue)

    def _build(self):
        # ── Sidebar ───────────────────────────────────────────────────────────
        sb = ctk.CTkFrame(self, width=210, corner_radius=0, fg_color=C_SIDEBAR)
        sb.pack(side="left", fill="y")
        sb.pack_propagate(False)

        ctk.CTkLabel(sb, text="⚽", font=ctk.CTkFont(size=32)).pack(pady=(24, 4))
        ctk.CTkLabel(sb, text="Value Bot",
                     font=ctk.CTkFont(size=18, weight="bold")).pack()
        ctk.CTkLabel(sb, text=f"v{_VERSION}  |  free APIs",
                     font=ctk.CTkFont(size=10), text_color=C_DIM).pack(pady=(2, 20))

        ctk.CTkFrame(sb, height=1, fg_color="#2d2d50").pack(fill="x", padx=16, pady=4)

        nav = [
            ("pregame", "🔍   Pre-game Scan"),
            ("live",    "🔴   Live Monitor"),
            ("tipster", "🤖   AI Tipster"),
            ("history", "📊   History & PnL"),
        ]
        self._nav_btns: dict[str, ctk.CTkButton] = {}
        for key, label in nav:
            btn = ctk.CTkButton(
                sb, text=label, anchor="w",
                command=lambda k=key: self._show(k),
                height=46, corner_radius=8,
                font=ctk.CTkFont(size=13),
                fg_color="transparent", hover_color="#1a1a3a",
            )
            btn.pack(fill="x", padx=12, pady=3)
            self._nav_btns[key] = btn

        ctk.CTkFrame(sb, height=1, fg_color="#2d2d50").pack(fill="x", padx=16, pady=12)

        # Quick stats στο sidebar
        self._sb_pnl = ctk.CTkLabel(sb, text="PnL: —",
                                     font=ctk.CTkFont(size=12), text_color=C_DIM)
        self._sb_pnl.pack(pady=2)
        self._sb_pending = ctk.CTkLabel(sb, text="Pending: —",
                                         font=ctk.CTkFont(size=12), text_color=C_DIM)
        self._sb_pending.pack(pady=2)

        ctk.CTkFrame(sb, height=1, fg_color="#2d2d50").pack(fill="x", padx=16, pady=(10, 6))

        # ── API Credits panel ─────────────────────────────────────────────────
        ctk.CTkLabel(sb, text="API Credits",
                     font=ctk.CTkFont(size=10, weight="bold"),
                     text_color="#636e72").pack()

        self._sb_odds_api    = ctk.CTkLabel(sb, text="Odds API: —",
                                             font=ctk.CTkFont(size=11), text_color=C_DIM)
        self._sb_odds_api.pack(pady=1)
        self._sb_apifootball = ctk.CTkLabel(sb, text="API-Football: —",
                                             font=ctk.CTkFont(size=11), text_color=C_DIM)
        self._sb_apifootball.pack(pady=1)
        self._sb_fdorg       = ctk.CTkLabel(sb, text="Football-Data: —",
                                             font=ctk.CTkFont(size=11), text_color=C_DIM)
        self._sb_fdorg.pack(pady=1)

        self._refresh_sidebar()

        # ── Main area ─────────────────────────────────────────────────────────
        main = ctk.CTkFrame(self, corner_radius=0, fg_color="transparent")
        main.pack(side="right", fill="both", expand=True, padx=12, pady=12)

        self.frames = {
            "pregame": PregameFrame(main, self),
            "live":    LiveFrame(main, self),
            "tipster": TipsterFrame(main, self),
            "history": HistoryFrame(main, self),
        }
        for f in self.frames.values():
            f.place(relx=0, rely=0, relwidth=1, relheight=1)

        self._restore_from_cache()

    def _restore_from_cache(self):
        """Populate all tabs from last_scan.json if it's from today."""
        try:
            from utils.scan_cache import load_scan
            cached = load_scan()
            if not cached:
                return

            # ── Restore Pre-game table ──────────────────────────────────
            pg = self.frames["pregame"]
            rows       = cached.get("rows", [])
            value_rows = [r for r in rows if r.get("is_value")]
            n_leagues  = len(set(r.get("league","") for r in rows))
            multi      = n_leagues > 1
            for i, r in enumerate(rows):
                tag  = "value" if r.get("is_value") else ("alt" if i % 2 else "")
                abbr = LEAGUE_ABBREV.get(r.get("league",""), r.get("league","")[:4].upper())
                match = f"[{abbr}]  {r['match']}" if multi else r["match"]
                pg._tree.insert("", "end", tags=(tag,), values=(
                    match, r.get("date",""), r.get("market",""),
                    f"{r.get('prob',0):.1%}", r.get("bookmaker",""), r.get("odds",""),
                    f"{r.get('edge',0)*100:+.1f}%",
                    f"€{r.get('kelly',0):.2f}" if r.get("is_value") else "—",
                ))
            cnt = len(value_rows)
            pg._status.configure(
                text=f"✓ {cnt} value bets (cached)  |  {len(rows)} αγορές",
                text_color=C_GREEN if cnt else C_DIM,
            )

            # ── Restore Live Targets ──────────────────────────────────
            from models.live_targets import LiveTarget
            targets = []
            for td in cached.get("targets", []):
                try:
                    t = LiveTarget(**td)
                    targets.append(t)
                except Exception:
                    pass
            if targets:
                pg._targets_lbl.configure(text=f"Σημερινά Live Targets  ({len(targets)})")
                for t in targets:
                    tag = {1: "target_high", 2: "target_med", 3: "target_low"}.get(t.priority, "target_low")
                    pg._targets_tree.insert("", "end", tags=(tag,), values=(
                        t.priority_label, t.match, t.target_type,
                        f"{t.key_prob:.1%}",
                        f"{t.current_odds:.2f}" if t.current_odds else "—",
                        t.action,
                    ))

            # ── Restore Tipster picks ──────────────────────────────────
            from models.tipster import TipsterPick
            tipster_picks = []
            for pd in cached.get("tipster_picks", []):
                try:
                    tipster_picks.append(TipsterPick(**pd))
                except Exception:
                    pass
            if tipster_picks:
                self.frames["tipster"].update_picks(tipster_picks)

            # ── Restore Watchlist ──────────────────────────────────────
            from models.watchlist import WatchlistGame
            watchlist_games = []
            for wd in cached.get("watchlist", []):
                try:
                    watchlist_games.append(WatchlistGame(**wd))
                except Exception:
                    pass
            if watchlist_games:
                self.frames["tipster"].update_watchlist(watchlist_games)

            saved_at = cached.get("saved_at", "")[:16].replace("T", " ")
            print(f"[Cache] Restored scan from {saved_at}")
        except Exception as e:
            _log_error("RestoreFromCache", e)

    def _show(self, name: str):
        self.frames[name].tkraise()
        for k, btn in self._nav_btns.items():
            btn.configure(fg_color=C_ACCENT if k == name else "transparent")
        if name == "history":
            self.frames["history"].refresh()
            self._refresh_sidebar()

    def _refresh_sidebar(self):
        # PnL / pending
        try:
            from utils.database import get_stats
            s   = get_stats()
            pnl = s.get("total_pnl") or 0
            pen = s.get("pending") or 0
            col = C_GREEN if pnl >= 0 else C_RED
            self._sb_pnl.configure(text=f"PnL: €{pnl:+.2f}", text_color=col)
            self._sb_pending.configure(text=f"Pending: {pen}", text_color=C_YELLOW if pen else C_DIM)
        except Exception:
            pass

        # API credits
        try:
            from scrapers.odds_api import get_credits
            c   = get_credits()
            rem = c.get("remaining")
            if rem is not None:
                try:
                    rem_i = int(rem)
                    col_o = C_GREEN if rem_i > 200 else (C_YELLOW if rem_i > 50 else C_RED)
                    warn  = "  ⚠ LOW" if rem_i <= 50 else ""
                except (ValueError, TypeError):
                    rem_i, col_o, warn = rem, C_DIM, ""
                self._sb_odds_api.configure(
                    text=f"Odds API: {rem_i} / 500{warn}",
                    text_color=col_o,
                )
        except Exception:
            pass

        try:
            from scrapers.apifootball import get_remaining
            rem_af = get_remaining()
            if rem_af is not None:
                col_af = C_GREEN if rem_af > 30 else (C_YELLOW if rem_af > 10 else C_RED)
                self._sb_apifootball.configure(
                    text=f"API-Football: {rem_af} / 100",
                    text_color=col_af,
                )
        except Exception:
            pass

        try:
            from scrapers.football_data import get_requests_used, DAILY_LIMIT
            used_fd = get_requests_used()
            rem_fd  = DAILY_LIMIT - used_fd
            col_fd  = C_GREEN if rem_fd > 30 else (C_YELLOW if rem_fd > 10 else C_RED)
            self._sb_fdorg.configure(
                text=f"Football-Data: {rem_fd} / {DAILY_LIMIT}",
                text_color=col_fd,
            )
        except Exception:
            pass

        self.after(30_000, self._refresh_sidebar)   # ανανέωση κάθε 30s


# ═══════════════════════════════════════════════════════════════════════════════
#  ENTRY POINT
# ═══════════════════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    from utils.database import init_db
    init_db()
    app = App()
    app.update()   # settle geometry before wizard reads winfo_x/y

    # ── First-run setup wizard (runs before main window is usable) ────────────
    try:
        from setup_wizard import run_if_needed
        run_if_needed(app)
        # Reload .env so keys picked up in wizard are visible to the rest of the app
        load_dotenv(override=True)
    except ImportError:
        pass   # setup_wizard not present in dev without the file
    except Exception as e:
        _log_error("setup_wizard", e)

    # ── Update check (non-blocking, runs in background) ───────────────────────
    def _check_update_bg():
        try:
            from updater import check_for_update, download_update, restart_app, get_local_version
            available, local_ver, remote_ver = check_for_update()
            if not available:
                return

            def _show_update_prompt():
                answer = messagebox.askyesno(
                    "BetBot Update Available",
                    f"A new version is available!\n\n"
                    f"  Current:  v{local_ver}\n"
                    f"  New:      v{remote_ver}\n\n"
                    f"Download and apply update now?\n"
                    f"(The app will restart automatically)",
                    parent=app,
                )
                if not answer:
                    return

                # Show progress window
                prog_win = ctk.CTkToplevel(app)
                prog_win.title("Updating BetBot...")
                prog_win.geometry("400x160")
                prog_win.resizable(False, False)
                prog_win.grab_set()
                prog_win.configure(fg_color="#1a1a2e")
                ctk.CTkLabel(prog_win, text=f"Downloading update v{remote_ver}...",
                             font=("Segoe UI", 13)).pack(pady=(24, 8))
                progress = ctk.CTkProgressBar(prog_win, width=340)
                progress.pack(pady=4)
                progress.set(0)
                file_lbl = ctk.CTkLabel(prog_win, text="",
                                        font=("Segoe UI", 10), text_color="#888")
                file_lbl.pack()

                def _progress_cb(cur, total, fname):
                    progress.set(cur / total)
                    file_lbl.configure(text=fname)
                    prog_win.update()

                import threading
                def _do_download():
                    ok, err = download_update(progress_cb=_progress_cb)
                    prog_win.destroy()
                    if ok:
                        messagebox.showinfo("Update Complete",
                                            f"Updated to v{remote_ver}.\nBetBot will now restart.")
                        restart_app()
                    else:
                        messagebox.showerror("Update Failed",
                                             f"Some files could not be updated:\n{err}\n\n"
                                             f"The app will continue with the current version.")

                threading.Thread(target=_do_download, daemon=True).start()

            app.after(2000, _show_update_prompt)   # wait 2s for main window to settle

        except ImportError:
            pass   # updater.py not present
        except Exception as e:
            _log_error("update_check", e)

    import threading as _threading
    _threading.Thread(target=_check_update_bg, daemon=True).start()

    app.mainloop()
