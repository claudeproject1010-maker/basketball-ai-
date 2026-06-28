"""
collect_fixtures.py  v6
-----------------------
Data sources:
  1. ESPN hidden API  — WNBA, NBA, NCAA, NBL (North America/Australia)
  2. Sofascore API    — 500+ leagues including all international basketball
                        (VBA Vietnam, PBA Philippines, ACB Spain, EuroLeague,
                         KBL Korea, CBA China, LNB France, BBL UK, etc.)

Both sources are free and require no API key.
Sofascore uses their undocumented internal API (same one that powers their website).
"""

import json, os, time
from datetime import datetime, timezone, timedelta
import urllib.request, urllib.error

NOW      = datetime.now(timezone.utc)
TODAY    = NOW.strftime("%Y-%m-%d")
TOMORROW = (NOW + timedelta(days=1)).strftime("%Y-%m-%d")

print(f"[collect] {TODAY}  UTC {NOW.strftime('%H:%M')}")
ERRORS = []

# ── HTTP helpers ─────────────────────────────────────────────────────────────
def fetch_espn(url, timeout=20):
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "application/json",
    })
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8", errors="replace")), None
    except urllib.error.HTTPError as e:
        if e.code not in (404, 400):
            ERRORS.append(f"ESPN HTTP {e.code} — {url[:90]}")
        return None, f"HTTP {e.code}"
    except Exception as e:
        ERRORS.append(f"ESPN {type(e).__name__} — {url[:90]}")
        return None, str(e)

def fetch_sofa(url, timeout=20):
    """Sofascore needs specific headers to avoid Cloudflare blocks."""
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) "
                      "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1",
        "Accept": "application/json",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://www.sofascore.com/",
        "Origin": "https://www.sofascore.com",
    })
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8", errors="replace")), None
    except urllib.error.HTTPError as e:
        ERRORS.append(f"Sofascore HTTP {e.code} — {url[:90]}")
        return None, f"HTTP {e.code}"
    except Exception as e:
        ERRORS.append(f"Sofascore {type(e).__name__} — {url[:90]}")
        return None, str(e)

def save(path, obj):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2)
    print(f"[save]  {path}  ({len(json.dumps(obj))//1024} KB)")


# ══════════════════════════════════════════════════════════════════════════════
# SOURCE 1: ESPN
# ══════════════════════════════════════════════════════════════════════════════

ESPN_LEAGUES = [
    # (sport_slug, league_slug, display_name, history_days)
    # Active year-round at different seasons — all collected, empty ones return 0 silently
    ("basketball", "wnba",                     "WNBA",   50),
    ("basketball", "nba",                      "NBA",    50),
    ("basketball", "mens-college-basketball",  "NCAA",   50),
    ("basketball", "womens-college-basketball","NCAAW",  50),
    ("basketball", "nbl",                      "NBL",    60),
]

def espn_scoreboard(sport, league_slug, friendly, date_str):
    url = (f"https://site.api.espn.com/apis/site/v2/sports/{sport}/{league_slug}"
           f"/scoreboard?dates={date_str}&limit=200")
    data, err = fetch_espn(url)
    if not data:
        return [], err
    games = []
    for ev in data.get("events", []):
        comp        = (ev.get("competitions") or [{}])[0]
        competitors = comp.get("competitors", [])
        if len(competitors) < 2:
            continue
        home = next((c for c in competitors if c.get("homeAway") == "home"), competitors[0])
        away = next((c for c in competitors if c.get("homeAway") == "away"), competitors[1])
        status = ev.get("status", {}).get("type", {}).get("name", "")
        gdt    = ev.get("date", "")
        hs = as_ = None
        if status == "STATUS_FINAL":
            try:
                hs  = int(home.get("score") or 0)
                as_ = int(away.get("score") or 0)
            except (ValueError, TypeError):
                pass
        games.append({
            "source":       f"espn_{league_slug}",
            "league":       friendly,
            "home_team":    home.get("team", {}).get("displayName", ""),
            "away_team":    away.get("team", {}).get("displayName", ""),
            "home_team_id": home.get("team", {}).get("id"),
            "away_team_id": away.get("team", {}).get("id"),
            "date":         gdt[:10] if gdt else date_str[:4]+"-"+date_str[4:6]+"-"+date_str[6:],
            "time_utc":     gdt,
            "status":       status,
            "home_score":   hs,
            "away_score":   as_,
            "venue":        comp.get("venue", {}).get("fullName", ""),
        })
    return games, None

def espn_history_range(sport, league_slug, friendly, days_back):
    completed = []
    for i in range(days_back):
        d = NOW - timedelta(days=i+1)
        games, _ = espn_scoreboard(sport, league_slug, friendly, d.strftime("%Y%m%d"))
        for g in games:
            if g["status"] == "STATUS_FINAL" and g["home_score"] is not None:
                completed.append(g)
        time.sleep(0.1)
    return completed


