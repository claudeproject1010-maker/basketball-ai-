"""
collect_fixtures.py  v5
-----------------------
Single reliable source: ESPN hidden JSON API (no key, no auth).
Covers 10+ basketball leagues including international.

Strategy confirmed working from diagnostics:
  - ESPN scoreboard endpoint → fixtures for today/tomorrow
  - ESPN scoreboard for past 35 days → build team history from completed games
  - No balldontlie (401), no TheSportsDB (empty)

International leagues added via ESPN soccer-style league slugs for basketball.
"""

import json, os, time
from datetime import datetime, timezone, timedelta
import urllib.request, urllib.error

NOW      = datetime.now(timezone.utc)
TODAY    = NOW.strftime("%Y-%m-%d")
TOMORROW = (NOW + timedelta(days=1)).strftime("%Y-%m-%d")

print(f"[collect] {TODAY}  UTC {NOW.strftime('%H:%M')}")

ERRORS = []

# ── ESPN leagues to collect ──────────────────────────────────────────────────
# Format: (sport_slug, league_slug, display_name, history_days)
# history_days: how far back to look for completed games (longer for slower leagues)
ESPN_LEAGUES = [
    # North America — active year-round at different times
    ("basketball", "wnba",                    "WNBA",    45),
    ("basketball", "nba",                     "NBA",     45),
    ("basketball", "nba",                     "NBA",     45),   # deduped naturally
    ("basketball", "mens-college-basketball", "NCAA",    45),
    ("basketball", "womens-college-basketball","NCAAW",  45),
    ("basketball", "nbl",                     "NBL",     60),   # Australia (Oct–Apr)

    # International / regional — ESPN covers these via league slug
    ("basketball", "bbl",                     "BBL",     60),   # UK
    ("basketball", "fiba",                    "FIBA",    60),   # FIBA events
    ("basketball", "eba",                     "EBA",     60),   # Spain lower div
    ("basketball", "acb",                     "ACB",     60),   # Spain Liga ACB
    ("basketball", "vba",                     "VBA",     60),   # Vietnam Basketball Association
    ("basketball", "pba",                     "PBA",     60),   # Philippines
    ("basketball", "kbl",                     "KBL",     60),   # Korea
    ("basketball", "cba",                     "CBA",     60),   # China
    ("basketball", "lnb",                     "LNB",     60),   # France Pro A
    ("basketball", "beko.bbl",                "Beko BBL",60),   # German BBL
    ("basketball", "euroleague",              "EuroLeague",60),
    ("basketball", "eurocup",                 "EuroCup", 60),
]

# Deduplicate league list
seen_slugs = set()
UNIQUE_LEAGUES = []
for entry in ESPN_LEAGUES:
    slug = entry[1]
    if slug not in seen_slugs:
        seen_slugs.add(slug)
        UNIQUE_LEAGUES.append(entry)

# ── HTTP helper ──────────────────────────────────────────────────────────────
def fetch(url, timeout=20):
    req = urllib.request.Request(url, headers={
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0 Safari/537.36"
        ),
        "Accept": "application/json",
    })
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8", errors="replace")), None
    except urllib.error.HTTPError as e:
        if e.code not in (404, 400):   # 404 = league doesn't exist on ESPN, silent
            ERRORS.append(f"HTTP {e.code} — {url[:100]}")
        return None, f"HTTP {e.code}"
    except Exception as e:
        ERRORS.append(f"{type(e).__name__} — {url[:100]}")
        return None, str(e)


def save(path, obj):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2)
    print(f"[save]  {path}  ({len(json.dumps(obj))//1024} KB)")


# ── Scoreboard fetch ─────────────────────────────────────────────────────────
def espn_scoreboard(sport, league_slug, friendly, date_str):
    """date_str = YYYYMMDD"""
    url = (
        f"https://site.api.espn.com/apis/site/v2/sports/{sport}/{league_slug}"
        f"/scoreboard?dates={date_str}&limit=200"
    )
    data, err = fetch(url)
    if not data:
        return [], err

    games = []
    for ev in data.get("events", []):
        comps       = ev.get("competitions", [{}])
        comp        = comps[0] if comps else {}
        competitors = comp.get("competitors", [])
        if len(competitors) < 2:
            continue

        home = next((c for c in competitors if c.get("homeAway") == "home"), competitors[0])
        away = next((c for c in competitors if c.get("homeAway") == "away"), competitors[1])
        status_name = ev.get("status", {}).get("type", {}).get("name", "")
        game_dt     = ev.get("date", "")

        h_score = a_score = None
        if status_name == "STATUS_FINAL":
            try:
                h_score = int(home.get("score") or 0)
                a_score = int(away.get("score") or 0)
            except (ValueError, TypeError):
                pass

        game_date = game_dt[:10] if game_dt else (
            date_str[:4] + "-" + date_str[4:6] + "-" + date_str[6:]
        )

        games.append({
            "source":       f"espn_{league_slug}",
            "league":       friendly,
            "home_team":    home.get("team", {}).get("displayName", ""),
            "away_team":    away.get("team", {}).get("displayName", ""),
            "home_team_id": home.get("team", {}).get("id"),
            "away_team_id": away.get("team", {}).get("id"),
            "date":         game_date,
            "time_utc":     game_dt,
            "status":       status_name,
            "home_score":   h_score,
            "away_score":   a_score,
            "venue":        comp.get("venue", {}).get("fullName", ""),
            "espn_sport":   sport,
            "espn_league":  league_slug,
        })
    return games, None


