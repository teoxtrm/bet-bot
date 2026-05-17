"""
Live Scanner — polling loop για in-play αγώνες.
Ανανεώνει scores + odds κάθε N δευτερόλεπτα και υπολογίζει live value.
"""

import os
import time
import requests
from datetime import datetime, timezone
from dotenv import load_dotenv

load_dotenv()

BASE_URL = "https://api.the-odds-api.com/v4"
API_KEY  = os.getenv("ODDS_API_KEY", "")


def _get(path: str, params: dict) -> list | None:
    params["apiKey"] = API_KEY
    try:
        r = requests.get(f"{BASE_URL}{path}", params=params, timeout=15)
        remaining = r.headers.get("x-requests-remaining", "?")
        if r.status_code == 200:
            print(f"[LiveScanner] {r.status_code} {path.split('?')[0]} | remaining={remaining}")
            return r.json()
        print(f"[LiveScanner] Error {r.status_code}: {r.text[:100]}")
    except requests.RequestException as e:
        print(f"[LiveScanner] Network error: {e}")
    return None


def get_live_scores(sport_key: str) -> list:
    """
    Επιστρέφει αγώνες που είναι in-play τώρα.
    In-play = commenced + not completed + scores not null.
    """
    now  = datetime.now(timezone.utc)
    data = _get(f"/sports/{sport_key}/scores/", {"daysFrom": 1, "dateFormat": "iso"})
    if not data:
        return []

    live = []
    for e in data:
        if e.get("completed"):
            continue
        try:
            start = datetime.fromisoformat(e["commence_time"].replace("Z", "+00:00"))
        except Exception:
            continue
        if start > now:
            continue  # δεν έχει ξεκινήσει ακόμα

        scores = e.get("scores") or []
        score_map = {s["name"]: int(s["score"]) for s in scores} if scores else {}

        live.append({
            "id":         e["id"],
            "home_team":  e["home_team"],
            "away_team":  e["away_team"],
            "home_score": score_map.get(e["home_team"], 0),
            "away_score": score_map.get(e["away_team"], 0),
            "total_goals": sum(score_map.values()),
            "commence":   e["commence_time"],
            "last_update": e.get("last_update", ""),
        })
    return live


def get_live_odds_for_event(sport_key: str, event_id: str) -> dict | None:
    """
    Τραβάει τις τρέχουσες αποδόσεις για ένα συγκεκριμένο in-play event.
    """
    data = _get(
        f"/sports/{sport_key}/odds/",
        {"regions": "eu,uk", "markets": "h2h,totals,totals_h1", "oddsFormat": "decimal", "dateFormat": "iso"},
    )
    if not data:
        return None
    for e in data:
        if e.get("id") == event_id:
            return e
    return None


def estimate_minute(commence_time: str) -> int:
    """Εκτιμά το τρέχον λεπτό από την ώρα έναρξης."""
    try:
        start = datetime.fromisoformat(commence_time.replace("Z", "+00:00"))
        now   = datetime.now(timezone.utc)
        elapsed = int((now - start).total_seconds() / 60)
        # Υπολογισμός για 90 λεπτά + ~15 λεπτά ημίχρονο
        if elapsed > 45:
            elapsed = max(elapsed - 15, 45)  # αφαίρεσε ημίχρονο break
        return min(elapsed, 90)
    except Exception:
        return 45


def scan_once(sport_key: str, our_model_probs: dict = None) -> list:
    """
    Μία σάρωση: βρίσκει live αγώνες, αποδόσεις, υπολογίζει value.

    Args:
        sport_key: π.χ. "soccer_greece_super_league"
        our_model_probs: {"match_id": {"over_2_5": 0.55, ...}} — προαιρετικό

    Returns:
        Λίστα live αγώνων με enriched δεδομένα
    """
    from scrapers.odds_api import (get_pinnacle_no_vig_totals, get_pinnacle_no_vig_probs,
                                    get_pinnacle_no_vig_ht_totals, _parse_event)
    from models.live_model import live_over_probability
    from models.value_calculator import compare_bookmakers

    live_scores  = get_live_scores(sport_key)
    if not live_scores:
        return []

    # Τράβα odds για όλο το sport (1 request αντί για N)
    raw_odds = _get(
        f"/sports/{sport_key}/odds/",
        {"regions": "eu,uk", "markets": "h2h,totals,totals_h1", "oddsFormat": "decimal", "dateFormat": "iso"},
    )
    odds_by_id = {}
    if raw_odds:
        for e in raw_odds:
            odds_by_id[e["id"]] = _parse_event(e)

    enriched = []
    for match in live_scores:
        minute  = estimate_minute(match["commence"])
        ev_odds = odds_by_id.get(match["id"])

        entry = {**match, "minute": minute, "value_bets": []}

        if ev_odds:
            # Pinnacle no-vig Over 2.5
            p_ou = get_pinnacle_no_vig_totals(ev_odds, 2.5)
            if p_ou:
                pregame_prob = p_ou["over_prob"]
                live_result  = live_over_probability(
                    pregame_prob, match["total_goals"], minute, target_goals=2.5
                )
                live_prob = live_result["live_over_prob"]

                # Collect Over 2.5 odds da tutti i bookmakers
                bm_odds = {}
                for bm_key, bm_data in ev_odds.get("odds", {}).items():
                    o = bm_data.get("totals", {}).get("over_2_5")
                    if o:
                        bm_odds[bm_key] = o

                if bm_odds:
                    comps = compare_bookmakers(live_prob, bm_odds)
                    value_hits = [c for c in comps if c["is_value_bet"]]
                    entry["pinnacle_over_prob"] = p_ou["over_prob"]
                    entry["live_over_prob"]     = live_prob
                    entry["value_bets"]         = value_hits

        # HT Over 0.5 — critical window: 15-25 min AND score 0-0
        entry["ht_value_bets"] = []
        if ev_odds and 15 <= minute <= 25 and match["total_goals"] == 0:
            p_ht = get_pinnacle_no_vig_ht_totals(ev_odds, 0.5)
            if p_ht:
                pt_str = str(p_ht["point"]).replace(".", "_")
                bm_ht = {}
                for bm_key, bm_data in ev_odds.get("odds", {}).items():
                    o = bm_data.get("totals_h1", {}).get(f"over_{pt_str}")
                    if o:
                        bm_ht[bm_key] = o
                if bm_ht:
                    ht_comps = compare_bookmakers(p_ht["over_prob"], bm_ht)
                    entry["ht_value_bets"] = [c for c in ht_comps if c["is_value_bet"]]
                    entry["ht_over_prob"]  = p_ht["over_prob"]

        enriched.append(entry)

    return enriched


