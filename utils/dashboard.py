"""
Rich Terminal Dashboard — εμφανίζει στατιστικά και ιστορικό bets.
"""

from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.columns import Columns
from rich.text import Text
from rich import box

console = Console()


def print_dashboard():
    """Κεντρικό dashboard με όλα τα στατιστικά."""
    from utils.database import get_stats, get_all_bets, get_pending_bets

    stats   = get_stats()
    pending = get_pending_bets()
    bets    = get_all_bets(50)

    # ── KPI Panel ────────────────────────────────────────────────────────────
    total    = stats["total_bets"] or 0
    settled  = stats["settled"] or 0
    wins     = stats["wins"] or 0
    losses   = stats["losses"] or 0
    win_rate = stats["win_rate"] * 100
    pnl      = stats["total_pnl"] or 0
    roi      = stats["roi"] or 0
    staked   = stats["total_staked"] or 0
    avg_edge = (stats["avg_edge"] or 0) * 100
    avg_odds = stats["avg_odds"] or 0

    pnl_color  = "green" if pnl >= 0 else "red"
    roi_color  = "green" if roi >= 0 else "red"
    wr_color   = "green" if win_rate >= 50 else "yellow" if win_rate >= 40 else "red"

    kpis = [
        Panel(f"[bold cyan]{total}[/bold cyan]\n[dim]Σύνολο Bets[/dim]",      expand=True),
        Panel(f"[bold]{stats['pending'] or 0}[/bold]\n[dim]Pending[/dim]",    expand=True),
        Panel(f"[bold {wr_color}]{win_rate:.1f}%[/bold {wr_color}]\n[dim]Win Rate ({wins}W/{losses}L)[/dim]", expand=True),
        Panel(f"[bold {pnl_color}]€{pnl:+.2f}[/bold {pnl_color}]\n[dim]Total PnL[/dim]", expand=True),
        Panel(f"[bold {roi_color}]{roi:+.1f}%[/bold {roi_color}]\n[dim]ROI[/dim]",        expand=True),
        Panel(f"[bold yellow]{avg_edge:.1f}%[/bold yellow]\n[dim]Avg Edge[/dim]",          expand=True),
    ]

    console.print()
    console.rule("[bold blue]VALUE BETTING BOT — DASHBOARD[/bold blue]")
    console.print(Columns(kpis, equal=True, expand=True))

    # ── Extra stats row ───────────────────────────────────────────────────────
    if settled > 0:
        best  = stats["best_win"]  or 0
        worst = stats["worst_loss"] or 0
        console.print(
            f"  Avg odds: [cyan]{avg_odds:.2f}[/cyan]  |  "
            f"Total staked: [cyan]€{staked:.2f}[/cyan]  |  "
            f"Best win: [green]€{best:+.2f}[/green]  |  "
            f"Worst loss: [red]€{worst:+.2f}[/red]"
        )

    # ── Pending Bets ──────────────────────────────────────────────────────────
    if pending:
        console.print()
        t = Table(title=f"Pending Bets ({len(pending)})", box=box.SIMPLE_HEAVY)
        t.add_column("#",        justify="right",  style="dim",    width=4)
        t.add_column("Αγώνας",   style="bold",                     min_width=28)
        t.add_column("Αγορά",    style="cyan",                     min_width=12)
        t.add_column("Prob",     justify="right",  style="yellow")
        t.add_column("Odds",     justify="right")
        t.add_column("Edge",     justify="right",  style="green")
        t.add_column("Stake",    justify="right",  style="magenta")
        t.add_column("Bookmaker",style="dim",                      min_width=10)
        t.add_column("Live",     justify="center")
        t.add_column("Date",     justify="center", style="dim")

        for b in pending:
            live_str = f"[red]{b['live_minute']}'[/red]" if b["is_live"] else "[dim]Pre[/dim]"
            t.add_row(
                str(b["id"]),
                f"{b['home_team']} vs {b['away_team']}",
                b["bet_type"],
                f"{b['our_probability']:.1%}",
                str(b["bookmaker_odds"]),
                f"{b['value_edge_pct']*100:.1f}%",
                f"€{b['kelly_stake']:.2f}",
                b["bookmaker"],
                live_str,
                b["match_date"],
            )
        console.print(t)

    # ── Recent Settled Bets ───────────────────────────────────────────────────
    settled_bets = [b for b in bets if b["status"] in ("Win", "Loss", "Void")]
    if settled_bets:
        console.print()
        t2 = Table(title="Τελευταία Settled Bets", box=box.SIMPLE)
        t2.add_column("#",      justify="right", style="dim", width=4)
        t2.add_column("Αγώνας",style="bold",                  min_width=26)
        t2.add_column("Αγορά", style="cyan",                  min_width=12)
        t2.add_column("Odds",  justify="right")
        t2.add_column("Stake", justify="right", style="magenta")
        t2.add_column("Score", justify="center")
        t2.add_column("PnL",   justify="right")
        t2.add_column("Status",justify="center")

        for b in settled_bets[:20]:
            pnl_val = b["profit_loss"] or 0
            pnl_col = "green" if pnl_val > 0 else "red" if pnl_val < 0 else "dim"
            status_fmt = {
                "Win":  "[bold green]WIN[/bold green]",
                "Loss": "[bold red]LOSS[/bold red]",
                "Void": "[dim]VOID[/dim]",
            }.get(b["status"], b["status"])
            score = f"{b['final_home_goals']}-{b['final_away_goals']}" \
                    if b["final_home_goals"] is not None else "—"

            t2.add_row(
                str(b["id"]),
                f"{b['home_team']} vs {b['away_team']}",
                b["bet_type"],
                str(b["bookmaker_odds"]),
                f"€{b['kelly_stake']:.2f}",
                score,
                f"[{pnl_col}]€{pnl_val:+.2f}[/{pnl_col}]",
                status_fmt,
            )
        console.print(t2)

    # ── League breakdown ──────────────────────────────────────────────────────
    if settled > 0:
        _print_league_breakdown(bets)

    console.print()


