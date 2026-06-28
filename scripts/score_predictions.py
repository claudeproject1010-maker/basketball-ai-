"""
score_predictions.py  v1
-------------------------
Self-scoring system: compares yesterday's predictions against actual results.

Pipeline:
  1. Load data/predictions_archive.json  (all past predictions)
  2. Fetch yesterday's ESPN scoreboard results (actual totals)
  3. For each prediction that now has a result:
       - Mark HIT or MISS
       - Record actual total vs predicted total
  4. Save updated archive + accuracy stats to data/accuracy.json
  5. Also writes public/data/accuracy.json so dashboard shows it

Run after generate_predictions.py in the GitHub Action.
"""

import json, os, time
from datetime import datetime, timezone, timedelta
import urllib.request, urllib.error

NOW       = datetime.now(timezone.utc)
YESTERDAY = (NOW - timedelta(days=1)).strftime("%Y%m%d")
Y_ISO     = (NOW - timedelta(days=1)).strftime("%Y-%m-%d")

print(f"[score] scoring predictions for {Y_ISO}")

def fetch(url, timeout=20):
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "application/json",
    })
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8", errors="replace"))
    except Exception as e:
        print(f"[score] fetch error: {e}  url={url[:80]}")
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

# ── ESPN leagues to check for results ───────────────────────────────────────
RESULT_LEAGUES = [
    ("basketball", "wnba"),
    ("basketball", "nba"),
    ("basketball", "mens-college-basketball"),
    ("basketball", "womens-college-basketball"),
    ("basketball", "nbl"),
    ("basketball", "vba"),
    ("basketball", "pba"),
    ("basketball", "kbl"),
    ("basketball", "cba"),
    ("basketball", "acb"),
    ("basketball", "euroleague"),
    ("basketball", "eurocup"),
    ("basketball", "bbl"),
    ("basketball", "lnb"),
]

# ── Fetch actual results for yesterday ───────────────────────────────────────
def fetch_results(date_str):
    """Returns dict: (home_team_lower, away_team_lower) → actual_total"""
    results = {}
    for sport, league in RESULT_LEAGUES:
        url = (
            f"https://site.api.espn.com/apis/site/v2/sports/{sport}/{league}"
            f"/scoreboard?dates={date_str}&limit=200"
        )
        data = fetch(url)
        if not data:
            continue
        for ev in data.get("events", []):
            status = ev.get("status", {}).get("type", {}).get("name", "")
            if status != "STATUS_FINAL":
                continue
            comp = (ev.get("competitions") or [{}])[0]
            competitors = comp.get("competitors", [])
            if len(competitors) < 2:
                continue
            home = next((c for c in competitors if c.get("homeAway") == "home"), competitors[0])
            away = next((c for c in competitors if c.get("homeAway") == "away"), competitors[1])
            try:
                hs = int(home.get("score") or 0)
                as_ = int(away.get("score") or 0)
            except (ValueError, TypeError):
                continue
            if hs == 0 and as_ == 0:
                continue
            key = (
                home.get("team", {}).get("displayName", "").lower(),
                away.get("team", {}).get("displayName", "").lower(),
            )
            results[key] = {
                "actual_total": hs + as_,
                "home_score":   hs,
                "away_score":   as_,
                "home_team":    home.get("team", {}).get("displayName", ""),
                "away_team":    away.get("team", {}).get("displayName", ""),
            }
        time.sleep(0.15)
    print(f"[score] found {len(results)} completed games for {date_str}")
    return results


# ── Archive management ────────────────────────────────────────────────────────
ARCHIVE_PATH = "data/predictions_archive.json"
ACCURACY_PATH = "data/accuracy.json"
PUBLIC_ACCURACY = "public/data/accuracy.json"

def load_archive():
    data = load(ARCHIVE_PATH)
    if data:
        return data
    return {"predictions": []}

def load_current_predictions():
    data = load("data/predictions.json")
    if not data:
        return []
    preds = data.get("top_predictions", [])
    gen_at = data.get("generated_at", "")
    # Tag each prediction with when it was generated
    for p in preds:
        p.setdefault("generated_at", gen_at)
        p.setdefault("scored", False)
        p.setdefault("result", None)
    return preds


def score_archive(archive, actual_results):
    """
    Go through archive predictions and mark any that now have results.
    A prediction is scoreable if:
      - scored=False
      - its date <= yesterday
    """
    newly_scored = 0
    for p in archive["predictions"]:
        if p.get("scored"):
            continue
        pred_date = p.get("date", "")
        if pred_date > Y_ISO:
            continue  # future game, can't score yet

        key = (p.get("home_team", "").lower(), p.get("away_team", "").lower())
        if key not in actual_results:
            continue

        result = actual_results[key]
        actual = result["actual_total"]
        predicted = p.get("predicted_total", 0)
        over_prob = p.get("over_probability", 0.5)

        # Determine hit/miss:
        # The prediction recommends OVER if over_prob > 0.5, UNDER otherwise
        recommended = "OVER" if over_prob > 0.5 else "UNDER"
        actual_outcome = "OVER" if actual > predicted else ("UNDER" if actual < predicted else "PUSH")
        hit = (recommended == actual_outcome) if actual_outcome != "PUSH" else None

        p.update({
            "scored":           True,
            "actual_total":     actual,
            "actual_home":      result["home_score"],
            "actual_away":      result["away_score"],
            "actual_outcome":   actual_outcome,
            "recommended":      recommended,
            "hit":              hit,
            "error":            round(actual - predicted, 1),
            "abs_error":        round(abs(actual - predicted), 1),
            "scored_at":        NOW.isoformat(),
        })
        newly_scored += 1

    print(f"[score] {newly_scored} predictions newly scored")
    return archive


