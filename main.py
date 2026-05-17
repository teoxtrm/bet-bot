"""
Value Betting Bot v0.3
=======================
python main.py

Modes:
  1. Demo           — value calculation παράδειγμα
  2. Pre-game       — ανάλυση αγώνα (football-data.org / greek_stats + Pinnacle no-vig)
  3. Live Scanner   — polling loop για in-play value bets
  4. Manual         — χειροκίνητη εισαγωγή stats & αποδόσεων
  5. Value Scan     — σάρωση ΟΛΩΝ των αγώνων ενός πρωταθλήματος
  6. Update Stats   — ενημέρωση Greek Super League stats cache
  q. Έξοδος
"""

import os, sys
from rich.console import Console
from rich.prompt import Prompt, IntPrompt, FloatPrompt
from rich.panel import Panel
from rich.table import Table
from rich import box
from dotenv import load_dotenv

load_dotenv()

from models.value_calculator import calculate_value, kelly_criterion, compare_bookmakers
from models.pregame_model import calculate_pregame_probs, TeamStats
from models.live_model import live_over_probability
from scrapers.odds_api import (
    get_odds, get_live_odds, find_match_odds,
    get_available_sports, get_pinnacle_no_vig_probs,
    get_pinnacle_no_vig_totals, SPORT_KEYS,
)
from scrapers.football_data import get_upcoming_matches, get_team_stats, COMPETITIONS
from scrapers import greek_stats
from scrapers.live_scanner import run_live_loop, scan_once, get_live_scores
from utils.helpers import (
    console, print_value_bet, print_comparison_table, print_pregame_probs,
)

BANKROLL = float(os.getenv("BANKROLL", "1000"))

# Leagues που έχουν football-data.org stats
FD_LEAGUES = set(COMPETITIONS.keys()) - {"super_league"}


# ─── HELPERS ─────────────────────────────────────────────────────────────────

def check_env():
    missing = []
    if not os.getenv("ODDS_API_KEY"):
        missing.append("ODDS_API_KEY  →  https://the-odds-api.com")
    if missing:
        console.print(Panel(
            "\n".join(["[yellow]Λείπουν API keys:[/yellow]", *[f"  • {k}" for k in missing],
                       "", "Βάλτα στο αρχείο [cyan].env[/cyan]"]),
            title="[red]Setup[/red]"
        ))
        return False
    return True


def _pick_league(prompt: str = "Επίλεξε πρωτάθλημα") -> tuple[str, str]:
    """Επιστρέφει (league_key, sport_key)."""
    all_leagues = list(SPORT_KEYS.keys())
    console.print(f"\n{prompt}:")
    for i, k in enumerate(all_leagues, 1):
        has_stats = "[green](stats)[/green]" if k in FD_LEAGUES else "[dim](Pinnacle only)[/dim]"
        console.print(f"  [cyan]{i:2}[/cyan]. {k.replace('_',' ').title():25s} {has_stats}")
    idx = IntPrompt.ask("Αριθμός", default=1) - 1
    league_key = all_leagues[idx] if 0 <= idx < len(all_leagues) else "premier_league"
    sport_key  = SPORT_KEYS[league_key]
    return league_key, sport_key


# ─── MODE 1: DEMO ─────────────────────────────────────────────────────────────

def run_demo():
    console.rule("[bold blue]DEMO: Value Bet Υπολογιστής")
    console.print("\n[bold]Παράδειγμα:[/bold] Ολυμπιακός vs Παναθηναϊκός — Over 2.5\n")

    our_prob = 0.60
    odds = {"william_hill": 1.95, "betsson": 2.05, "sport888": 1.90, "betway": 2.10}
    console.print(f"Πιθανότητά μας: [cyan]{our_prob:.0%}[/cyan]  |  Αποδόσεις: {odds}\n")

    comparisons = compare_bookmakers(our_prob, odds)
    print_comparison_table("Ολυμπιακός vs Παναθηναϊκός", "Over 2.5", comparisons)
    best  = comparisons[0]
    kelly = kelly_criterion(our_prob, best["bookmaker_odds"], BANKROLL)
    print_value_bet("Ολυμπιακός vs Παναθηναϊκός", "Over 2.5", best, kelly)

    console.print("\n[dim]Value Edge = (Πιθανότητά μας × Απόδοση) - 1[/dim]")
    console.print(f"[dim]= ({our_prob} × {best['bookmaker_odds']}) - 1 = [bold]{best['value_edge_pct']}[/bold][/dim]\n")


