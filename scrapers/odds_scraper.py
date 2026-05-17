"""
Scraper αποδόσεων από Stoiximan, Bet365, Novibet.

ΣΗΜΕΙΩΣΗ: Αυτά τα sites χρησιμοποιούν JavaScript rendering.
Αυτό το αρχείο παρέχει placeholder + manual input mode.
Σε επόμενο βήμα θα προστεθεί Selenium/Playwright integration.
"""

import json
from pathlib import Path

ODDS_CACHE_FILE = Path("data/processed/odds_cache.json")


def load_odds_from_cache() -> dict:
    if ODDS_CACHE_FILE.exists():
        with open(ODDS_CACHE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_odds_to_cache(odds_data: dict):
    ODDS_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(ODDS_CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(odds_data, f, indent=2, ensure_ascii=False)


def manual_odds_input(match_label: str) -> dict:
    """
    Χειροκίνητη εισαγωγή αποδόσεων από τον χρήστη.
    Χρησιμοποιείται όταν το auto-scraping δεν είναι διαθέσιμο.
    """
    print(f"\n--- Εισαγωγή αποδόσεων για: {match_label} ---")
    print("(Πάτα Enter για να παραλείψεις μια στοιχηματική)\n")

    bookmakers = ["stoiximan", "bet365", "novibet"]
    markets = {}

    for market in ["over_2_5", "btts_yes"]:
        print(f"\nΑγορά: {market.upper()}")
        odds = {}
        for bm in bookmakers:
            val = input(f"  {bm}: ").strip()
            if val:
                try:
                    odds[bm] = float(val)
                except ValueError:
                    print(f"  [!] Μη έγκυρη τιμή για {bm}, αγνοείται.")
        markets[market] = odds

    return markets


def get_odds_for_match(match_label: str, use_cache: bool = True) -> dict:
    """
    Κεντρική συνάρτηση λήψης αποδόσεων.
    Προς το παρόν: cache ή manual input.
    TODO: auto scraping με Selenium.
    """
    if use_cache:
        cache = load_odds_from_cache()
        if match_label in cache:
            print(f"[Cache] Φορτώθηκαν αποδόσεις για: {match_label}")
            return cache[match_label]

    odds = manual_odds_input(match_label)
    cache = load_odds_from_cache()
    cache[match_label] = odds
    save_odds_to_cache(cache)
    return odds