def compute_accuracy(archive):
    """Compute accuracy stats from all scored predictions."""
    scored = [p for p in archive["predictions"] if p.get("scored") and p.get("hit") is not None]
    if not scored:
        return {"total_scored": 0, "message": "No predictions scored yet"}

    hits  = [p for p in scored if p["hit"]]
    total = len(scored)
    hit_rate = round(len(hits) / total * 100, 1)
    avg_error = round(sum(p["abs_error"] for p in scored) / total, 1)

    # By confidence tier
    by_conf = {}
    for conf in ["HIGH", "MEDIUM", "LOW"]:
        subset = [p for p in scored if p.get("confidence") == conf]
        if subset:
            conf_hits = sum(1 for p in subset if p["hit"])
            by_conf[conf] = {
                "total":    len(subset),
                "hits":     conf_hits,
                "hit_rate": round(conf_hits / len(subset) * 100, 1),
            }

    # By league
    by_league = {}
    for p in scored:
        lg = p.get("league", "Unknown")
        if lg not in by_league:
            by_league[lg] = {"total": 0, "hits": 0}
        by_league[lg]["total"] += 1
        if p["hit"]:
            by_league[lg]["hits"] += 1
    for lg in by_league:
        t = by_league[lg]["total"]
        h = by_league[lg]["hits"]
        by_league[lg]["hit_rate"] = round(h / t * 100, 1)

    # Recent form (last 20)
    recent = sorted(scored, key=lambda x: x.get("date",""), reverse=True)[:20]
    recent_hits = sum(1 for p in recent if p["hit"])
    recent_rate = round(recent_hits / len(recent) * 100, 1) if recent else 0

    # Last 10 scored results for dashboard display
    last10 = sorted(scored, key=lambda x: x.get("date",""), reverse=True)[:10]

    return {
        "computed_at":    NOW.isoformat(),
        "total_scored":   total,
        "total_hits":     len(hits),
        "overall_hit_rate": hit_rate,
        "avg_abs_error":  avg_error,
        "recent_20_hit_rate": recent_rate,
        "by_confidence":  by_conf,
        "by_league":      by_league,
        "last_10_results": [
            {
                "date":          p["date"],
                "game":          p["game"],
                "league":        p.get("league",""),
                "confidence":    p.get("confidence",""),
                "predicted":     p.get("predicted_total"),
                "actual":        p.get("actual_total"),
                "error":         p.get("error"),
                "recommended":   p.get("recommended"),
                "outcome":       p.get("actual_outcome"),
                "hit":           p.get("hit"),
            }
            for p in last10
        ],
    }


# ── Main ─────────────────────────────────────────────────────────────────────
def main():
    # 1. Fetch actual results
    actual = fetch_results(YESTERDAY)

    # 2. Load archive; add today's predictions if not already there
    archive = load_archive()
    current = load_current_predictions()

    # Add current predictions to archive (avoid duplicates by game+date)
    existing_keys = {(p["game"], p["date"]) for p in archive["predictions"]}
    added = 0
    for p in current:
        key = (p["game"], p["date"])
        if key not in existing_keys:
            archive["predictions"].append(p)
            existing_keys.add(key)
            added += 1
    if added:
        print(f"[score] added {added} new predictions to archive")

    # 3. Score any that now have results
    archive = score_archive(archive, actual)

    # 4. Compute accuracy stats
    accuracy = compute_accuracy(archive)

    # 5. Save everything
    save(ARCHIVE_PATH, archive)
    save(ACCURACY_PATH, accuracy)
    save(PUBLIC_ACCURACY, accuracy)

    # Print summary
    if accuracy.get("total_scored", 0) > 0:
        print(f"[score] Overall hit rate: {accuracy['overall_hit_rate']}% "
              f"({accuracy['total_hits']}/{accuracy['total_scored']}) "
              f"| Avg error: ±{accuracy['avg_abs_error']} pts")
        bc = accuracy.get("by_confidence", {})
        for conf in ["HIGH","MEDIUM","LOW"]:
            if conf in bc:
                print(f"  {conf}: {bc[conf]['hit_rate']}% ({bc[conf]['hits']}/{bc[conf]['total']})")
    else:
        print("[score] No predictions scored yet — will score after first game completes")


if __name__ == "__main__":
    main()
