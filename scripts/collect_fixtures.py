"""
collect_fixtures.py  v4
-----------------------
What the diagnostics revealed:
  - ESPN WNBA scoreboard:   WORKS  (returns fixtures)
  - ESPN team schedule:     BROKEN (returns 0 events — wrong endpoint for WNBA)
  - balldontlie:            DEAD   (HTTP 401 — free tier killed)
  - TheSportsDB:            EMPTY  (off-season / tier issue)

Fix strategy for team history:
  Instead of ESPN team schedule endpoint (broken),
  fetch the WNBA scoreboard for the last 30 days
  and extract completed game results for every team we care about.
  This is the same endpoint that already works for fixtures.
"""

import json, os, time
from datetime import datetime, timezone, timedelta
import urllib.request, urllib.error

NOW      = datetime.now(timezone.utc)
TODAY    = NOW.strftime("%Y-%m-%d")
TOMORROW = (NOW + timedelta(days=1)).strftime("%Y-%m-%d")

print(f"[collect] {TODAY}  UTC {NOW.strftime('%H:%M')}")

ERRORS = []

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


# ── ESPN scoreboard (works reliably) ────────────────────────────────────────
ESPN_LEAGUES = [
    ("basketball", "wnba",                    "WNBA"),
    ("basketball", "nba",                     "NBA"),
    ("basketball", "mens-college-basketball", "NCAA"),
    ("basketball", "nbl",                     "NBL"),
]

def espn_scoreboard(sport, league, date_str, friendly_name):
    """Fetch scoreboard for a specific date. date_str = YYYYMMDD"""
    url = (
        f"https://site.api.espn.com/apis/site/v2/sports/{sport}/{league}"
        f"/scoreboard?dates={date_str}&limit=100"
    )
    data, err = fetch(url)
    if not data:
        return [], err

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
        game_dt     = ev.get("date", "")

        # Extract score if game is finished
        h_score = a_score = None
        if status_name == "STATUS_FINAL":
            try:
                h_score = int(home.get("score") or 0)
                a_score = int(away.get("score") or 0)
            except (ValueError, TypeError):
                pass

        games.append({
            "source":       f"espn_{league}",
            "league":       friendly_name,
            "home_team":    home.get("team", {}).get("displayName", ""),
            "away_team":    away.get("team", {}).get("displayName", ""),
            "home_team_id": home.get("team", {}).get("id"),
            "away_team_id": away.get("team", {}).get("id"),
            "date":         game_dt[:10] if game_dt else date_str[:4]+"-"+date_str[4:6]+"-"+date_str[6:],
            "time_utc":     game_dt,
            "status":       status_name,
            "home_score":   h_score,
            "away_score":   a_score,
            "venue":        comp.get("venue", {}).get("fullName", ""),
            "espn_sport":   sport,
            "espn_league":  league,
        })

    return games, None


def espn_scoreboard_range(sport, league, friendly, start_date, num_days):
    """
    Fetch scoreboard for a range of dates.
    Returns (upcoming_games, completed_games)
    """
    upcoming  = []
    completed = []
    d = start_date
    for _ in range(num_days):
        date_str = d.strftime("%Y%m%d")
        games, err = espn_scoreboard(sport, league, date_str, friendly)
        if err:
            print(f"  [espn/{league}] {date_str}: {err}")
        for g in games:
            if g["status"] == "STATUS_FINAL":
                completed.append(g)
            elif g["status"] in ("STATUS_SCHEDULED", "STATUS_IN_PROGRESS"):
                upcoming.append(g)
        d += timedelta(days=1)
        time.sleep(0.15)
    return upcoming, completed


