"""
collect_fixtures.py  —  v3
--------------------------
Data sources (all free, no key required):

  1. ESPN scoreboard JSON  — fixtures for today & tomorrow
  2. ESPN team schedule    — last-10 game history per team
  3. balldontlie.io        — NBA enrichment / fallback history
  4. TheSportsDB           — multi-league fallback

GitHub Actions has full network access so all of these work there.
"""

import json, os, time, sys
from datetime import datetime, timezone, timedelta
import urllib.request, urllib.error

# ── Date targets ────────────────────────────────────────────────────────────
NOW   = datetime.now(timezone.utc)
TODAY = NOW.strftime("%Y-%m-%d")
TOMORROW = (NOW + timedelta(days=1)).strftime("%Y-%m-%d")
TODAY_ESPN  = NOW.strftime("%Y%m%d")
TOMW_ESPN   = (NOW + timedelta(days=1)).strftime("%Y%m%d")

print(f"[collect] date: {TODAY}  (UTC now: {NOW.strftime('%H:%M')})")

ERRORS = []   # collect all errors for diagnostic output

# ── HTTP helper ─────────────────────────────────────────────────────────────
def fetch(url, timeout=20, extra_headers=None):
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0 Safari/537.36"
        ),
        "Accept": "application/json",
    }
    if extra_headers:
        headers.update(extra_headers)
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read().decode("utf-8", errors="replace")
            return json.loads(raw)
    except urllib.error.HTTPError as e:
        ERRORS.append(f"HTTP {e.code} — {url[:90]}")
        return None
    except Exception as e:
        ERRORS.append(f"{type(e).__name__}: {e} — {url[:90]}")
        return None

def save(path, obj):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2)
    kb = len(json.dumps(obj)) / 1024
    print(f"[save]  {path}  ({kb:.1f} KB)")

# ── ESPN: fixtures ───────────────────────────────────────────────────────────
ESPN_LEAGUES = [
    # (sport, league_slug, friendly_name)
    ("basketball", "nba",                     "NBA"),
    ("basketball", "wnba",                    "WNBA"),
    ("basketball", "mens-college-basketball", "NCAA"),
    ("basketball", "nbl",                     "NBL"),
]

def espn_scoreboard(sport, league, date_str, friendly):
    url = (
        f"https://site.api.espn.com/apis/site/v2/sports/{sport}/{league}"
        f"/scoreboard?dates={date_str}&limit=100"
    )
    data = fetch(url)
    if not data:
        return []
    games = []
    for ev in data.get("events", []):
        comps = ev.get("competitions", [{}])
        comp  = comps[0] if comps else {}
        competitors = comp.get("competitors", [])
        if len(competitors) < 2:
            continue
        home = next((c for c in competitors if c.get("homeAway") == "home"), competitors[0])
        away = next((c for c in competitors if c.get("homeAway") == "away"), competitors[1])
        status_name = ev.get("status", {}).get("type", {}).get("name", "")
        # Store game time in UTC ISO; dashboard will convert to WAT
        game_date_utc = ev.get("date", "")
        games.append({
            "source":        f"espn_{league}",
            "league":        friendly,
            "home_team":     home.get("team", {}).get("displayName", ""),
            "away_team":     away.get("team", {}).get("displayName", ""),
            "home_team_id":  home.get("team", {}).get("id"),
            "away_team_id":  away.get("team", {}).get("id"),
            "home_abbr":     home.get("team", {}).get("abbreviation", ""),
            "away_abbr":     away.get("team", {}).get("abbreviation", ""),
            "date":          game_date_utc[:10] if game_date_utc else TODAY,
            "time_utc":      game_date_utc,   # full ISO string
            "status":        status_name,
            "venue":         comp.get("venue", {}).get("fullName", ""),
            "espn_league":   league,
            "espn_sport":    sport,
        })
    print(f"[espn/{league}]  {date_str}: {len(games)} games  (status sample: {set(g['status'] for g in games[:5])})")
    return games