# ══════════════════════════════════════════════════════════════════════════════
# SOURCE 2: Sofascore
# Covers 500+ basketball leagues internationally, no key required
# ══════════════════════════════════════════════════════════════════════════════

def sofa_fixtures(date_iso):
    """
    Fetch all basketball events on a given date from Sofascore.
    Returns (upcoming_games, completed_games)
    sport slug for basketball = 'basketball'
    """
    url = f"https://www.sofascore.com/api/v1/sport/basketball/scheduled-events/{date_iso}"
    data, err = fetch_sofa(url)
    if not data:
        print(f"  [sofascore] {date_iso}: {err}")
        return [], []

    upcoming, completed = [], []
    for ev in data.get("events", []):
        status_code = ev.get("status", {}).get("type", "")
        home_t = ev.get("homeTeam", {})
        away_t = ev.get("awayTeam", {})
        tournament = ev.get("tournament", {})
        category   = tournament.get("category", {})

        home_name = home_t.get("name", "")
        away_name = away_t.get("name", "")
        if not home_name or not away_name:
            continue

        league_name = tournament.get("name", "")
        country     = category.get("name", "")
        # Build a friendly league display name
        if country and country.lower() not in league_name.lower():
            display_league = f"{league_name} ({country})"
        else:
            display_league = league_name

        # Convert Sofascore timestamp to ISO
        start_ts = ev.get("startTimestamp")
        if start_ts:
            dt = datetime.fromtimestamp(start_ts, tz=timezone.utc)
            time_utc = dt.isoformat()
            game_date = dt.strftime("%Y-%m-%d")
        else:
            time_utc  = ""
            game_date = date_iso

        home_score = away_score = None
        if ev.get("homeScore"):
            home_score = ev["homeScore"].get("current")
        if ev.get("awayScore"):
            away_score = ev["awayScore"].get("current")

        game = {
            "source":       "sofascore",
            "league":       display_league,
            "league_short": league_name,
            "country":      country,
            "home_team":    home_name,
            "away_team":    away_name,
            "home_team_id": str(home_t.get("id", "")),
            "away_team_id": str(away_t.get("id", "")),
            "sofa_event_id": str(ev.get("id", "")),
            "date":         game_date,
            "time_utc":     time_utc,
            "status":       status_code,
            "home_score":   home_score,
            "away_score":   away_score,
            "venue":        ev.get("venue", {}).get("stadium", {}).get("name", "") if ev.get("venue") else "",
        }

        if status_code in ("notstarted", "inprogress"):
            upcoming.append(game)
        elif status_code == "finished" and home_score is not None and away_score is not None:
            completed.append(game)

    return upcoming, completed

def sofa_team_history(team_id, team_name, n=10):
    """Fetch last N completed games for a team via Sofascore."""
    if not team_id:
        return []
    url = f"https://www.sofascore.com/api/v1/team/{team_id}/events/last/0"
    data, err = fetch_sofa(url)
    if not data:
        return []
    history = []
    for ev in data.get("events", []):
        if ev.get("status", {}).get("type") != "finished":
            continue
        home_t = ev.get("homeTeam", {})
        away_t = ev.get("awayTeam", {})
        hs = ev.get("homeScore", {}).get("current")
        as_ = ev.get("awayScore", {}).get("current")
        if hs is None or as_ is None:
            continue
        is_home = str(home_t.get("id","")) == str(team_id)
        ts  = hs if is_home else as_
        os_ = as_ if is_home else hs
        start_ts = ev.get("startTimestamp")
        game_date = datetime.fromtimestamp(start_ts, tz=timezone.utc).strftime("%Y-%m-%d") if start_ts else ""
        history.append({
            "date":       game_date,
            "opponent":   away_t.get("name","") if is_home else home_t.get("name",""),
            "team_score": ts,
            "opp_score":  os_,
            "total":      hs + as_,
            "home":       is_home,
            "result":     "W" if ts > os_ else "L",
        })
    history.sort(key=lambda x: x["date"], reverse=True)
    return history[:n]


# ══════════════════════════════════════════════════════════════════════════════
# Build team history from completed scoreboard games
# ══════════════════════════════════════════════════════════════════════════════

def build_history_from_games(completed_games, target_teams):
    team_games = {}
    for g in completed_games:
        home, away = g["home_team"], g["away_team"]
        hs = g.get("home_score") or 0
        as_ = g.get("away_score") or 0
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


# ══════════════════════════════════════════════════════════════════════════════
# Deduplication
# ══════════════════════════════════════════════════════════════════════════════

def dedup(games):
    seen = {}
    for g in games:
        key = (g["home_team"].lower().strip(), g["away_team"].lower().strip(), g["date"])
        if key not in seen:
            seen[key] = g
        else:
            for k, v in g.items():
                if not seen[key].get(k):
                    seen[key][k] = v
    return list(seen.values())


# ══════════════════════════════════════════════════════════════════════════════
# Main
# ══════════════════════════════════════════════════════════════════════════════

