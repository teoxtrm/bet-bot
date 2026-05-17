"""
Value Betting Bot — GUI v0.4
Dark Mode με customtkinter
python gui.py
"""

import customtkinter as ctk
import tkinter as tk
from tkinter import ttk, messagebox
import threading
import queue
import os
from datetime import datetime
from dotenv import load_dotenv

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
    "premier_league":  "EPL",  "champions_league": "UCL",
    "la_liga":         "ESP",  "bundesliga":        "GER",
    "serie_a":         "ITA",  "ligue_1":           "FRA",
    "eredivisie":      "NED",  "primeira_liga":     "POR",
    "championship":    "CH",   "super_league":      "GRE",
    "europa_league":   "UEL",  "conference":        "UECL",
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
        _league_opts = ["ALL LEAGUES"] + list(SPORT_KEYS.keys())
        self._league_var = ctk.StringVar(value="ALL LEAGUES")
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
            scan_all = (league_key == "ALL LEAGUES")
            # ALL LEAGUES: skip totals_h1 to save 1 credit per league
            markets  = ["h2h", "totals"] if scan_all else ["h2h", "totals", "totals_h1"]
            rows, value_rows, all_targets = [], [], []

            # ── Inner helper: process one league's events ─────────────────
            def _process_league(lkey, sport_key_inner):
                _rows, _vrows, _tgts = [], [], []
                try:
                    events = get_odds(sport_key_inner, markets=markets)
                except Exception:
                    return _rows, _vrows, _tgts

                for ev in events:
                    p_1x2  = get_pinnacle_no_vig_probs(ev)
                    p_ou   = get_pinnacle_no_vig_totals(ev, 2.5)
                    p_ht   = None if scan_all else get_pinnacle_no_vig_ht_totals(ev, 0.5)
                    p_ht15 = None if scan_all else get_pinnacle_no_vig_ht_totals(ev, 1.5)

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
                return _rows, _vrows, _tgts

            # ── Step 1 (ALL LEAGUES): Football-Data.org fixtures pre-fetch ─
            if scan_all:
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
            items = list(SPORT_KEYS.items()) if scan_all else \
                    [(league_key, SPORT_KEYS.get(league_key, "soccer_epl"))]
            total = len(items)

            for idx, (lkey, sport_key) in enumerate(items):
                if scan_all:
                    self.app.q(lambda i=idx, k=lkey, n=total: self._status.configure(
                        text=f"The Odds API [{i+1}/{n}]  {k.replace('_',' ').title()}...",
                        text_color=C_DIM,
                    ))
                r, vr, t = _process_league(lkey, sport_key)
                rows.extend(r)
                value_rows.extend(vr)
                all_targets.extend(t)
                if scan_all and idx < total - 1:
                    _time.sleep(1)

            all_targets = score_targets(all_targets)
            self.app.q(lambda r=rows, vr=value_rows, t=all_targets: self._done(r, vr, t))
        except Exception as e:
            self.app.q(lambda err=str(e): self._error(err))

    def _done(self, rows: list, value_rows: list, targets: list):
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

        # ── Controls ──────────────────────────────────────────────────────────
        ctrl = ctk.CTkFrame(self, fg_color="transparent")
        ctrl.pack(fill="x", padx=20, pady=8)

        ctk.CTkLabel(ctrl, text="Πρωτάθλημα:", font=ctk.CTkFont(size=13)).pack(side="left")
        from scrapers.odds_api import SPORT_KEYS
        self._sport_var = ctk.StringVar(value="super_league")
        ctk.CTkComboBox(ctrl, values=list(SPORT_KEYS.keys()),
                        variable=self._sport_var, width=210,
                        font=ctk.CTkFont(size=12)).pack(side="left", padx=(8, 16))

        ctk.CTkLabel(ctrl, text="Interval (s):", font=ctk.CTkFont(size=13)).pack(side="left")
        self._interval_var = ctk.StringVar(value="120")
        ctk.CTkEntry(ctrl, textvariable=self._interval_var,
                     width=70, font=ctk.CTkFont(size=12)).pack(side="left", padx=(6, 16))

        self._start_btn = ctk.CTkButton(
            ctrl, text="▶  Start Polling", command=self._start,
            width=150, height=38, font=ctk.CTkFont(size=13, weight="bold"),
            fg_color=C_GREEN, hover_color="#009e7f", text_color="black",
        )
        self._start_btn.pack(side="left")

        self._stop_btn = ctk.CTkButton(
            ctrl, text="■  Stop", command=self._stop,
            width=100, height=38, font=ctk.CTkFont(size=13),
            fg_color=C_RED, hover_color="#b71c1c",
            state="disabled",
        )
        self._stop_btn.pack(side="left", padx=10)

        self._clear_btn = ctk.CTkButton(
            ctrl, text="🗑  Clear", command=self._clear_log,
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

    # ── Polling ───────────────────────────────────────────────────────────────
    def _start(self):
        if self._polling:
            return
        self._polling = True
        self._stop_evt.clear()
        self._start_btn.configure(state="disabled")
        self._stop_btn.configure(state="normal")
        self._dot.configure(text="⬤  LIVE", text_color=C_GREEN)

        interval = int(self._interval_var.get() or "120")
        sport    = self._sport_var.get()
        from scrapers.odds_api import SPORT_KEYS
        sport_key = SPORT_KEYS.get(sport, "soccer_greece_super_league")

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
                f"[Scan #{i}] {datetime.now().strftime('%H:%M:%S')} — σάρωση in-play..."
            ))
            try:
                from scrapers.live_scanner import scan_once
                results = scan_once(sport_key)
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
            match_name = f"{r['home_team']} vs {r['away_team']}"
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
        self.title("Value Betting Bot  v0.4")
        self.geometry("1280x780")
        self.minsize(1050, 650)
        self.configure(fg_color=C_BG)

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
                self._queue.get_nowait()()
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
        ctk.CTkLabel(sb, text="v0.4  |  free APIs",
                     font=ctk.CTkFont(size=10), text_color=C_DIM).pack(pady=(2, 20))

        ctk.CTkFrame(sb, height=1, fg_color="#2d2d50").pack(fill="x", padx=16, pady=4)

        nav = [
            ("pregame", "🔍   Pre-game Scan"),
            ("live",    "🔴   Live Monitor"),
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
        self._refresh_sidebar()

        # ── Main area ─────────────────────────────────────────────────────────
        main = ctk.CTkFrame(self, corner_radius=0, fg_color="transparent")
        main.pack(side="right", fill="both", expand=True, padx=12, pady=12)

        self.frames = {
            "pregame": PregameFrame(main, self),
            "live":    LiveFrame(main, self),
            "history": HistoryFrame(main, self),
        }
        for f in self.frames.values():
            f.place(relx=0, rely=0, relwidth=1, relheight=1)

    def _show(self, name: str):
        self.frames[name].tkraise()
        for k, btn in self._nav_btns.items():
            btn.configure(fg_color=C_ACCENT if k == name else "transparent")
        if name == "history":
            self.frames["history"].refresh()
            self._refresh_sidebar()

    def _refresh_sidebar(self):
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
        self.after(30_000, self._refresh_sidebar)   # ανανέωση κάθε 30s


# ═══════════════════════════════════════════════════════════════════════════════
#  ENTRY POINT
# ═══════════════════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    from utils.database import init_db
    init_db()
    app = App()
    app.mainloop()
