"""
collect_fixtures.py
-------------------
Collects today's basketball fixtures from multiple FREE sources:

1. TheSportsDB (free, no key needed)  — primary source
2. balldontlie.io (free, NBA focused) — secondary / enrichment
3. ESPN hidden JSON endpoints         — tertiary fallback

Saves raw data to data/fixtures.json
Saves team history (last 10 games) to data/team_history.json
"""

import json
import os
import time
from datetime import datetime, timezone, timedelta
import urllib.request
import urllib.error


TODAY = datetime.now(timezone.utc).strftime("%Y-%m-%d")
TOMORROW = (datetime.now(timezone.utc) + timedelta(days=1)).strftime("%Y-%m-%d")

print(f"[collect] target dates: {TODAY}, {TOMORROW}")


# ─── helpers ────────────────────────────────────────────────────────────────

def fetch(url, headers=None, timeout=15):
    req = urllib.request.Request(url, headers=headers or {
        "User-Agent": "Mozilla/5.0 BasketballAI/1.0"
    })
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode())
    except Exception as e:
        print(f"[fetch] ERROR {url[:80]}: {e}")
        return None


def save(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    print(f"[save] {path} ({len(json.dumps(data))} bytes)")


# ─── Source 1: TheSportsDB (free tier, no key) ───────────────────────────────

def fetch_thesportsdb_fixtures(date):
    """
    TheSportsDB free API — returns events for a given date.
    League IDs we care about (basketball):
      4387 = NBA
      4388 = NCAA Men's Basketball (D1)
      4391 = WNBA
      4966 = EuroLeague
      4967 = Liga ACB (Spain)
      4968 = BBL (Germany)
      4971 = NBL (Australia)
      4579 = Turkish BSL
    """
    LEAGUE_IDS = {
        "4387": "NBA",
        "4388": "NCAA",
        "4391": "WNBA",
        "4966": "EuroLeague",
        "4967": "Liga ACB",
        "4968": "BBL",
        "4971": "NBL",
        "4579": "Turkish BSL",
    }

    games = []
    for lid, league_name in LEAGUE_IDS.items():
        url = f"https://www.thesportsdb.com/api/v1/json/3/eventsday.php?d={date}&s=Basketball&l={lid}"
        data = fetch(url)
        if not data or not data.get("events"):
            continue
        for ev in data["events"]:
            if ev.get("strStatus") in ("Not Started", "NS", ""):
                home = ev.get("strHomeTeam", "")
                away = ev.get("strAwayTeam", "")
                if not home or not away:
                    continue
                games.append({
                    "source": "thesportsdb",
                    "source_id": ev.get("idEvent"),
                    "league": league_name,
                    "league_id": lid,
                    "home_team": home,
                    "away_team": away,
                    "home_team_id": ev.get("idHomeTeam"),
                    "away_team_id": ev.get("idAwayTeam"),
                    "date": date,
                    "time_utc": ev.get("strTime", ""),
                    "status": "NS",
                })
        time.sleep(0.3)

    print(f"[thesportsdb] {date}: {len(games)} upcoming games")
    return games


def fetch_thesportsdb_team_last10(team_id, team_name):
    """
    Fetch last 15 events for a team from TheSportsDB.
    Returns list of completed game scores (most recent first).
    """
    if not team_id:
        return []
    url = f"https://www.thesportsdb.com/api/v1/json/3/eventslast.php?id={team_id}"
    data = fetch(url)
    if not data:
        return []
    events = data.get("results") or []
    history = []
    for ev in events:
        h_score = ev.get("intHomeScore")
        a_score = ev.get("intAwayScore")
        if h_score is None or a_score is None:
            continue
        try:
            h_score = int(h_score)
            a_score = int(a_score)
        except (ValueError, TypeError):
            continue
        total = h_score + a_score
        is_home = ev.get("strHomeTeam", "").lower() == team_name.lower()
        team_score = h_score if is_home else a_score
        opp_score = a_score if is_home else h_score
        history.append({
            "date": ev.get("dateEvent", ""),
            "opponent": ev.get("strAwayTeam") if is_home else ev.get("strHomeTeam"),
            "team_score": team_score,
            "opp_score": opp_score,
            "total": total,
            "home": is_home,
            "result": "W" if team_score > opp_score else "L",
        })
    return history[:10]


# ─── Source 2: balldontlie (NBA, free) ───────────────────────────────────────

def fetch_balldontlie_games(date):
    """balldontlie.io free tier — NBA games for a date."""
    url = f"https://api.balldontlie.io/v1/games?dates[]={date}&per_page=100"
    # API key optional for free tier with low rate; try without first
    data = fetch(url, headers={
        "User-Agent": "BasketballAI/1.0",
    })
    if not data or "data" not in data:
        return []

    games = []
    for g in data["data"]:
        status = g.get("status", "")
        # Only pre-game
        if status not in ("scheduled", "1st Qtr", "") and "Final" not in status:
            pass  # include regardless, filter later
        home = g.get("home_team", {})
        away = g.get("visitor_team", {})
        games.append({
            "source": "balldontlie",
            "source_id": str(g.get("id")),
            "league": "NBA",
            "league_id": "nba_bdl",
            "home_team": home.get("full_name", ""),
            "away_team": away.get("full_name", ""),
            "home_team_id": str(home.get("id", "")),
            "away_team_id": str(away.get("id", "")),
            "home_team_abbr": home.get("abbreviation", ""),
            "away_team_abbr": away.get("abbreviation", ""),
            "date": date,
            "status": status,
        })
    print(f"[balldontlie] {date}: {len(games)} games")
    return games


def fetch_balldontlie_season_avg(team_id):
    """Fetch current season averages for a team (points scored & allowed)."""
    if not team_id:
        return {}
    # Season stats endpoint
    url = f"https://api.balldontlie.io/v1/season_averages?season=2024&team_ids[]={team_id}"
    data = fetch(url)
    if not data or not data.get("data"):
        return {}
    # Aggregate across all players on that team
    players = data["data"]
    if not players:
        return {}
    total_pts = sum(p.get("pts", 0) or 0 for p in players)
    return {"team_pts_per_game": round(total_pts, 1)}


def fetch_balldontlie_team_games(team_id, seasons=None):
    """Fetch last 10 completed games for an NBA team via balldontlie."""
    if not team_id:
        return []
    seasons = seasons or [2024, 2025]
    all_games = []
    for season in seasons:
        url = f"https://api.balldontlie.io/v1/games?seasons[]={season}&team_ids[]={team_id}&per_page=100"
        data = fetch(url)
        if data and data.get("data"):
            all_games.extend(data["data"])
        time.sleep(0.2)

    completed = [g for g in all_games if "Final" in g.get("status", "")]
    completed.sort(key=lambda g: g.get("date", ""), reverse=True)

    history = []
    for g in completed[:10]:
        home = g.get("home_team", {})
        away = g.get("visitor_team", {})
        is_home = str(home.get("id")) == str(team_id)
        h_score = g.get("home_team_score") or 0
        a_score = g.get("visitor_team_score") or 0
        team_score = h_score if is_home else a_score
        opp_score = a_score if is_home else h_score
        history.append({
            "date": g.get("date", ""),
            "opponent": away.get("full_name") if is_home else home.get("full_name"),
            "team_score": team_score,
            "opp_score": opp_score,
            "total": h_score + a_score,
            "home": is_home,
            "result": "W" if team_score > opp_score else "L",
        })
    return history


# ─── Source 3: ESPN scoreboard (hidden JSON) ─────────────────────────────────

def fetch_espn_scoreboard(sport="basketball", league="nba", date=None):
    """
    ESPN's undocumented but stable JSON endpoint.
    Works for: nba, wnba, mens-college-basketball, nbl (Australia)
    """
    date_str = (date or TODAY).replace("-", "")
    url = (
        f"https://site.api.espn.com/apis/site/v2/sports/{sport}/{league}"
        f"/scoreboard?dates={date_str}&limit=100"
    )
    data = fetch(url)
    if not data:
        return []

    events = data.get("events") or []
    games = []
    for ev in events:
        comps = ev.get("competitions", [{}])
        comp = comps[0] if comps else {}
        competitors = comp.get("competitors", [])
        if len(competitors) < 2:
            continue

        status_type = ev.get("status", {}).get("type", {})
        status_name = status_type.get("name", "")
        # Only pre-game
        if status_name not in ("STATUS_SCHEDULED", "STATUS_IN_PROGRESS"):
            if status_name != "STATUS_SCHEDULED":
                pass  # still include, predictions script will filter

        home = next((c for c in competitors if c.get("homeAway") == "home"), competitors[0])
        away = next((c for c in competitors if c.get("homeAway") == "away"), competitors[1])

        games.append({
            "source": f"espn_{league}",
            "source_id": ev.get("id"),
            "league": data.get("leagues", [{}])[0].get("name", league.upper()),
            "league_id": f"espn_{league}",
            "home_team": home.get("team", {}).get("displayName", ""),
            "away_team": away.get("team", {}).get("displayName", ""),
            "home_team_id": home.get("team", {}).get("id"),
            "away_team_id": away.get("team", {}).get("id"),
            "home_team_abbr": home.get("team", {}).get("abbreviation", ""),
            "away_team_abbr": away.get("team", {}).get("abbreviation", ""),
            "date": date or TODAY,
            "status": status_name,
            "venue": comp.get("venue", {}).get("fullName", ""),
        })

    print(f"[espn/{league}] {date}: {len(games)} games")
    return games


def fetch_espn_team_history(team_id, league="nba", sport="basketball"):
    """Fetch recent game results for a team via ESPN team schedule endpoint."""
    if not team_id:
        return []
    url = (
        f"https://site.api.espn.com/apis/site/v2/sports/{sport}/{league}"
        f"/teams/{team_id}/schedule?season=2025&seasontype=2"
    )
    data = fetch(url)
    if not data:
        return []

    events = data.get("events") or []
    history = []
    for ev in events:
        result_obj = ev.get("competitions", [{}])[0]
        competitors = result_obj.get("competitors", [])
        if len(competitors) < 2:
            continue
        status = result_obj.get("status", {}).get("type", {}).get("name", "")
        if status != "STATUS_FINAL":
            continue

        home_c = next((c for c in competitors if c.get("homeAway") == "home"), competitors[0])
        away_c = next((c for c in competitors if c.get("homeAway") == "away"), competitors[1])
        is_home = home_c.get("team", {}).get("id") == str(team_id)

        try:
            h_score = int(home_c.get("score", 0) or 0)
            a_score = int(away_c.get("score", 0) or 0)
        except (ValueError, TypeError):
            continue
        if h_score == 0 and a_score == 0:
            continue

        team_score = h_score if is_home else a_score
        opp_score = a_score if is_home else h_score

        history.append({
            "date": ev.get("date", "")[:10],
            "opponent": (away_c if is_home else home_c).get("team", {}).get("displayName", ""),
            "team_score": team_score,
            "opp_score": opp_score,
            "total": h_score + a_score,
            "home": is_home,
            "result": "W" if team_score > opp_score else "L",
        })

    history.sort(key=lambda x: x["date"], reverse=True)
    return history[:10]


# ─── Deduplicate games across sources ────────────────────────────────────────

def deduplicate(games):
    """
    Merge games from multiple sources by (home_team, away_team, date).
    Later sources enrich earlier ones; don't produce duplicates.
    """
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
            # Enrich existing with any extra fields from this source
            existing = seen[key]
            for k, v in g.items():
                if k not in existing or not existing[k]:
                    existing[k] = v
    return list(seen.values())


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    all_games = []

    # --- Fixtures ---
    for date in [TODAY, TOMORROW]:
        # TheSportsDB (multi-league)
        tsdb = fetch_thesportsdb_fixtures(date)
        all_games.extend(tsdb)

        # ESPN (NBA, WNBA, NCAA, NBL, EuroLeague)
        espn_sources = [
            ("basketball", "nba"),
            ("basketball", "wnba"),
            ("basketball", "mens-college-basketball"),
        ]
        for sport, league in espn_sources:
            all_games.extend(fetch_espn_scoreboard(sport, league, date))
            time.sleep(0.2)

        # balldontlie (NBA enrichment)
        bdl = fetch_balldontlie_games(date)
        all_games.extend(bdl)

    all_games = deduplicate(all_games)
    print(f"[collect] total unique fixtures: {len(all_games)}")

    # --- Team history (last 10 games) ---
    team_history = {}
    processed_teams = set()

    for game in all_games:
        for side in ["home", "away"]:
            team_name = game.get(f"{side}_team", "")
            team_id = game.get(f"{side}_team_id")
            source = game.get("source", "")
            key = team_name.lower()

            if key in processed_teams or not team_name:
                continue
            processed_teams.add(key)

            history = []

            # ESPN path (most reliable for NBA/WNBA/NCAA)
            if "espn" in source and team_id:
                league_slug = source.replace("espn_", "")
                history = fetch_espn_team_history(team_id, league_slug)
                time.sleep(0.25)

            # TheSportsDB path (multi-league)
            if not history and source == "thesportsdb" and team_id:
                history = fetch_thesportsdb_team_last10(team_id, team_name)
                time.sleep(0.3)

            # balldontlie path (NBA fallback)
            if not history and "bdl" in str(game.get("league_id", "")):
                history = fetch_balldontlie_team_games(team_id)
                time.sleep(0.3)

            if history:
                team_history[team_name] = history
                print(f"  [history] {team_name}: {len(history)} games")

    # --- Save ---
    save("data/fixtures.json", {
        "collected_at": datetime.now(timezone.utc).isoformat(),
        "dates": [TODAY, TOMORROW],
        "total_games": len(all_games),
        "games": all_games,
    })

    save("data/team_history.json", {
        "collected_at": datetime.now(timezone.utc).isoformat(),
        "teams": len(team_history),
        "history": team_history,
    })

    print(f"[collect] done — {len(all_games)} games, {len(team_history)} teams with history")


if __name__ == "__main__":
    main()
