"""
Value Betting Bot — Entry Point
================================
Τρέξε: python main.py

Modes:
  1. Demo        — δείχνει πώς λειτουργεί ο υπολογισμός value
  2. Pre-game    — ανάλυση αγώνα από Sofascore stats
  3. Live        — live αναπροσαρμογή πιθανότητας
  4. Compare     — σύγκριση αποδόσεων πολλών bookmakers
"""

import sys
from datetime import date
from rich.console import Console
from rich.prompt import Prompt, IntPrompt, FloatPrompt

from models.value_calculator import calculate_value, kelly_criterion, compare_bookmakers
from models.pregame_model import calculate_pregame_probs, TeamStats
from models.live_model import live_over_probability
from scrapers.sofascore import get_matches_by_date, build_team_stats_from_history, get_live_matches
from scrapers.odds_scraper import get_odds_for_match
from utils.helpers import console, print_value_bet, print_comparison_table, print_pregame_probs

BANKROLL = 1000.0  # Αλλαξέ το στο budget σου


# ─── MODE 1: DEMO ────────────────────────────────────────────────────────────

def run_demo():
    console.rule("[bold blue]DEMO: Value Bet Υπολογιστής")

    console.print("\n[bold]Παράδειγμα:[/bold] Αγώνας Ολυμπιακός vs Παναθηναϊκός")
    console.print("Αγορά: Over 2.5 Goals\n")

    # Υποθετική πιθανότητα δική μας: 60%
    our_prob = 0.60
    # Αποδόσεις στοιχηματικών
    odds = {
        "stoiximan": 1.95,
        "bet365": 2.05,
        "novibet": 1.90,
    }

    console.print(f"Πιθανότητά μας για Over 2.5: [cyan]{our_prob:.0%}[/cyan]")
    console.print(f"Αποδόσεις: {odds}\n")

    comparisons = compare_bookmakers(our_prob, odds)
    print_comparison_table("Ολυμπιακός vs Παναθηναϊκός", "Over 2.5", comparisons)

    # Καλύτερη επιλογή
    best = comparisons[0]
    kelly = kelly_criterion(our_prob, best["bookmaker_odds"], BANKROLL)
    print_value_bet("Ολυμπιακός vs Παναθηναϊκός", "Over 2.5", best, kelly)

    console.print("\n[dim]Εξήγηση:[/dim]")
    console.print("  Value Edge = (Πιθανότητά μας × Απόδοση) - 1")
    console.print(f"  = ({our_prob} × {best['bookmaker_odds']}) - 1 = [bold]{best['value_edge_pct']}[/bold]")
    console.print("  Θετικό edge → υπάρχει value υπέρ μας.\n")


# ─── MODE 2: PRE-GAME ANALYSIS ───────────────────────────────────────────────

def run_pregame():
    console.rule("[bold green]PRE-GAME ANALYSIS")

    today = date.today().isoformat()
    console.print(f"\n[dim]Φόρτωση αγώνων για {today}...[/dim]")

    matches = get_matches_by_date(today)
    if not matches:
        console.print("[red]Δεν βρέθηκαν αγώνες από Sofascore. Δοκίμασε χειροκίνητη εισαγωγή.[/red]")
        run_manual_pregame()
        return

    console.print(f"Βρέθηκαν [bold]{len(matches)}[/bold] αγώνες.\n")
    for i, m in enumerate(matches[:15], 1):
        console.print(f"  {i:2}. {m['home_team']} vs {m['away_team']} [{m.get('tournament', '')}]")

    idx = IntPrompt.ask("\nΕπίλεξε αγώνα (αριθμό)", default=1) - 1
    if not (0 <= idx < len(matches)):
        console.print("[red]Μη έγκυρη επιλογή.[/red]")
        return

    match = matches[idx]
    match_label = f"{match['home_team']} vs {match['away_team']}"
    console.print(f"\n[bold]Ανάλυση:[/bold] {match_label}")

    # Φόρτωση stats από Sofascore
    home_raw = build_team_stats_from_history(match["home_team_id"]) or {}
    away_raw = build_team_stats_from_history(match["away_team_id"]) or {}

    home = TeamStats(
        name=match["home_team"],
        avg_goals_scored=home_raw.get("avg_goals_scored", 1.3),
        avg_goals_conceded=home_raw.get("avg_goals_conceded", 1.1),
    )
    away = TeamStats(
        name=match["away_team"],
        avg_goals_scored=away_raw.get("avg_goals_scored", 1.1),
        avg_goals_conceded=away_raw.get("avg_goals_conceded", 1.3),
    )

    probs = calculate_pregame_probs(home, away)
    print_pregame_probs(match_label, probs)

    # Σύγκριση με bookmaker αποδόσεις
    console.print("\n[bold]Σύγκριση με bookmaker αποδόσεις:[/bold]")
    market_map = {
        "over_2_5": probs["over_2_5"],
        "btts_yes": probs["btts_yes"],
    }

    odds_data = get_odds_for_match(match_label)
    for market, our_prob in market_map.items():
        if market in odds_data and odds_data[market]:
            comparisons = compare_bookmakers(our_prob, odds_data[market])
            print_comparison_table(match_label, market, comparisons)
            if comparisons and comparisons[0]["is_value_bet"]:
                kelly = kelly_criterion(our_prob, comparisons[0]["bookmaker_odds"], BANKROLL)
                print_value_bet(match_label, market, comparisons[0], kelly)


