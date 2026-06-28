"""
debug_sources.py  v4
--------------------
Tests every data source and reports exactly what comes back.
Run via: python scripts/debug_sources.py
Or via GitHub Actions step.
"""

import urllib.request, urllib.error, json
from datetime import datetime, timezone, timedelta

NOW      = datetime.now(timezone.utc)
TODAY    = NOW.strftime("%Y-%m-%d")
TODAY_E  = NOW.strftime("%Y%m%d")
YEST_E   = (NOW - timedelta(days=1)).strftime("%Y%m%d")
WEEK_AGO = (NOW - timedelta(days=7)).strftime("%Y%m%d")

def fetch(url, label=""):
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "application/json",
    })
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            data = json.loads(r.read())
            return data, None
    except urllib.error.HTTPError as e:
        return None, f"HTTP {e.code} {e.reason}"
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"

def section(title):
    print(f"\n{'─'*56}")
    print(f"  {title}")
    print(f"{'─'*56}")

print(f"\n{'='*56}")
print(f"  BASKETBALL AI — SOURCE DIAGNOSTICS  v4")
print(f"  Date: {TODAY}  UTC: {NOW.strftime('%H:%M')}")
print(f"{'='*56}")

# ── 1. ESPN WNBA scoreboard ──────────────────────────────
section("ESPN WNBA — Today's Fixtures")
data, err = fetch(f"https://site.api.espn.com/apis/site/v2/sports/basketball/wnba/scoreboard?dates={TODAY_E}&limit=100")
wnba_teams = {}
if data:
    evs = data.get("events", [])
    print(f"  ✓ {len(evs)} events")
    for ev in evs:
        print(f"    {ev.get('name')} | {ev.get('status',{}).get('type',{}).get('name')}")
        comp = ev.get("competitions",[{}])[0]
        for c in comp.get("competitors",[]):
            tid   = c.get("team",{}).get("id")
            tname = c.get("team",{}).get("displayName","")
            print(f"      team_id={tid}  name={tname}")
            if tid and tname:
                wnba_teams[tname] = tid
else:
    print(f"  ✗ {err}")

# ── 2. ESPN WNBA — yesterday's scoreboard (test history source) ──
section("ESPN WNBA — Yesterday (history test)")
data, err = fetch(f"https://site.api.espn.com/apis/site/v2/sports/basketball/wnba/scoreboard?dates={YEST_E}&limit=100")
if data:
    evs = data.get("events", [])
    finals = [e for e in evs if e.get("status",{}).get("type",{}).get("name") == "STATUS_FINAL"]
    print(f"  ✓ {len(evs)} events, {len(finals)} final")
    for ev in finals[:3]:
        comp = ev.get("competitions",[{}])[0]
        teams = comp.get("competitors",[])
        scores = [(c.get("team",{}).get("displayName","?"), c.get("score","?")) for c in teams]
        print(f"    {scores[0][0]} {scores[0][1]} — {scores[1][0]} {scores[1][1]}")
else:
    print(f"  ✗ {err}")

# ── 3. ESPN WNBA — 7 days ago ──
section("ESPN WNBA — 7 Days Ago (history depth test)")
data, err = fetch(f"https://site.api.espn.com/apis/site/v2/sports/basketball/wnba/scoreboard?dates={WEEK_AGO}&limit=100")
if data:
    evs = data.get("events", [])
    finals = [e for e in evs if e.get("status",{}).get("type",{}).get("name") == "STATUS_FINAL"]
    print(f"  ✓ {len(evs)} events, {len(finals)} final")
    for ev in finals[:3]:
        comp = ev.get("competitions",[{}])[0]
        teams = comp.get("competitors",[])
        scores = [(c.get("team",{}).get("displayName","?"), c.get("score","?")) for c in teams]
        print(f"    {scores[0][0]} {scores[0][1]} — {scores[1][0]} {scores[1][1]}")
else:
    print(f"  ✗ {err}")

# ── 4. ESPN NBA ──────────────────────────────────────────
section("ESPN NBA — Today")
data, err = fetch(f"https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard?dates={TODAY_E}&limit=100")
if data:
    evs = data.get("events", [])
    print(f"  ✓ {len(evs)} events (NBA off-season — expected 0 in June)")
else:
    print(f"  ✗ {err}")

# ── 5. ESPN team schedule (broken — keep testing) ───────
section("ESPN WNBA Team Schedule (known broken)")
if wnba_teams:
    sample_name, sample_id = next(iter(wnba_teams.items()))
    for season in [2026, 2025, 2024]:
        url = (f"https://site.api.espn.com/apis/site/v2/sports/basketball/wnba"
               f"/teams/{sample_id}/schedule?season={season}&seasontype=2&limit=100")
        data, err = fetch(url)
        if data:
            evts = data.get("events", [])
            finals = [e for e in evts if e.get("competitions",[{}])[0].get("status",{}).get("type",{}).get("name") == "STATUS_FINAL"]
            print(f"  season={season}: {len(evts)} events, {len(finals)} final — {'✓ WORKS' if finals else '✗ empty'}")
        else:
            print(f"  season={season}: ✗ {err}")
else:
    print("  (skipped — no team IDs from scoreboard)")

# ── 6. TheSportsDB ──────────────────────────────────────
section("TheSportsDB")
for lid, name in [("4391","WNBA"),("4387","NBA"),("4966","EuroLeague")]:
    url = f"https://www.thesportsdb.com/api/v1/json/3/eventsday.php?d={TODAY}&s=Basketball&l={lid}"
    data, err = fetch(url)
    if data:
        evs = data.get("events") or []
        print(f"  {name} (id={lid}): {'✓' if evs else '○'} {len(evs)} events")
    else:
        print(f"  {name}: ✗ {err}")

# ── 7. balldontlie ──────────────────────────────────────
section("balldontlie (expects 401 — free tier dead)")
data, err = fetch(f"https://api.balldontlie.io/v1/games?dates[]={TODAY}&per_page=100")
if data:
    print(f"  ✓ {len(data.get('data',[]))} games (free tier works!)")
else:
    print(f"  ✗ {err}")

print(f"\n{'='*56}\n")
