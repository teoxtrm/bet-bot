"""
Exploration script — τρέξε μία φορά για να δεις τη δομή του Sofascore odds API.
Αποθηκεύει τα raw JSON σε data/raw/ για επιθεώρηση.
"""

import json, requests
from pathlib import Path
from datetime import date

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json",
    "Referer": "https://www.sofascore.com/",
}
BASE = "https://api.sofascore.com/api/v1"
OUT  = Path("data/raw")
OUT.mkdir(parents=True, exist_ok=True)

def get(path):
    r = requests.get(f"{BASE}{path}", headers=HEADERS, timeout=10)
    print(f"  GET {path}  -> {r.status_code}")
    return r.json() if r.status_code == 200 else None

# ── 1. Βρες έναν αγώνα ─────────────────────────────────────────────────────
today = date.today().isoformat()
print(f"\n[1] Αγώνες για {today}")
sched = get(f"/sport/football/scheduled-events/{today}")
events = sched.get("events", []) if sched else []
print(f"    Βρέθηκαν {len(events)} αγώνες")

# Αν δεν υπάρχουν σήμερα, δοκίμασε τα live
if not events:
    print("\n[1b] Δοκιμή live αγώνων...")
    live = get("/sport/football/events/live")
    events = live.get("events", []) if live else []

# Πάρε τον πρώτο διαθέσιμο αγώνα
if not events:
    print("Δεν βρέθηκαν αγώνες. Δοκίμασε αύριο.")
    exit()

ev = events[0]
eid = ev["id"]
home = ev["homeTeam"]["name"]
away = ev["awayTeam"]["name"]
print(f"    Δοκιμή με event id={eid}: {home} vs {away}")
print(f"    Status: {ev.get('status', {}).get('description', '?')}")

# ── 2. Δοκίμασε όλα τα γνωστά odds endpoints ──────────────────────────────
print(f"\n[2] Odds endpoints για event {eid}")

endpoints = {
    "odds_prematch_featured" : f"/event/{eid}/odds/1/featured",
    "odds_prematch_all"      : f"/event/{eid}/odds/1/all",
    "odds_live_featured"     : f"/event/{eid}/odds/2/featured",
    "odds_live_all"          : f"/event/{eid}/odds/2/all",
}

for name, path in endpoints.items():
    data = get(path)
    if data:
        fpath = OUT / f"{name}_{eid}.json"
        fpath.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"    [OK] Saved -> {fpath}")

        # Εκτύπωσε τα top-level keys και τα markets
        print(f"      Keys: {list(data.keys())}")
        markets = data.get("markets", [])
        print(f"      Markets ({len(markets)}):")
        for m in markets[:8]:
            mname = m.get("marketName", m.get("market", {}).get("name", "?"))
            # Bookmakers που περιέχει
            bms = [b.get("bookmaker", {}).get("name", "?")
                   for b in m.get("bookmakerOdds", [])]
            choices = [c.get("name","?") for c in m.get("choices", [])[:4]]
            print(f"        • {mname:30s} | choices: {choices} | bookmakers: {bms[:5]}")
    else:
        print(f"    ✗ {path} → no data")

# ── 3. Βρες το Stoiximan provider ID ───────────────────────────────────────
print(f"\n[3] Ψάξιμο για 'stoiximan' στα αποθηκευμένα JSONs")
for f in OUT.glob(f"odds_*_{eid}.json"):
    raw = json.loads(f.read_text(encoding="utf-8"))
    for market in raw.get("markets", []):
        for bm_entry in market.get("bookmakerOdds", []):
            bm = bm_entry.get("bookmaker", {})
            name_lower = bm.get("name", "").lower()
            if "stoix" in name_lower or "bet365" in name_lower or "novibet" in name_lower:
                print(f"    ΒΡΕΘΗΚΕ → id={bm.get('id')} name={bm.get('name')} (αρχείο: {f.name})")

print("\nΈτοιμο! Κοίταξε τα αρχεία data/raw/ για πλήρη δομή.")