# ── Build team history from completed scoreboard games ───────────────────────
def build_team_history(completed_games, target_teams):
    """
    Given a list of completed games (from scoreboard),
    build a last-10 game history dict for each team in target_teams.

    This is the reliable approach since ESPN team schedule is broken.
    """
    # Index completed games by team name (both home and away)
    team_games = {}  # team_name → list of game dicts

    for g in completed_games:
        home = g["home_team"]
        away = g["away_team"]
        h_sc = g.get("home_score") or 0
        a_sc = g.get("away_score") or 0
        date = g["date"]

        if h_sc == 0 and a_sc == 0:
            continue

        for team, is_home in [(home, True), (away, False)]:
            ts = h_sc if is_home else a_sc
            os_ = a_sc if is_home else h_sc
            entry = {
                "date":       date,
                "opponent":   away if is_home else home,
                "team_score": ts,
                "opp_score":  os_,
                "total":      h_sc + a_sc,
                "home":       is_home,
                "result":     "W" if ts > os_ else "L",
            }
            if team not in team_games:
                team_games[team] = []
            team_games[team].append(entry)

    # Sort each team's games by date descending, keep last 10
    history = {}
    for team in target_teams:
        games = team_games.get(team, [])
        games.sort(key=lambda x: x["date"], reverse=True)
        if games:
            history[team] = games[:10]

    return history


# ── Main ─────────────────────────────────────────────────────────────────────
def main():
    all_upcoming  = []
    all_completed = []  # pool used to build team history

    for sport, league, friendly in ESPN_LEAGUES:
        # Today + tomorrow for upcoming fixtures
        for delta in [0, 1]:
            d = NOW + timedelta(days=delta)
            date_str = d.strftime("%Y%m%d")
            games, err = espn_scoreboard(sport, league, date_str, friendly)
            if err:
                print(f"[espn/{league}] {date_str}: {err}")
                continue
            for g in games:
                if g["status"] == "STATUS_FINAL":
                    all_completed.append(g)
                else:
                    all_upcoming.append(g)
            print(f"[espn/{league}] {date_str}: {len(games)} games")
            time.sleep(0.2)

        # Last 35 days for team history
        history_start = NOW - timedelta(days=35)
        print(f"[espn/{league}] fetching last 35 days of results for team history...")
        _, hist_games = espn_scoreboard_range(sport, league, friendly, history_start, 35)
        print(f"[espn/{league}] {len(hist_games)} completed games found in last 35 days")
        all_completed.extend(hist_games)
        time.sleep(0.2)

    # Deduplicate fixtures by (home, away, date)
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

    print(f"\n[collect] {len(fixtures)} upcoming fixtures")

    # Get all teams appearing in today's fixtures
    target_teams = set()
    for g in fixtures:
        target_teams.add(g["home_team"])
        target_teams.add(g["away_team"])
    target_teams.discard("")

    # Build history from completed scoreboard games
    team_history = build_team_history(all_completed, target_teams)

    # Report
    for team in sorted(target_teams):
        n = len(team_history.get(team, []))
        if n:
            avgt = sum(g["total"] for g in team_history[team]) / n
            print(f"  ✓ {team}: {n} games, avg total {avgt:.0f}")
        else:
            print(f"  ✗ {team}: no history in last 35 days")

    # Save
    save("data/fixtures.json", {
        "collected_at":  NOW.isoformat(),
        "dates":         [TODAY, TOMORROW],
        "total_games":   len(fixtures),
        "games":         fixtures,
        "source_errors": ERRORS,
    })

    by_league = {}
    for g in fixtures:
        lg = g.get("league", "?")
        by_league[lg] = by_league.get(lg, 0) + 1

    save("data/team_history.json", {
        "collected_at":          NOW.isoformat(),
        "teams_with_history":    len(team_history),
        "teams_without_history": len(target_teams) - len(team_history),
        "history":               team_history,
    })

    # Summary
    print()
    print("=" * 56)
    print("COLLECTION SUMMARY")
    print("=" * 56)
    for lg, cnt in sorted(by_league.items(), key=lambda x: -x[1]):
        print(f"  {lg:<30} {cnt} fixtures")
    print(f"  {'─'*44}")
    print(f"  TOTAL                          {len(fixtures)} fixtures")
    print(f"  Teams WITH history:            {len(team_history)}")
    print(f"  Teams WITHOUT history:         {len(target_teams) - len(team_history)}")
    if ERRORS:
        print(f"\n  ERRORS ({len(ERRORS)}):")
        for e in ERRORS:
            print(f"    ! {e}")


if __name__ == "__main__":
    main()
