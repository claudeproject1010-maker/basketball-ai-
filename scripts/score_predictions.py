"""
score_predictions.py  v6
-------------------------
Self-scoring: fetches yesterday's actual results from ESPN + Sofascore,
matches against stored predictions, marks HIT/MISS, accumulates accuracy stats.
"""

import json, os, time
from datetime import datetime, timezone, timedelta
import urllib.request, urllib.error

NOW       = datetime.now(timezone.utc)
YESTERDAY = (NOW - timedelta(days=1))
YEST_ISO  = YESTERDAY.strftime("%Y-%m-%d")
YEST_ESPN = YESTERDAY.strftime("%Y%m%d")

print(f"[score] scoring predictions for {YEST_ISO}")

def fetch_espn(url, timeout=20):
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "application/json",
    })
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8", errors="replace"))
    except Exception:
        return None

def fetch_sofa(url, timeout=20):
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) "
                      "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1",
        "Accept": "application/json",
        "Referer": "https://www.sofascore.com/",
    })
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8", errors="replace"))
    except Exception:
        return None

def load(path):
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return None

def save(path, obj):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2)

# ── Fetch actual results ──────────────────────────────────────────────────────
def fetch_results(yest_iso, yest_espn):
    """Returns dict: (home_lower, away_lower) → {actual_total, home_score, away_score}"""
    results = {}

    # ESPN sources (only ones that don't 400)
    espn_leagues = ["wnba", "nba", "mens-college-basketball",
                    "womens-college-basketball", "nbl"]
    for slug in espn_leagues:
        url = (f"https://site.api.espn.com/apis/site/v2/sports/basketball/{slug}"
               f"/scoreboard?dates={yest_espn}&limit=200")
        data = fetch_espn(url)
        if not data:
            continue
        for ev in data.get("events", []):
            if ev.get("status", {}).get("type", {}).get("name") != "STATUS_FINAL":
                continue
            comp = (ev.get("competitions") or [{}])[0]
            teams = comp.get("competitors", [])
            if len(teams) < 2:
                continue
            home = next((c for c in teams if c.get("homeAway") == "home"), teams[0])
            away = next((c for c in teams if c.get("homeAway") == "away"), teams[1])
            try:
                hs  = int(home.get("score") or 0)
                as_ = int(away.get("score") or 0)
            except (ValueError, TypeError):
                continue
            if hs == 0 and as_ == 0:
                continue
            key = (home.get("team",{}).get("displayName","").lower(),
                   away.get("team",{}).get("displayName","").lower())
            results[key] = {"actual_total": hs+as_, "home_score": hs, "away_score": as_,
                            "home_team": home.get("team",{}).get("displayName",""),
                            "away_team": away.get("team",{}).get("displayName","")}
        time.sleep(0.1)

    # Sofascore (covers all international leagues)
    data = fetch_sofa(f"https://www.sofascore.com/api/v1/sport/basketball/scheduled-events/{yest_iso}")
    if data:
        for ev in data.get("events", []):
            if ev.get("status", {}).get("type") != "finished":
                continue
            hs  = ev.get("homeScore", {}).get("current")
            as_ = ev.get("awayScore", {}).get("current")
            if hs is None or as_ is None:
                continue
            home_name = ev.get("homeTeam", {}).get("name", "")
            away_name = ev.get("awayTeam", {}).get("name", "")
            key = (home_name.lower(), away_name.lower())
            results[key] = {"actual_total": hs+as_, "home_score": hs, "away_score": as_,
                            "home_team": home_name, "away_team": away_name}

    print(f"[score] {len(results)} completed games found for {yest_iso}")
    return results

# ── Archive & scoring ─────────────────────────────────────────────────────────
ARCHIVE_PATH = "data/predictions_archive.json"

def load_archive():
    d = load(ARCHIVE_PATH)
    return d if d else {"predictions": []}

def load_current_predictions():
    d = load("data/predictions.json")
    if not d:
        return []
    preds = d.get("top_predictions", [])
    gen = d.get("generated_at", "")
    for p in preds:
        p.setdefault("generated_at", gen)
        p.setdefault("scored", False)
        p.setdefault("result", None)
    return preds