# ─── MODE 2: PRE-GAME ─────────────────────────────────────────────────────────

def run_pregame():
    console.rule("[bold green]PRE-GAME ANALYSIS")
    if not check_env():
        return

    league_key, sport_key = _pick_league()
    is_greek = (league_key == "super_league")

    # ── Αγώνες ──
    if is_greek:
        # Για Super League χρησιμοποιούμε The Odds API για upcoming
        console.print("\n[dim]Φόρτωση αγώνων Super League από The Odds API...[/dim]")
        events = get_odds(sport_key, markets=["h2h"])
        if not events:
            console.print("[red]Δεν βρέθηκαν αγώνες.[/red]")
            return
        console.print(f"Βρέθηκαν [bold]{len(events)}[/bold] αγώνες:\n")
        for i, e in enumerate(events, 1):
            console.print(f"  [cyan]{i:2}[/cyan]. {e['home_team']} vs {e['away_team']}  [{e['commence'][:10]}]")
        idx = IntPrompt.ask("\nΕπίλεξε αγώνα", default=1) - 1
        if not (0 <= idx < len(events)):
            return
        sel  = events[idx]
        home_name = sel["home_team"]
        away_name = sel["away_team"]
        match_label = f"{home_name} vs {away_name}"

        # Stats από Greek cache
        console.print(f"\n[dim]Stats: {greek_stats.get_cache_summary()}[/dim]")
        home_raw = greek_stats.get_team_stats(home_name)
        away_raw = greek_stats.get_team_stats(away_name)
        if home_raw["games_analyzed"] == 0 or away_raw["games_analyzed"] == 0:
            console.print("[yellow]Ανεπαρκή stats — χρησιμοποιώ Pinnacle no-vig ως μοναδική πηγή πιθανότητας.[/yellow]")
            console.print("[dim]Τρέξε Mode 6 για να ανανεώσεις τα stats.[/dim]")
        event_with_all_odds = find_match_odds(
            get_odds(sport_key, markets=["h2h", "totals"]), home_name, away_name
        )
        _analyze_with_pinnacle(match_label, event_with_all_odds, home_raw, away_raw)

    else:
        # Football-data.org για stats
        console.print(f"\n[dim]Φόρτωση αγώνων {league_key}...[/dim]")
        matches = get_upcoming_matches(league_key)
        if not matches:
            console.print("[yellow]Δεν βρέθηκαν αγώνες.[/yellow]")
            return
        console.print(f"Βρέθηκαν [bold]{len(matches)}[/bold] αγώνες:\n")
        for i, m in enumerate(matches[:12], 1):
            console.print(f"  [cyan]{i:2}[/cyan]. {m['home_team']} vs {m['away_team']}  [{m['date']}]")
        idx = IntPrompt.ask("\nΕπίλεξε αγώνα", default=1) - 1
        if not (0 <= idx < len(matches)):
            return
        match = matches[idx]
        match_label = f"{match['home_team']} vs {match['away_team']}"

        console.print(f"\n[dim]Φόρτωση stats...[/dim]")
        home_raw = get_team_stats(match["home_id"])
        away_raw = get_team_stats(match["away_id"])

        home  = TeamStats(match["home_team"], home_raw["avg_goals_scored"], home_raw["avg_goals_conceded"])
        away  = TeamStats(match["away_team"], away_raw["avg_goals_scored"], away_raw["avg_goals_conceded"])
        probs = calculate_pregame_probs(home, away)
        print_pregame_probs(match_label, probs)

        console.print(f"\n[dim]Φόρτωση αποδόσεων...[/dim]")
        events = get_odds(sport_key, markets=["h2h", "totals"])
        event  = find_match_odds(events, match["home_team"], match["away_team"])
        if event:
            _value_scan_event(match_label, event, probs)
        else:
            console.print("[yellow]Αγώνας δεν βρέθηκε στο Odds API.[/yellow]")