# ── ESPN: team history ───────────────────────────────────────────────────────
def espn_team_history(team_id, sport, league, season=2025):
    """
    Fetches a team's completed games from their schedule endpoint.
    Returns list of last-10 completed game dicts.
    """
    if not team_id:
        return []
    url = (
        f"https://site.api.espn.com/apis/site/v2/sports/{sport}/{league}"
        f"/teams/{team_id}/schedule?season={season}&seasontype=2&limit=100"
    )
    data = fetch(url)
    if not data:
        # Try previous season too
        if season == 2025:
            return espn_team_history(team_id, sport, league, season=2024)
        return []

    history = []
    for ev in data.get("events", []):
        comp = (ev.get("competitions") or [{}])[0]
        status = comp.get("status", {}).get("type", {}).get("name", "")
        if status != "STATUS_FINAL":
            continue
        competitors = comp.get("competitors", [])
        if len(competitors) < 2:
            continue
        home_c = next((c for c in competitors if c.get("homeAway") == "home"), competitors[0])
        away_c = next((c for c in competitors if c.get("homeAway") == "away"), competitors[1])
        try:
            h = int(home_c.get("score") or 0)
            a = int(away_c.get("score") or 0)
        except (ValueError, TypeError):
            continue
        if h == 0 and a == 0:
            continue
        is_home = home_c.get("team", {}).get("id") == str(team_id)
        ts = h if is_home else a
        os_ = a if is_home else h
        history.append({
            "date":       ev.get("date", "")[:10],
            "opponent":   (away_c if is_home else home_c).get("team", {}).get("displayName", ""),
            "team_score": ts,
            "opp_score":  os_,
            "total":      h + a,
            "home":       is_home,
            "result":     "W" if ts > os_ else "L",
        })
    history.sort(key=lambda x: x["date"], reverse=True)
    return history[:10]

# ── balldontlie: NBA fixtures ────────────────────────────────────────────────
def bdl_games(date):
    url = f"https://api.balldontlie.io/v1/games?dates[]={date}&per_page=100"
    data = fetch(url)
    if not data:
        return []
    games = []
    for g in (data.get("data") or []):
        home = g.get("home_team", {})
        away = g.get("visitor_team", {})
        games.append({
            "source":       "balldontlie",
            "league":       "NBA",
            "home_team":    home.get("full_name", ""),
            "away_team":    away.get("full_name", ""),
            "home_team_id": str(home.get("id", "")),
            "away_team_id": str(away.get("id", "")),
            "home_abbr":    home.get("abbreviation", ""),
            "away_abbr":    away.get("abbreviation", ""),
            "date":         date,
            "time_utc":     g.get("date", ""),
            "status":       g.get("status", ""),
        })
    print(f"[balldontlie]  {date}: {len(games)} games")
    return games

def bdl_team_history(team_id):
    if not team_id:
        return []
    games_all = []
    for season in [2024, 2025]:
        url = f"https://api.balldontlie.io/v1/games?seasons[]={season}&team_ids[]={team_id}&per_page=100"
        data = fetch(url)
        if data and data.get("data"):
            games_all.extend(data["data"])
        time.sleep(0.15)
    completed = [g for g in games_all if "Final" in str(g.get("status", ""))]
    completed.sort(key=lambda g: g.get("date", ""), reverse=True)
    history = []
    for g in completed[:10]:
        home = g.get("home_team", {})
        away = g.get("visitor_team", {})
        is_home = str(home.get("id")) == str(team_id)
        h = g.get("home_team_score") or 0
        a = g.get("visitor_team_score") or 0
        ts = h if is_home else a
        os_ = a if is_home else h
        history.append({
            "date":       g.get("date", "")[:10],
            "opponent":   (away if is_home else home).get("full_name", ""),
            "team_score": ts,
            "opp_score":  os_,
            "total":      h + a,
            "home":       is_home,
            "result":     "W" if ts > os_ else "L",
        })
    return history

# ── TheSportsDB: multi-league fixtures ───────────────────────────────────────
TSDB_LEAGUES = {
    "4387": "NBA",
    "4391": "WNBA",
    "4966": "EuroLeague",
    "4967": "Liga ACB",
    "4968": "BBL",
    "4971": "NBL",
    "4579": "Turkish BSL",
}

def tsdb_fixtures(date):
    games = []
    for lid, name in TSDB_LEAGUES.items():
        url = (
            f"https://www.thesportsdb.com/api/v1/json/3/eventsday.php"
            f"?d={date}&s=Basketball&l={lid}"
        )
        data = fetch(url)
        if not data or not data.get("events"):
            continue
        for ev in data["events"]:
            home = ev.get("strHomeTeam", "")
            away = ev.get("strAwayTeam", "")
            if not home or not away:
                continue
            # Build ISO time string for WAT conversion in dashboard
            ev_date = ev.get("dateEvent", date)
            ev_time = ev.get("strTime", "")
            time_utc = f"{ev_date}T{ev_time}Z" if ev_time else ""
            games.append({
                "source":       "thesportsdb",
                "league":       name,
                "home_team":    home,
                "away_team":    away,
                "home_team_id": ev.get("idHomeTeam"),
                "away_team_id": ev.get("idAwayTeam"),
                "date":         ev_date,
                "time_utc":     time_utc,
                "status":       ev.get("strStatus", "NS"),
            })
        time.sleep(0.25)
    print(f"[thesportsdb]  {date}: {len(games)} games")
    return games