def scoreboard_range(sport, league_slug, friendly, start_date, num_days):
    """Fetch scoreboard for multiple dates. Returns completed games only."""
    completed = []
    d = start_date
    for _ in range(num_days):
        date_str = d.strftime("%Y%m%d")
        games, _ = espn_scoreboard(sport, league_slug, friendly, date_str)
        for g in games:
            if g["status"] == "STATUS_FINAL" and g["home_score"] is not None:
                completed.append(g)
        d += timedelta(days=1)
        time.sleep(0.1)
    return completed


# ── Build team history from completed games ──────────────────────────────────
def build_history(completed_games, target_teams):
    team_games = {}
    for g in completed_games:
        home, away = g["home_team"], g["away_team"]
        hs, as_ = g.get("home_score") or 0, g.get("away_score") or 0
        if hs == 0 and as_ == 0:
            continue
        for team, is_home in [(home, True), (away, False)]:
            ts  = hs if is_home else as_
            os_ = as_ if is_home else hs
            entry = {
                "date": g["date"], "opponent": away if is_home else home,
                "team_score": ts, "opp_score": os_,
                "total": hs + as_, "home": is_home,
                "result": "W" if ts > os_ else "L",
            }
            team_games.setdefault(team, []).append(entry)

    history = {}
    for team in target_teams:
        games = sorted(team_games.get(team, []), key=lambda x: x["date"], reverse=True)
        if games:
            history[team] = games[:10]
    return history


# ── Main ─────────────────────────────────────────────────────────────────────
def main():
    all_upcoming  = []
    all_completed = []
    leagues_with_games = []

    for sport, league_slug, friendly, hist_days in UNIQUE_LEAGUES:
        league_upcoming = []

        # Today + tomorrow
        for delta in [0, 1]:
            d = NOW + timedelta(days=delta)
            games, err = espn_scoreboard(sport, league_slug, friendly, d.strftime("%Y%m%d"))
            if err and "404" not in err and "400" not in err:
                print(f"  [espn/{league_slug}] {d.strftime('%Y%m%d')}: {err}")
            for g in games:
                if g["status"] in ("STATUS_SCHEDULED", "STATUS_IN_PROGRESS"):
                    league_upcoming.append(g)
                elif g["status"] == "STATUS_FINAL" and g["home_score"] is not None:
                    all_completed.append(g)
            time.sleep(0.15)

        if league_upcoming:
            print(f"  [espn/{league_slug}] {len(league_upcoming)} upcoming games  ← {friendly}")
            leagues_with_games.append(friendly)
            all_upcoming.extend(league_upcoming)

        # Historical results for team history
        hist_start = NOW - timedelta(days=hist_days)
        completed = scoreboard_range(sport, league_slug, friendly, hist_start, hist_days)
        if completed:
            print(f"  [espn/{league_slug}] {len(completed)} historical results ({hist_days}d)")
            all_completed.extend(completed)

    # Deduplicate fixtures
    seen = {}
    for g in all_upcoming:
        key = (g["home_team"].lower(), g["away_team"].lower(), g["date"])
        if key not in seen:
            seen[key] = g
        else:
            for k, v in g.items():
                if not seen[key].get(k):
                    seen[key][k] = v
    fixtures = list(seen.values())

    print(f"\n[collect] {len(fixtures)} total upcoming fixtures across {len(set(g['league'] for g in fixtures))} leagues")

    # Target teams from today's fixtures
    target_teams = {g["home_team"] for g in fixtures} | {g["away_team"] for g in fixtures}
    target_teams.discard("")

    # Build history
    team_history = build_history(all_completed, target_teams)

    for team in sorted(target_teams):
        n = len(team_history.get(team, []))
        if n:
            avgt = sum(g["total"] for g in team_history[team]) / n
            print(f"  ✓ {team}: {n} games, avg total {avgt:.0f}")
        else:
            print(f"  ✗ {team}: no history")

    # Summary by league
    by_league = {}
    for g in fixtures:
        by_league[g.get("league","?")] = by_league.get(g.get("league","?"),0) + 1

    save("data/fixtures.json", {
        "collected_at":  NOW.isoformat(),
        "dates":         [TODAY, TOMORROW],
        "total_games":   len(fixtures),
        "games":         fixtures,
        "source_errors": ERRORS,
    })
    save("data/team_history.json", {
        "collected_at":          NOW.isoformat(),
        "teams_with_history":    len(team_history),
        "teams_without_history": len(target_teams) - len(team_history),
        "history":               team_history,
    })

    print("\n" + "="*52)
    print("COLLECTION SUMMARY")
    print("="*52)
    for lg, cnt in sorted(by_league.items(), key=lambda x: -x[1]):
        print(f"  {lg:<28} {cnt} fixtures")
    print(f"  {'─'*40}")
    print(f"  TOTAL                        {len(fixtures)}")
    print(f"  Teams with history:          {len(team_history)}")
    print(f"  Teams without history:       {len(target_teams)-len(team_history)}")
    if ERRORS:
        print(f"\n  ERRORS ({len(ERRORS)}):")
        for e in ERRORS[:8]:
            print(f"    ! {e}")

if __name__ == "__main__":
    main()