def _analyze_with_pinnacle(match_label: str, event: dict, home_raw: dict, away_raw: dict):
    """Ανάλυση αγώνα χρησιμοποιώντας Pinnacle no-vig ως κύρια πιθανότητα."""
    if not event:
        console.print("[red]Δεν βρέθηκαν αποδόσεις.[/red]")
        return

    p_1x2 = get_pinnacle_no_vig_probs(event)
    p_ou  = get_pinnacle_no_vig_totals(event, 2.5)

    # Εμφάνιση Pinnacle reference
    console.print()
    if p_1x2:
        console.print(
            f"[bold]Pinnacle no-vig 1X2:[/bold] "
            f"Home=[cyan]{p_1x2['home']:.1%}[/cyan] "
            f"Draw=[cyan]{p_1x2['draw']:.1%}[/cyan] "
            f"Away=[cyan]{p_1x2['away']:.1%}[/cyan] "
            f"[dim](margin {p_1x2['pinnacle_margin_pct']}%)[/dim]"
        )
    if p_ou:
        console.print(
            f"[bold]Pinnacle no-vig O{p_ou['point']}:[/bold] "
            f"Over=[cyan]{p_ou['over_prob']:.1%}[/cyan] "
            f"Under=[cyan]{p_ou['under_prob']:.1%}[/cyan] "
            f"[dim](margin {p_ou['pinnacle_margin_pct']}%)[/dim]"
        )

    # Αν έχουμε stats → και Poisson model
    if home_raw["games_analyzed"] > 0 and away_raw["games_analyzed"] > 0:
        from models.pregame_model import calculate_pregame_probs, TeamStats
        home  = TeamStats(match_label.split(" vs ")[0],
                          home_raw["avg_goals_scored"], home_raw["avg_goals_conceded"])
        away  = TeamStats(match_label.split(" vs ")[1],
                          away_raw["avg_goals_scored"], away_raw["avg_goals_conceded"])
        probs = calculate_pregame_probs(home, away)
        print_pregame_probs(match_label, probs)
        _value_scan_event(match_label, event, probs)
    elif p_ou:
        # Pinnacle-only scan
        probs_approx = {"over_2_5": p_ou["over_prob"], "btts_yes": None}
        _value_scan_event(match_label, event, probs_approx, source="Pinnacle no-vig")


def _value_scan_event(match_label: str, event: dict, probs: dict, source: str = "Poisson model"):
    """Σκανάρει όλα τα bookmakers για value."""
    console.print(f"\n[bold]Value Scan[/bold] [dim](πηγή: {source})[/dim]")
    found_any = False

    checks = [
        ("Over 2.5", probs.get("over_2_5"), "totals", "over_2_5"),
        ("Over 1.5", probs.get("over_1_5"), "totals", "over_1_5"),
        ("BTTS Yes", probs.get("btts_yes"), "btts", "yes"),
        ("Home Win", probs.get("over_1_5"), "1x2", "home"),
    ]

    for label, our_prob, mkt, sub in checks:
        if not our_prob:
            continue
        bm_odds = _collect_bm_odds(event, mkt, sub)
        if not bm_odds:
            continue
        comps = compare_bookmakers(our_prob, bm_odds)
        print_comparison_table(match_label, label, comps)
        best = comps[0]
        if best["is_value_bet"]:
            found_any = True
            kelly = kelly_criterion(our_prob, best["bookmaker_odds"], BANKROLL)
            print_value_bet(match_label, label, best, kelly)

    if not found_any:
        console.print("[yellow]Δεν βρέθηκε value bet (threshold 5%).[/yellow]")


def _collect_bm_odds(event: dict, market: str, sub_key: str) -> dict:
    """Συλλέγει αποδόσεις από όλα τα bookmakers για μια αγορά."""
    result = {}
    for bm_key, bm_data in event.get("odds", {}).items():
        if bm_key == "pinnacle":
            continue  # Pinnacle = reference, όχι target
        if market == "totals":
            o = bm_data.get("totals", {}).get(sub_key)
        elif market == "btts":
            o = (bm_data.get("btts") or {}).get("yes")
        else:
            o = (bm_data.get("1x2") or {}).get("home")
        if o:
            result[bm_key] = o
    return result


# ─── MODE 3: LIVE SCANNER ────────────────────────────────────────────────────