def tsdb_team_history(team_id, team_name):
    if not team_id:
        return []
    url = f"https://www.thesportsdb.com/api/v1/json/3/eventslast.php?id={team_id}"
    data = fetch(url)
    if not data:
        return []
    history = []
    for ev in (data.get("results") or []):
        try:
            h = int(ev.get("intHomeScore") or 0)
            a = int(ev.get("intAwayScore") or 0)
        except (ValueError, TypeError):
            continue
        if h == 0 and a == 0:
            continue
        is_home = ev.get("strHomeTeam", "").lower() == team_name.lower()
        ts = h if is_home else a
        os_ = a if is_home else h
        history.append({
            "date":       ev.get("dateEvent", ""),
            "opponent":   ev.get("strAwayTeam") if is_home else ev.get("strHomeTeam"),
            "team_score": ts,
            "opp_score":  os_,
            "total":      h + a,
            "home":       is_home,
            "result":     "W" if ts > os_ else "L",
        })
    history.sort(key=lambda x: x["date"], reverse=True)
    return history[:10]

# ── Deduplicate ──────────────────────────────────────────────────────────────
def dedup(games):
    seen = {}
    for g in games:
        key = (
            g["home_team"].lower().strip(),
            g["away_team"].lower().strip(),
            g["date"],
        )
        if key not in seen:
            seen[key] = g
        else:
            for k, v in g.items():
                if k not in seen[key] or not seen[key][k]:
                    seen[key][k] = v
    return list(seen.values())

# ── Main ─────────────────────────────────────────────────────────────────────
def main():
    all_games = []

    # ─ Fixtures ─
    for date_iso, date_espn in [(TODAY, TODAY_ESPN), (TOMORROW, TOMW_ESPN)]:
        # ESPN (most reliable, no key)
        for sport, league, friendly in ESPN_LEAGUES:
            all_games.extend(espn_scoreboard(sport, league, date_espn, friendly))
            time.sleep(0.2)

        # balldontlie (NBA)
        all_games.extend(bdl_games(date_iso))

        # TheSportsDB (multi-league)
        all_games.extend(tsdb_fixtures(date_iso))

    all_games = dedup(all_games)
    print(f"[collect]  unique fixtures: {len(all_games)}")

    # ─ Team history ─
    team_history = {}
    seen_teams = set()

    for game in all_games:
        for side in ["home", "away"]:
            name    = game.get(f"{side}_team", "")
            team_id = game.get(f"{side}_team_id")
            source  = game.get("source", "")
            key = name.lower().strip()
            if not name or key in seen_teams:
                continue
            seen_teams.add(key)

            history = []

            # Try ESPN first (most complete)
            if team_id and "espn" in source:
                sport  = game.get("espn_sport", "basketball")
                league = game.get("espn_league", "nba")
                history = espn_team_history(team_id, sport, league)
                time.sleep(0.25)

            # Try balldontlie for NBA teams
            if not history and game.get("league") == "NBA" and team_id:
                history = bdl_team_history(team_id)
                time.sleep(0.2)

            # TheSportsDB fallback for other leagues
            if not history and source == "thesportsdb" and team_id:
                history = tsdb_team_history(team_id, name)
                time.sleep(0.3)

            if history:
                team_history[name] = history
                avg_total = sum(g["total"] for g in history) / len(history)
                print(f"  ✓ {name}: {len(history)} games, avg total {avg_total:.0f}")
            else:
                print(f"  ✗ {name}: no history retrieved")

    # ─ Save ─
    save("data/fixtures.json", {
        "collected_at": NOW.isoformat(),
        "dates":        [TODAY, TOMORROW],
        "total_games":  len(all_games),
        "games":        all_games,
        "source_errors": ERRORS,
    })

    save("data/team_history.json", {
        "collected_at": NOW.isoformat(),
        "teams_with_history": len(team_history),
        "teams_without_history": len(seen_teams) - len(team_history),
        "history": team_history,
    })

    # ─ Diagnostic summary ─
    print()
    print("=" * 60)
    print("COLLECTION SUMMARY")
    print("=" * 60)
    by_league = {}
    for g in all_games:
        lg = g.get("league", "Unknown")
        by_league[lg] = by_league.get(lg, 0) + 1
    for lg, count in sorted(by_league.items(), key=lambda x: -x[1]):
        print(f"  {lg:<30} {count} games")
    print(f"  {'─'*40}")
    print(f"  TOTAL                          {len(all_games)} games")
    print(f"  Teams WITH history:            {len(team_history)}")
    print(f"  Teams WITHOUT history:         {len(seen_teams) - len(team_history)}")
    if ERRORS:
        print(f"\n  API ERRORS ({len(ERRORS)}):")
        for e in ERRORS[:10]:
            print(f"    ! {e}")

if __name__ == "__main__":
    main()