def run_live_loop(sport_key: str, interval_seconds: int = 120, max_iterations: int = 30):
    """
    Polling loop — ανανεώνει κάθε interval_seconds.
    Χρησιμοποιεί ~2 requests/iteration (scores + odds).
    Για 500 free requests/μήνα: max ~250 iterations = ~8 ώρες continuous scanning.
    """
    from rich.console import Console
    from rich.table import Table
    from rich import box
    console = Console()

    console.print(f"\n[bold red]LIVE SCANNER[/bold red] — {sport_key}")
    console.print(f"Polling κάθε [cyan]{interval_seconds}s[/cyan] | Max iterations: {max_iterations}")
    console.print("Ctrl+C για έξοδο\n")

    iteration = 0
    try:
        while iteration < max_iterations:
            iteration += 1
            now_str = datetime.now().strftime("%H:%M:%S")
            console.rule(f"[dim]Scan #{iteration} — {now_str}[/dim]")

            results = scan_once(sport_key)

            if not results:
                console.print("[yellow]Δεν υπάρχουν in-play αγώνες αυτή τη στιγμή.[/yellow]")
            else:
                table = Table(box=box.SIMPLE_HEAVY, show_header=True)
                table.add_column("Αγώνας", style="bold")
                table.add_column("Σκορ", justify="center", style="cyan")
                table.add_column("Λεπτό", justify="center")
                table.add_column("Live O2.5", justify="right", style="yellow")
                table.add_column("Best Odds", justify="right")
                table.add_column("Edge", justify="right")
                table.add_column("Value?", justify="center")

                for r in results:
                    score    = f"{r['home_score']}-{r['away_score']}"
                    minute   = f"{r['minute']}'"
                    live_p   = f"{r.get('live_over_prob', 0):.1%}" if r.get('live_over_prob') else "—"
                    vbets    = r.get("value_bets", [])
                    if vbets:
                        best  = vbets[0]
                        odds  = str(best["bookmaker_odds"])
                        edge  = best["value_edge_pct"]
                        val   = "[green]VALUE![/green]"
                    else:
                        odds, edge, val = "—", "—", "[dim]no[/dim]"

                    table.add_row(
                        f"{r['home_team']} vs {r['away_team']}",
                        score, minute, live_p, odds, edge, val
                    )

                console.print(table)

                # Alert για Over 2.5 value bets
                for r in results:
                    for vb in r.get("ht_value_bets", []):
                        console.print(
                            f"[bold yellow]>>> ⚡ HT VALUE:[/bold yellow] "
                            f"{r['home_team']} vs {r['away_team']} [{r['minute']}'] "
                            f"Over 0.5 HT @ [yellow]{vb['bookmaker_odds']}[/yellow] "
                            f"({vb['bookmaker']}) | edge=[green]{vb['value_edge_pct']}[/green]"
                        )
                for r in results:
                    for vb in r.get("value_bets", []):
                        console.print(
                            f"[bold green]>>> VALUE BET:[/bold green] "
                            f"{r['home_team']} vs {r['away_team']} [{r['minute']}'] "
                            f"Over 2.5 @ [yellow]{vb['bookmaker_odds']}[/yellow] "
                            f"({vb['bookmaker']}) | edge=[green]{vb['value_edge_pct']}[/green]"
                        )
                        # Auto-track στη DB
                        try:
                            from utils.database import track_value_bet
                            from models.value_calculator import kelly_criterion
                            kelly = kelly_criterion(
                                r.get("live_over_prob", 0.5),
                                vb["bookmaker_odds"],
                                float(os.getenv("BANKROLL", "1000"))
                            )
                            bet_id = track_value_bet(
                                value_result = vb,
                                kelly_result = kelly,
                                match_info   = {
                                    "event_id":   r.get("id", ""),
                                    "match_date": r.get("commence", "")[:10],
                                    "home_team":  r["home_team"],
                                    "away_team":  r["away_team"],
                                    "bet_type":   "Over 2.5",
                                },
                                league     = sport_key,
                                is_live    = True,
                                live_minute= r.get("minute"),
                            )
                            if bet_id > 0:
                                console.print(f"  [dim]DB: tracked as #{bet_id}[/dim]")
                        except Exception as db_err:
                            console.print(f"  [dim]DB tracking error: {db_err}[/dim]")

            console.print(f"[dim]Επόμενο scan σε {interval_seconds}s...[/dim]")
            time.sleep(interval_seconds)

    except KeyboardInterrupt:
        console.print("\n[dim]Live scanner διακόπηκε.[/dim]")