def run_live():
    console.rule("[bold red]LIVE SCANNER")
    if not check_env():
        return

    league_key, sport_key = _pick_league("Πρωτάθλημα για live scan")

    console.print("\nΕπιλογές polling:")
    console.print("  [cyan]1[/cyan]. Ένα snapshot τώρα")
    console.print("  [cyan]2[/cyan]. Συνεχής polling (κάθε 2 λεπτά)")
    mode = Prompt.ask("Επιλογή", choices=["1", "2"], default="1")

    if mode == "1":
        results = scan_once(sport_key)
        _print_live_results(results)
    else:
        interval = IntPrompt.ask("Interval (δευτερόλεπτα)", default=120)
        run_live_loop(sport_key, interval_seconds=interval)


def _print_live_results(results: list):
    if not results:
        console.print("[yellow]Δεν υπάρχουν in-play αγώνες αυτή τη στιγμή.[/yellow]")
        return

    console.print(f"\nIn-play: [bold]{len(results)}[/bold] αγώνες\n")
    for r in results:
        score    = f"{r['home_score']}-{r['away_score']}"
        minute   = f"~{r.get('minute', '?')}'"
        live_p   = f"{r['live_over_prob']:.1%}" if r.get("live_over_prob") else "—"
        vbets    = r.get("value_bets", [])

        color = "green" if vbets else "white"
        console.print(
            f"[{color}]{r['home_team']} vs {r['away_team']}[/{color}]  "
            f"[cyan]{score}[/cyan]  [{minute}]  Live O2.5={live_p}"
        )
        for vb in vbets:
            console.print(
                f"  [bold green]>>> VALUE:[/bold green] "
                f"@[yellow]{vb['bookmaker_odds']}[/yellow] "
                f"({vb['bookmaker']}) edge=[green]{vb['value_edge_pct']}[/green]"
            )


# ─── MODE 4: MANUAL ──────────────────────────────────────────────────────────

def run_manual():
    console.rule("[bold]Χειροκίνητη Εισαγωγή")

    home_name     = Prompt.ask("Γηπεδούχος")
    home_scored   = FloatPrompt.ask("Μέσος γκολ που σκοράρει (τελ. 6 αγ.)", default=1.3)
    home_conceded = FloatPrompt.ask("Μέσος γκολ που δέχεται", default=1.1)
    away_name     = Prompt.ask("Φιλοξενούμενος")
    away_scored   = FloatPrompt.ask("Μέσος γκολ που σκοράρει", default=1.1)
    away_conceded = FloatPrompt.ask("Μέσος γκολ που δέχεται", default=1.3)

    home  = TeamStats(home_name, home_scored, home_conceded)
    away  = TeamStats(away_name, away_scored, away_conceded)
    label = f"{home_name} vs {away_name}"

    probs = calculate_pregame_probs(home, away)
    print_pregame_probs(label, probs)

    console.print("\n[bold]Εισαγωγή αποδόσεων[/bold] [dim](Enter για παράλειψη)[/dim]:")
    for mkt_label, our_prob in [("Over 2.5", probs["over_2_5"]), ("BTTS Yes", probs["btts_yes"])]:
        bm_odds = {}
        for bm in ["stoiximan", "bet365", "novibet", "betsson", "william_hill"]:
            val = Prompt.ask(f"  {mkt_label} @ {bm}", default="")
            if val:
                try:
                    bm_odds[bm] = float(val)
                except ValueError:
                    pass
        if bm_odds:
            comps = compare_bookmakers(our_prob, bm_odds)
            print_comparison_table(label, mkt_label, comps)
            if comps[0]["is_value_bet"]:
                kelly = kelly_criterion(our_prob, comps[0]["bookmaker_odds"], BANKROLL)
                print_value_bet(label, mkt_label, comps[0], kelly)


# ─── MODE 5: FULL VALUE SCAN ─────────────────────────────────────────────────