def main():
    all_upcoming  = []
    all_completed = []   # pool for building team history

    # ── Source 1: ESPN ───────────────────────────────────────────────────────
    print("\n[ESPN]")
    for sport, slug, friendly, hist_days in ESPN_LEAGUES:
        league_up = []
        for delta in [0, 1]:
            d = NOW + timedelta(days=delta)
            games, err = espn_scoreboard(sport, slug, friendly, d.strftime("%Y%m%d"))
            if err and "404" not in err and "400" not in err:
                print(f"  [{slug}] {err}")
            for g in games:
                if g["status"] in ("STATUS_SCHEDULED", "STATUS_IN_PROGRESS"):
                    league_up.append(g)
                elif g["status"] == "STATUS_FINAL" and g["home_score"] is not None:
                    all_completed.append(g)
            time.sleep(0.15)
        if league_up:
            print(f"  [{slug}] {len(league_up)} upcoming games")
            all_upcoming.extend(league_up)

        # History
        hist = espn_history_range(sport, slug, friendly, hist_days)
        if hist:
            print(f"  [{slug}] {len(hist)} historical results ({hist_days}d)")
            all_completed.extend(hist)

    # ── Source 2: Sofascore ──────────────────────────────────────────────────
    print("\n[Sofascore]")
    sofa_completed_all = []
    for delta, label in [(0, TODAY), (1, TOMORROW)]:
        d = (NOW + timedelta(days=delta)).strftime("%Y-%m-%d")
        up, comp = sofa_fixtures(d)
        print(f"  [{d}] {len(up)} upcoming, {len(comp)} completed")
        all_upcoming.extend(up)
        sofa_completed_all.extend(comp)

    # History from Sofascore: fetch past 30 days
    for i in range(1, 31):
        d = (NOW - timedelta(days=i)).strftime("%Y-%m-%d")
        _, comp = sofa_fixtures(d)
        sofa_completed_all.extend(comp)
        time.sleep(0.3)   # be polite to Sofascore
    print(f"  [history] {len(sofa_completed_all)} completed games from last 30d")
    all_completed.extend(sofa_completed_all)

    # ── Deduplicate fixtures ─────────────────────────────────────────────────
    fixtures = dedup(all_upcoming)
    print(f"\n[collect] {len(fixtures)} unique fixtures across {len(set(g['league'] for g in fixtures))} leagues")

    # ── Team history ─────────────────────────────────────────────────────────
    target_teams = {g["home_team"] for g in fixtures} | {g["away_team"] for g in fixtures}
    target_teams.discard("")

    # Build from completed scoreboard data first
    team_history = build_history_from_games(all_completed, target_teams)

    # For any team still missing history, try Sofascore team endpoint directly
    missing = [t for t in target_teams if t not in team_history]
    if missing:
        print(f"  [sofascore] fetching team history for {len(missing)} teams with no data...")
        # Build team_id lookup from fixtures
        id_map = {}
        for g in fixtures:
            if g.get("source") == "sofascore":
                if g["home_team"] not in id_map and g.get("home_team_id"):
                    id_map[g["home_team"]] = g["home_team_id"]
                if g["away_team"] not in id_map and g.get("away_team_id"):
                    id_map[g["away_team"]] = g["away_team_id"]
        for team in missing:
            tid = id_map.get(team)
            if tid:
                hist = sofa_team_history(tid, team)
                if hist:
                    team_history[team] = hist
                    print(f"    ✓ {team}: {len(hist)} games via Sofascore team endpoint")
                time.sleep(0.4)

    # Report
    for team in sorted(target_teams):
        n = len(team_history.get(team, []))
        if n:
            avgt = sum(g["total"] for g in team_history[team]) / n
            print(f"  ✓ {team}: {n} games, avg total {avgt:.0f}")
        else:
            print(f"  ✗ {team}: no history")

    # ── Summary ──────────────────────────────────────────────────────────────
    by_league = {}
    for g in fixtures:
        lg = g.get("league","?")
        by_league[lg] = by_league.get(lg, 0) + 1

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
    by_source = {}
    for g in fixtures:
        s = "ESPN" if g["source"].startswith("espn") else "Sofascore"
        by_source[s] = by_source.get(s,0) + 1
    for s, c in sorted(by_source.items()):
        print(f"  Source: {s:<15} {c} fixtures")
    print()
    for lg, cnt in sorted(by_league.items(), key=lambda x: -x[1])[:20]:
        print(f"  {lg:<36} {cnt}")
    if len(by_league) > 20:
        print(f"  ... and {len(by_league)-20} more leagues")
    print(f"  {'─'*44}")
    print(f"  TOTAL                                {len(fixtures)}")
    print(f"  Teams with history:                  {len(team_history)}")
    print(f"  Teams without history:               {len(target_teams)-len(team_history)}")
    if ERRORS:
        print(f"\n  ERRORS ({len(ERRORS)}):")
        for e in ERRORS[:8]:
            print(f"    ! {e}")

if __name__ == "__main__":
    main()
