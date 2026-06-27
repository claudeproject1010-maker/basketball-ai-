"""
debug_sources.py
----------------
Run this via GitHub Actions to test which APIs are reachable
and what data they actually return.

Usage:  python scripts/debug_sources.py
"""
import urllib.request, urllib.error, json, sys
from datetime import datetime, timezone, timedelta

NOW   = datetime.now(timezone.utc)
TODAY = NOW.strftime("%Y-%m-%d")
TODAY_ESPN = NOW.strftime("%Y%m%d")

def fetch(url, label):
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
        return None, str(e)

print(f"\n{'='*60}")
print(f"BASKETBALL AI — SOURCE DIAGNOSTICS")
print(f"Date: {TODAY}  UTC: {NOW.strftime('%H:%M')}")
print(f"{'='*60}\n")

# 1. ESPN NBA
data, err = fetch(
    f"https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard?dates={TODAY_ESPN}&limit=100",
    "ESPN NBA"
)
if data:
    evs = data.get("events", [])
    print(f"✓ ESPN NBA: {len(evs)} events")
    for ev in evs[:3]:
        print(f"    {ev.get('name')} | {ev.get('status',{}).get('type',{}).get('name')}")
else:
    print(f"✗ ESPN NBA: {err}")

# 2. ESPN WNBA
data, err = fetch(
    f"https://site.api.espn.com/apis/site/v2/sports/basketball/wnba/scoreboard?dates={TODAY_ESPN}&limit=100",
    "ESPN WNBA"
)
if data:
    evs = data.get("events", [])
    print(f"✓ ESPN WNBA: {len(evs)} events")
    for ev in evs[:3]:
        print(f"    {ev.get('name')} | {ev.get('status',{}).get('type',{}).get('name')}")
        # Check team IDs
        comps = ev.get("competitions", [{}])
        for c in comps[0].get("competitors", []):
            tid = c.get("team", {}).get("id")
            tname = c.get("team", {}).get("displayName")
            print(f"      team_id={tid} name={tname}")
else:
    print(f"✗ ESPN WNBA: {err}")

# 3. ESPN WNBA team history (test with first team found)
if data:
    evs = data.get("events", [])
    if evs:
        comp0 = evs[0].get("competitions", [{}])[0]
        competitors = comp0.get("competitors", [])
        if competitors:
            t = competitors[0].get("team", {})
            tid = t.get("id")
            tname = t.get("displayName")
            hist_data, err2 = fetch(
                f"https://site.api.espn.com/apis/site/v2/sports/basketball/wnba/teams/{tid}/schedule?season=2025&seasontype=2&limit=100",
                f"ESPN WNBA history ({tname})"
            )
            if hist_data:
                evts = hist_data.get("events", [])
                finals = [e for e in evts if e.get("competitions",[{}])[0].get("status",{}).get("type",{}).get("name") == "STATUS_FINAL"]
                print(f"✓ ESPN WNBA history ({tname}): {len(evts)} events, {len(finals)} final")
                if finals:
                    comp = finals[0].get("competitions",[{}])[0]
                    for c in comp.get("competitors",[]):
                        print(f"    {c.get('team',{}).get('displayName')} {c.get('score')}")
            else:
                print(f"✗ ESPN WNBA history ({tname}): {err2}")

# 4. ESPN NCAA
data, err = fetch(
    f"https://site.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball/scoreboard?dates={TODAY_ESPN}&limit=100",
    "ESPN NCAA"
)
if data:
    evs = data.get("events", [])
    print(f"✓ ESPN NCAA: {len(evs)} events")
else:
    print(f"✗ ESPN NCAA: {err}")

# 5. balldontlie
data, err = fetch(
    f"https://api.balldontlie.io/v1/games?dates[]={TODAY}&per_page=100",
    "balldontlie"
)
if data:
    games = data.get("data", [])
    print(f"✓ balldontlie NBA: {len(games)} games")
    for g in games[:3]:
        print(f"    {g['home_team']['full_name']} vs {g['visitor_team']['full_name']} | {g['status']}")
else:
    print(f"✗ balldontlie: {err}")

# 6. TheSportsDB WNBA
data, err = fetch(
    f"https://www.thesportsdb.com/api/v1/json/3/eventsday.php?d={TODAY}&s=Basketball&l=4391",
    "TheSportsDB WNBA"
)
if data:
    evs = data.get("events") or []
    print(f"✓ TheSportsDB WNBA: {len(evs)} events")
else:
    print(f"✗ TheSportsDB WNBA: {err}")

# 7. TheSportsDB NBA
data, err = fetch(
    f"https://www.thesportsdb.com/api/v1/json/3/eventsday.php?d={TODAY}&s=Basketball&l=4387",
    "TheSportsDB NBA"
)
if data:
    evs = data.get("events") or []
    print(f"✓ TheSportsDB NBA: {len(evs)} events")
else:
    print(f"✗ TheSportsDB NBA: {err}")

print(f"\n{'='*60}\n")
