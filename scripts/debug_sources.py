"""
debug_sources.py  v6
--------------------
Tests ESPN and Sofascore sources.
Run via: python scripts/debug_sources.py
"""

import urllib.request, urllib.error, json
from datetime import datetime, timezone, timedelta

NOW     = datetime.now(timezone.utc)
TODAY   = NOW.strftime("%Y-%m-%d")
TODAY_E = NOW.strftime("%Y%m%d")
YEST_E  = (NOW - timedelta(days=1)).strftime("%Y%m%d")
YEST    = (NOW - timedelta(days=1)).strftime("%Y-%m-%d")

def fetch_espn(url):
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "application/json",
    })
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.loads(r.read()), None
    except urllib.error.HTTPError as e:
        return None, f"HTTP {e.code} {e.reason}"
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"

def fetch_sofa(url):
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) "
                      "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1",
        "Accept": "application/json",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://www.sofascore.com/",
    })
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.loads(r.read()), None
    except urllib.error.HTTPError as e:
        return None, f"HTTP {e.code} {e.reason}"
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"

def section(t):
    print(f"\n{'─'*56}\n  {t}\n{'─'*56}")

print(f"\n{'='*56}")
print(f"  BASKETBALL AI — SOURCE DIAGNOSTICS  v6")
print(f"  Date: {TODAY}  UTC: {NOW.strftime('%H:%M')}")
print(f"{'='*56}")

# ── 1. ESPN WNBA today ───────────────────────────────────
section("ESPN WNBA — Today")
data, err = fetch_espn(f"https://site.api.espn.com/apis/site/v2/sports/basketball/wnba/scoreboard?dates={TODAY_E}&limit=100")
if data:
    evs = data.get("events",[])
    print(f"  ✓ {len(evs)} events")
    for ev in evs[:4]:
        print(f"    {ev.get('name')} | {ev.get('status',{}).get('type',{}).get('name')}")
else:
    print(f"  ✗ {err}")

# ── 2. ESPN WNBA yesterday (history test) ────────────────
section("ESPN WNBA — Yesterday")
data, err = fetch_espn(f"https://site.api.espn.com/apis/site/v2/sports/basketball/wnba/scoreboard?dates={YEST_E}&limit=100")
if data:
    evs = data.get("events",[])
    finals = [e for e in evs if e.get("status",{}).get("type",{}).get("name")=="STATUS_FINAL"]
    print(f"  ✓ {len(evs)} events, {len(finals)} final")
    for ev in finals[:3]:
        comp = ev.get("competitions",[{}])[0]
        scores = [(c.get("team",{}).get("displayName","?"), c.get("score","?")) for c in comp.get("competitors",[])]
        if len(scores)>=2: print(f"    {scores[0][0]} {scores[0][1]} — {scores[1][0]} {scores[1][1]}")
else:
    print(f"  ✗ {err}")

# ── 3. ESPN NBA today ─────────────────────────────────────
section("ESPN NBA — Today (off-season Jun-Sep)")
data, err = fetch_espn(f"https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard?dates={TODAY_E}&limit=100")
if data:
    evs = data.get("events",[])
    print(f"  ✓ {len(evs)} events {'(off-season, expected 0)' if not evs else ''}")
else:
    print(f"  ✗ {err}")

# ── 4. Sofascore basketball today ─────────────────────────
section("Sofascore — Basketball Today")
data, err = fetch_sofa(f"https://www.sofascore.com/api/v1/sport/basketball/scheduled-events/{TODAY}")
if data:
    evs = data.get("events",[])
    not_started = [e for e in evs if e.get("status",{}).get("type") in ("notstarted","inprogress")]
    finished    = [e for e in evs if e.get("status",{}).get("type") == "finished"]
    print(f"  ✓ {len(evs)} total events")
    print(f"    Upcoming/live: {len(not_started)}")
    print(f"    Finished:      {len(finished)}")
    # Show leagues
    leagues = {}
    for ev in not_started:
        lg = ev.get("tournament",{}).get("name","?")
        leagues[lg] = leagues.get(lg,0)+1
    print(f"    Leagues with upcoming games ({len(leagues)}):")
    for lg, cnt in sorted(leagues.items(), key=lambda x:-x[1])[:15]:
        print(f"      {lg}: {cnt}")
    # Sample games
    print(f"    Sample upcoming:")
    for ev in not_started[:5]:
        h = ev.get("homeTeam",{}).get("name","?")
        a = ev.get("awayTeam",{}).get("name","?")
        lg = ev.get("tournament",{}).get("name","?")
        cat = ev.get("tournament",{}).get("category",{}).get("name","?")
        print(f"      [{cat}/{lg}] {h} vs {a}")
else:
    print(f"  ✗ {err}")

# ── 5. Sofascore basketball yesterday (history check) ─────
section("Sofascore — Basketball Yesterday (history)")
data, err = fetch_sofa(f"https://www.sofascore.com/api/v1/sport/basketball/scheduled-events/{YEST}")
if data:
    evs = data.get("events",[])
    finished = [e for e in evs if e.get("status",{}).get("type") == "finished"]
    print(f"  ✓ {len(evs)} events, {len(finished)} finished")
    for ev in finished[:4]:
        h = ev.get("homeTeam",{}).get("name","?")
        a = ev.get("awayTeam",{}).get("name","?")
        hs = ev.get("homeScore",{}).get("current","?")
        as_ = ev.get("awayScore",{}).get("current","?")
        lg = ev.get("tournament",{}).get("name","?")
        print(f"    [{lg}] {h} {hs} — {a} {as_}")
else:
    print(f"  ✗ {err}")

# ── 6. Sofascore team history test ────────────────────────
section("Sofascore — Team History Test")
# Use a well-known team: Chicago Sky (Sofascore ID varies, try search)
# We'll just test the endpoint structure with a generic call
data, err = fetch_sofa(f"https://www.sofascore.com/api/v1/sport/basketball/scheduled-events/{YEST}")
if data:
    evs = data.get("events",[])
    finished = [e for e in evs if e.get("status",{}).get("type") == "finished"]
    if finished:
        sample = finished[0]
        team_id = sample.get("homeTeam",{}).get("id")
        team_name = sample.get("homeTeam",{}).get("name","?")
        if team_id:
            hist_data, err2 = fetch_sofa(f"https://www.sofascore.com/api/v1/team/{team_id}/events/last/0")
            if hist_data:
                hist_evs = [e for e in hist_data.get("events",[]) if e.get("status",{}).get("type")=="finished"]
                print(f"  ✓ Team history for '{team_name}' (id={team_id}): {len(hist_evs)} past games")
                for e in hist_evs[:3]:
                    h = e.get("homeTeam",{}).get("name","?")
                    a = e.get("awayTeam",{}).get("name","?")
                    hs = e.get("homeScore",{}).get("current","?")
                    as_ = e.get("awayScore",{}).get("current","?")
                    print(f"    {h} {hs} — {a} {as_}")
            else:
                print(f"  ✗ Team history: {err2}")
else:
    print(f"  ✗ Sofascore unavailable for team history test")

print(f"\n{'='*56}\n")