def run_full_scan():
    console.rule("[bold cyan]FULL VALUE SCAN")
    if not check_env():
        return

    league_key, sport_key = _pick_league()
    console.print(f"\n[dim]Σάρωση {league_key}...[/dim]")

    events = get_odds(sport_key, markets=["h2h", "totals"])
    if not events:
        console.print("[red]Δεν βρέθηκαν αγώνες.[/red]")
        return

    console.print(f"[bold]{len(events)}[/bold] αγώνες | Threshold: 5%\n")
    total_value = 0

    for event in events:
        label = f"{event['home_team']} vs {event['away_team']}"
        p_1x2 = get_pinnacle_no_vig_probs(event)
        p_ou  = get_pinnacle_no_vig_totals(event, 2.5)

        if not p_1x2 and not p_ou:
            continue

        checks = []
        if p_ou:
            checks += [
                ("Over 2.5", p_ou["over_prob"],  "totals", "over_2_5"),
                ("Under 2.5", p_ou["under_prob"], "totals", "under_2_5"),
            ]
        if p_1x2:
            checks += [
                ("Home",  p_1x2["home"], "1x2", "home"),
                ("Draw",  p_1x2["draw"], "1x2", "draw"),
                ("Away",  p_1x2["away"], "1x2", "away"),
            ]

        match_values = []
        for mkt_label, our_prob, mkt, sub in checks:
            bm_odds = _collect_bm_odds(event, mkt, sub)
            if not bm_odds:
                continue
            comps = compare_bookmakers(our_prob, bm_odds)
            best  = comps[0]
            if best["is_value_bet"]:
                match_values.append((mkt_label, our_prob, best))

        if match_values:
            console.print(f"[bold]{label}[/bold]  [{event['commence'][:10]}]")
            for mkt_label, our_prob, best in match_values:
                kelly = kelly_criterion(our_prob, best["bookmaker_odds"], BANKROLL)
                console.print(
                    f"  [green]VALUE[/green] {mkt_label:12s} "
                    f"prob=[cyan]{our_prob:.1%}[/cyan]  "
                    f"@[yellow]{best['bookmaker_odds']}[/yellow] "
                    f"({best['bookmaker']})  "
                    f"edge=[green]{best['value_edge_pct']}[/green]  "
                    f"Kelly=€[magenta]{kelly['suggested_bet']}[/magenta]"
                )
                total_value += 1
            console.print()

    if total_value == 0:
        console.print("[yellow]Κανένα value bet σε αυτό το πρωτάθλημα σήμερα.[/yellow]")
    else:
        console.print(f"\n[bold]Σύνολο value bets:[/bold] [green]{total_value}[/green]")


# ─── MODE 6: UPDATE GREEK STATS ──────────────────────────────────────────────

def run_update_greek_stats():
    console.rule("[bold]Update Greek Super League Stats")
    if not check_env():
        return

    console.print(f"\n[dim]Τρέχον cache: {greek_stats.get_cache_summary()}[/dim]")
    added = greek_stats.update_results_cache()

    if added > 0:
        console.print(f"[green]+{added} νέα αποτελέσματα προστέθηκαν![/green]")
    else:
        console.print("[yellow]Δεν υπάρχουν νέα αποτελέσματα (τελευταίες 3 μέρες).[/yellow]")

    console.print(f"[dim]Νέο cache: {greek_stats.get_cache_summary()}[/dim]")

    teams = greek_stats.get_all_teams()
    if teams:
        console.print(f"\n[bold]Stats ανά ομάδα ({len(teams)} ομάδες):[/bold]")
        table = Table(box=box.SIMPLE)
        table.add_column("Ομάδα", style="bold")
        table.add_column("Αγ.", justify="right")
        table.add_column("Avg Scored", justify="right", style="green")
        table.add_column("Avg Conceded", justify="right", style="red")
        for t in teams:
            s = greek_stats.get_team_stats(t)
            table.add_row(t, str(s["games_analyzed"]),
                          f"{s['avg_goals_scored']:.2f}", f"{s['avg_goals_conceded']:.2f}")
        console.print(table)


# ─── MAIN ─────────────────────────────────────────────────────────────────────

def main():
    console.print("\n[bold blue]Value Betting Bot v0.3[/bold blue]\n")
    console.print("  [cyan]1[/cyan]  Demo")
    console.print("  [cyan]2[/cyan]  Pre-game ανάλυση")
    console.print("  [cyan]3[/cyan]  Live Scanner (polling)")
    console.print("  [cyan]4[/cyan]  Manual εισαγωγή")
    console.print("  [cyan]5[/cyan]  Full Value Scan (όλοι οι αγώνες)")
    console.print("  [cyan]6[/cyan]  Update Greek Super League stats")
    console.print("  [cyan]q[/cyan]  Έξοδος\n")

    choice = Prompt.ask("Επιλογή", choices=["1","2","3","4","5","6","q"], default="1")
    {
        "1": run_demo,
        "2": run_pregame,
        "3": run_live,
        "4": run_manual,
        "5": run_full_scan,
        "6": run_update_greek_stats,
    }.get(choice, lambda: sys.exit(0))()


if __name__ == "__main__":
    main()