def _print_league_breakdown(bets: list):
    """PnL ανά πρωτάθλημα."""
    from collections import defaultdict
    leagues: dict = defaultdict(lambda: {"bets": 0, "wins": 0, "pnl": 0.0, "staked": 0.0})

    for b in bets:
        if b["status"] not in ("Win", "Loss"):
            continue
        lg = b["league"]
        leagues[lg]["bets"]   += 1
        leagues[lg]["staked"] += b["kelly_stake"] or 0
        leagues[lg]["pnl"]    += b["profit_loss"] or 0
        if b["status"] == "Win":
            leagues[lg]["wins"] += 1

    if not leagues:
        return

    console.print()
    t = Table(title="Ανά Πρωτάθλημα", box=box.SIMPLE)
    t.add_column("League",  style="bold")
    t.add_column("Bets",    justify="right")
    t.add_column("Win Rate",justify="right")
    t.add_column("Staked",  justify="right", style="magenta")
    t.add_column("PnL",     justify="right")
    t.add_column("ROI",     justify="right")

    for lg, d in sorted(leagues.items(), key=lambda x: x[1]["pnl"], reverse=True):
        wr    = d["wins"] / d["bets"] * 100 if d["bets"] else 0
        roi   = d["pnl"] / d["staked"] * 100 if d["staked"] else 0
        pc    = "green" if d["pnl"] >= 0 else "red"
        rc    = "green" if roi >= 0 else "red"
        t.add_row(
            lg.replace("_", " ").title(),
            str(d["bets"]),
            f"{wr:.0f}%",
            f"€{d['staked']:.2f}",
            f"[{pc}]€{d['pnl']:+.2f}[/{pc}]",
            f"[{rc}]{roi:+.1f}%[/{rc}]",
        )
    console.print(t)


def print_settlement_preview(pending: list) -> None:
    """Εμφανίζει τα pending bets πριν το settlement."""
    if not pending:
        console.print("[yellow]Δεν υπάρχουν Pending bets.[/yellow]")
        return
    console.print(f"\n[bold]{len(pending)} Pending bets προς settlement:[/bold]\n")
    for b in pending:
        console.print(
            f"  #{b['id']:3d}  {b['home_team']} vs {b['away_team']}  "
            f"[cyan]{b['bet_type']}[/cyan]  "
            f"@[yellow]{b['bookmaker_odds']}[/yellow]  "
            f"stake=[magenta]€{b['kelly_stake']:.2f}[/magenta]  "
            f"[dim]{b['match_date']}[/dim]"
        )
