"""
Βοηθητικές συναρτήσεις εμφάνισης και μορφοποίησης.
"""

from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich import box

console = Console()


def print_value_bet(match: str, market: str, result: dict, kelly: dict = None):
    color = "green" if result["is_value_bet"] else "red"
    symbol = "✓ VALUE BET" if result["is_value_bet"] else "✗ Όχι value"

    panel_content = (
        f"[bold]{match}[/bold] | {market}\n\n"
        f"Πιθανότητά μας:  [cyan]{result['our_probability']:.1%}[/cyan]\n"
        f"Implied prob:    [yellow]{result['implied_probability']:.1%}[/yellow]\n"
        f"Απόδοση:         [white]{result['bookmaker_odds']}[/white]  [{result.get('bookmaker', '')}]\n"
        f"Edge:            [{color}]{result['value_edge_pct']}[/{color}]\n"
    )

    if kelly:
        panel_content += f"Kelly bet:       [magenta]€{kelly['suggested_bet']}[/magenta] ({kelly['fractional_kelly_pct']}% bankroll)\n"

    console.print(Panel(panel_content, title=f"[{color}]{symbol}[/{color}]", box=box.ROUNDED))


def print_comparison_table(match: str, market: str, comparisons: list):
    table = Table(title=f"{match} — {market}", box=box.SIMPLE_HEAVY)
    table.add_column("Bookmaker", style="cyan")
    table.add_column("Απόδοση", justify="right")
    table.add_column("Implied %", justify="right")
    table.add_column("Edge", justify="right")
    table.add_column("Value?", justify="center")

    for r in comparisons:
        is_val = r["is_value_bet"]
        edge_color = "green" if is_val else "red"
        table.add_row(
            r["bookmaker"].capitalize(),
            str(r["bookmaker_odds"]),
            f"{r['implied_probability']:.1%}",
            f"[{edge_color}]{r['value_edge_pct']}[/{edge_color}]",
            "[green]✓[/green]" if is_val else "[red]✗[/red]",
        )

    console.print(table)


def print_pregame_probs(match: str, probs: dict):
    # Keys που είναι expected goals (αριθμοί, όχι πιθανότητες)
    GOAL_KEYS = {"expected_goals_home", "expected_goals_away", "expected_goals_total"}

    table = Table(title=f"Pre-game Model: {match}", box=box.SIMPLE)
    table.add_column("Αγορά", style="bold")
    table.add_column("Τιμή", justify="right", style="cyan")
    table.add_column("Implied Odds", justify="right", style="yellow")

    for key, val in probs.items():
        if not isinstance(val, float):
            continue
        label = key.replace("_", " ").title()
        if key in GOAL_KEYS:
            table.add_row(label, f"{val:.2f} γκολ", "—")
        else:
            implied = f"{1/val:.2f}" if val > 0 else "—"
            table.add_row(label, f"{val:.1%}", implied)

    console.print(table)