def score_archive(archive, actual):
    newly = 0
    for p in archive["predictions"]:
        if p.get("scored"):
            continue
        if p.get("date", "") > YEST_ISO:
            continue
        key = (p.get("home_team","").lower(), p.get("away_team","").lower())
        if key not in actual:
            continue
        res    = actual[key]
        actual_total = res["actual_total"]
        pred   = p.get("predicted_total", 0)
        prob   = p.get("over_probability", 0.5)
        rec    = "OVER" if prob > 0.5 else "UNDER"
        outcome = "OVER" if actual_total > pred else ("UNDER" if actual_total < pred else "PUSH")
        hit    = (rec == outcome) if outcome != "PUSH" else None
        p.update({
            "scored": True, "actual_total": actual_total,
            "actual_home": res["home_score"], "actual_away": res["away_score"],
            "actual_outcome": outcome, "recommended": rec, "hit": hit,
            "error": round(actual_total - pred, 1),
            "abs_error": round(abs(actual_total - pred), 1),
            "scored_at": NOW.isoformat(),
        })
        newly += 1
    print(f"[score] {newly} predictions newly scored")
    return archive

def compute_accuracy(archive):
    scored = [p for p in archive["predictions"] if p.get("scored") and p.get("hit") is not None]
    if not scored:
        return {"total_scored": 0, "message": "No predictions scored yet"}
    hits = [p for p in scored if p["hit"]]
    total = len(scored)
    by_conf = {}
    for conf in ["HIGH","MEDIUM","LOW"]:
        sub = [p for p in scored if p.get("confidence") == conf]
        if sub:
            ch = sum(1 for p in sub if p["hit"])
            by_conf[conf] = {"total": len(sub), "hits": ch, "hit_rate": round(ch/len(sub)*100, 1)}
    by_league = {}
    for p in scored:
        lg = p.get("league","Unknown")
        by_league.setdefault(lg, {"total":0,"hits":0})
        by_league[lg]["total"] += 1
        if p["hit"]: by_league[lg]["hits"] += 1
    for lg in by_league:
        t = by_league[lg]["total"]; h = by_league[lg]["hits"]
        by_league[lg]["hit_rate"] = round(h/t*100, 1)
    recent = sorted(scored, key=lambda x: x.get("date",""), reverse=True)[:20]
    rh = sum(1 for p in recent if p["hit"])
    last10 = sorted(scored, key=lambda x: x.get("date",""), reverse=True)[:10]
    return {
        "computed_at": NOW.isoformat(),
        "total_scored": total, "total_hits": len(hits),
        "overall_hit_rate": round(len(hits)/total*100, 1),
        "avg_abs_error": round(sum(p["abs_error"] for p in scored)/total, 1),
        "recent_20_hit_rate": round(rh/len(recent)*100, 1) if recent else 0,
        "by_confidence": by_conf,
        "by_league": by_league,
        "last_10_results": [
            {"date": p["date"], "game": p["game"], "league": p.get("league",""),
             "confidence": p.get("confidence",""), "predicted": p.get("predicted_total"),
             "actual": p.get("actual_total"), "error": p.get("error"),
             "recommended": p.get("recommended"), "outcome": p.get("actual_outcome"), "hit": p.get("hit")}
            for p in last10
        ],
    }

def main():
    actual  = fetch_results(YEST_ISO, YEST_ESPN)
    archive = load_archive()
    current = load_current_predictions()

    existing = {(p["game"], p["date"]) for p in archive["predictions"]}
    added = 0
    for p in current:
        k = (p["game"], p["date"])
        if k not in existing:
            archive["predictions"].append(p); existing.add(k); added += 1
    if added: print(f"[score] +{added} predictions added to archive")

    archive  = score_archive(archive, actual)
    accuracy = compute_accuracy(archive)
    save(ARCHIVE_PATH, archive)
    save("data/accuracy.json", accuracy)
    save("public/data/accuracy.json", accuracy)

    if accuracy.get("total_scored", 0) > 0:
        print(f"[score] Hit rate: {accuracy['overall_hit_rate']}% "
              f"({accuracy['total_hits']}/{accuracy['total_scored']}) "
              f"| Avg error: ±{accuracy['avg_abs_error']} pts")
    else:
        print("[score] No predictions scored yet")

if __name__ == "__main__":
    main()