def run_manual_pregame():
    """Χειροκίνητη εισαγωγή stats για pre-game ανάλυση."""
    console.rule("[bold]Χειροκίνητη Εισαγωγή Stats")

    home_name = Prompt.ask("Όνομα γηπεδούχου")
    home_scored = FloatPrompt.ask("Μέσος όρος γκολ που σκοράρει (τελ. 6 αγ.)", default=1.3)
    home_conceded = FloatPrompt.ask("Μέσος όρος γκολ που δέχεται", default=1.1)

    away_name = Prompt.ask("Όνομα φιλοξενούμενου")
    away_scored = FloatPrompt.ask("Μέσος όρος γκολ που σκοράρει", default=1.1)
    away_conceded = FloatPrompt.ask("Μέσος όρος γκολ που δέχεται", default=1.3)

    home = TeamStats(home_name, home_scored, home_conceded)
    away = TeamStats(away_name, away_scored, away_conceded)
    match_label = f"{home_name} vs {away_name}"

    probs = calculate_pregame_probs(home, away)
    print_pregame_probs(match_label, probs)


# ─── MODE 3: LIVE ────────────────────────────────────────────────────────────

def run_live():
    console.rule("[bold red]LIVE VALUE ANALYSIS")

    console.print("\n[dim]Φόρτωση live αγώνων...[/dim]")
    live_matches = get_live_matches()

    if live_matches:
        console.print(f"\nΒρέθηκαν [bold]{len(live_matches)}[/bold] live αγώνες:\n")
        for i, m in enumerate(live_matches[:10], 1):
            console.print(f"  {i}. {m['home_team']} {m['score_home']}-{m['score_away']} {m['away_team']} [{m['minute']}']")
    else:
        console.print("[yellow]Δεν βρέθηκαν live αγώνες αυτή τη στιγμή.[/yellow]")

    # Χειροκίνητη εισαγωγή για live ανάλυση
    console.print("\n[bold]Εισαγωγή live δεδομένων:[/bold]")
    pregame_prob = FloatPrompt.ask("Pre-game πιθανότητα Over 2.5 (0-1)", default=0.55)
    current_goals = IntPrompt.ask("Τρέχοντα γκολ (home + away)", default=0)
    minute = IntPrompt.ask("Τρέχον λεπτό", default=30)
    bookmaker_odds = FloatPrompt.ask("Τρέχουσα live απόδοση Over 2.5", default=2.20)

    live_result = live_over_probability(pregame_prob, current_goals, minute, target_goals=2.5)

    console.print(f"\n[bold]Live Model:[/bold]")
    console.print(f"  Λεπτό: [cyan]{minute}'[/cyan]  |  Σκορ: [cyan]{current_goals} γκολ[/cyan]  |  Χρειάζονται: [yellow]{live_result['goals_still_needed']} ακόμα[/yellow]")
    console.print(f"  Αναμενόμενα γκολ υπόλοιπο: [cyan]{live_result['expected_goals_remaining']}[/cyan]")
    console.print(f"  Live πιθανότητα: [bold cyan]{live_result['live_over_prob']:.1%}[/bold cyan]")

    value = calculate_value(live_result["live_over_prob"], bookmaker_odds)
    kelly = kelly_criterion(live_result["live_over_prob"], bookmaker_odds, BANKROLL)
    print_value_bet(f"Live αγώνας [{minute}']", "Over 2.5", value, kelly)


# ─── MAIN MENU ────────────────────────────────────────────────────────────────

def main():
    console.print("\n[bold blue]╔══════════════════════════════╗[/bold blue]")
    console.print("[bold blue]║    VALUE BETTING BOT v0.1    ║[/bold blue]")
    console.print("[bold blue]╚══════════════════════════════╝[/bold blue]\n")

    console.print("Επίλεξε mode:")
    console.print("  [bold cyan]1[/bold cyan]  Demo (παράδειγμα value calculation)")
    console.print("  [bold cyan]2[/bold cyan]  Pre-game ανάλυση")
    console.print("  [bold cyan]3[/bold cyan]  Live ανάλυση")
    console.print("  [bold cyan]4[/bold cyan]  Χειροκίνητη pre-game εισαγωγή")
    console.print("  [bold cyan]q[/bold cyan]  Έξοδος\n")

    choice = Prompt.ask("Επιλογή", choices=["1", "2", "3", "4", "q"], default="1")

    if choice == "1":
        run_demo()
    elif choice == "2":
        run_pregame()
    elif choice == "3":
        run_live()
    elif choice == "4":
        run_manual_pregame()
    elif choice == "q":
        console.print("[dim]Αντίο![/dim]")
        sys.exit(0)


if __name__ == "__main__":
    main()
