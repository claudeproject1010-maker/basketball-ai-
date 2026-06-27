"""
generate_predictions.py  —  v3
--------------------------------
Statistical Over/Under engine.
Only uses historical completed games — never reads live/final scores.
"""

import json, math, os
from datetime import datetime, timezone

# ── League constants ─────────────────────────────────────────────────────────
HOME_ADV = {
    "NBA": 2.5, "WNBA": 2.0, "NCAA": 3.5,
    "EuroLeague": 3.0, "Liga ACB": 3.5, "BBL": 3.0,
    "NBL": 2.5, "Turkish BSL": 4.0, "default": 3.0,
}
LEAGUE_BASELINE = {
    "NBA": 226, "WNBA": 162, "NCAA": 150,
    "EuroLeague": 152, "Liga ACB": 158, "BBL": 154,
    "NBL": 180, "Turkish BSL": 155, "default": 160,
}
LEAGUE_TYPICAL_STD = {
    "NBA": 22, "WNBA": 17, "NCAA": 18,
    "EuroLeague": 15, "Liga ACB": 16, "default": 18,
}

# ── Helpers ──────────────────────────────────────────────────────────────────
def load(path):
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)

def mean(vals):
    v = [x for x in vals if x is not None]
    return sum(v) / len(v) if v else None

def std(vals):
    v = [x for x in vals if x is not None]
    if len(v) < 2:
        return None
    m = sum(v) / len(v)
    return math.sqrt(sum((x - m)**2 for x in v) / (len(v) - 1))

def trend(history):
    """last-3 avg / last-10 avg — returns 1.0 if not enough data"""
    totals = [g["total"] for g in history if g.get("total")]
    if len(totals) < 4:
        return 1.0
    r3 = mean(totals[:3])
    r10 = mean(totals)
    return (r3 / r10) if r3 and r10 and r10 > 0 else 1.0

def over_prob(predicted, hist_mean, hist_std):
    """P(total > predicted) via logistic approximation to normal CDF"""
    std_val = hist_std or 18.0
    if std_val < 5:
        std_val = 5.0
    z = (predicted - hist_mean) / std_val
    p_under = 1.0 / (1.0 + math.exp(-1.7 * z))
    return round(min(max(1.0 - p_under, 0.08), 0.92), 3)

# ── Feature extraction ───────────────────────────────────────────────────────
def features(history):
    if not history:
        return dict(scored=None, allowed=None, avg_total=None, std_total=None,
                    trend=1.0, n=0)
    scored  = mean([g["team_score"] for g in history])
    allowed = mean([g["opp_score"]  for g in history])
    totals  = [g["total"] for g in history if g.get("total")]
    return dict(
        scored    = scored,
        allowed   = allowed,
        avg_total = mean(totals),
        std_total = std(totals),
        trend     = trend(history),
        n         = len(history),
    )

# ── Prediction ───────────────────────────────────────────────────────────────
def predict(home_f, away_f, league):
    baseline = LEAGUE_BASELINE.get(league, LEAGUE_BASELINE["default"])
    home_adv = HOME_ADV.get(league, HOME_ADV["default"])

    def side_pts(off, def_):
        if off and def_:   return (off + def_) / 2
        if off:            return off
        if def_:           return def_
        return None

    home_exp = side_pts(home_f["scored"], away_f["allowed"])
    away_exp = side_pts(away_f["scored"], home_f["allowed"])

    if home_exp and away_exp:
        raw = home_exp + away_exp
        # weight toward team data as sample grows; full trust at 20 combined
        w = min((home_f["n"] + away_f["n"]) / 20.0, 1.0)
        predicted = w * raw + (1 - w) * baseline
    elif home_exp or away_exp:
        known = (home_exp or 0) + (away_exp or 0)
        predicted = 0.5 * (known + baseline / 2) + 0.5 * baseline
    else:
        predicted = baseline

    predicted += home_adv

    avg_trend = (home_f["trend"] + away_f["trend"]) / 2
    predicted *= (0.7 + 0.3 * avg_trend)

    return round(predicted, 1)

def confidence(n_home, n_away, prob):
    total = n_home + n_away
    edge  = abs(prob - 0.5)
    if total >= 16 and edge >= 0.15:  return "HIGH"
    if total >= 10 and edge >= 0.10:  return "MEDIUM"
    return "LOW"

# ── Main ─────────────────────────────────────────────────────────────────────
def main():
    fixtures_data = load("data/fixtures.json")
    history_data  = load("data/team_history.json")

    if not fixtures_data:
        print("[predict] ERROR: data/fixtures.json missing — run collect_fixtures.py first")
        return

    games      = fixtures_data.get("games", [])
    hist_map   = (history_data or {}).get("history", {})
    errors     = fixtures_data.get("source_errors", [])

    print(f"[predict] {len(games)} fixtures, {len(hist_map)} teams with history")
    if errors:
        print(f"[predict] {len(errors)} API errors during collection:")
        for e in errors[:5]:
            print(f"  ! {e}")

    predictions = []
    skipped_final = 0

    for g in games:
        home   = g.get("home_team", "")
        away   = g.get("away_team", "")
        league = g.get("league", "")
        status = g.get("status", "")

        # Skip finished games
        if status in ("STATUS_FINAL", "Final", "FT", "finished"):
            skipped_final += 1
            continue
        if not home or not away:
            continue

        hf = features(hist_map.get(home) or [])
        af = features(hist_map.get(away) or [])

        pred_total = predict(hf, af, league)
        baseline   = LEAGUE_BASELINE.get(league, LEAGUE_BASELINE["default"])
        league_std = LEAGUE_TYPICAL_STD.get(league, LEAGUE_TYPICAL_STD["default"])

        # Historical mean for probability: blend team avg_totals vs baseline
        hist_means = [m for m in [hf["avg_total"], af["avg_total"]] if m]
        hist_mean  = mean(hist_means) if hist_means else baseline

        # Std dev: team history std, fallback to league typical
        stds       = [s for s in [hf["std_total"], af["std_total"]] if s]
        hist_std   = mean(stds) if stds else league_std

        prob   = over_prob(pred_total, hist_mean, hist_std)
        conf   = confidence(hf["n"], af["n"], prob)
        edge   = round(pred_total - baseline, 1)

        predictions.append({
            "league":           league,
            "game":             f"{home} vs {away}",
            "home_team":        home,
            "away_team":        away,
            "date":             g.get("date", ""),
            "time_utc":         g.get("time_utc", ""),
            "predicted_total":  pred_total,
            "league_baseline":  baseline,
            "edge":             edge,
            "over_probability": prob,
            "under_probability":round(1 - prob, 3),
            "confidence":       conf,
            "home_avg_scored":  round(hf["scored"], 1)  if hf["scored"]  else None,
            "away_avg_scored":  round(af["scored"], 1)  if af["scored"]  else None,
            "home_avg_allowed": round(hf["allowed"], 1) if hf["allowed"] else None,
            "away_avg_allowed": round(af["allowed"], 1) if af["allowed"] else None,
            "home_avg_total":   round(hf["avg_total"], 1) if hf["avg_total"] else None,
            "away_avg_total":   round(af["avg_total"], 1) if af["avg_total"] else None,
            "home_games_used":  hf["n"],
            "away_games_used":  af["n"],
            "home_trend":       round(hf["trend"], 3),
            "away_trend":       round(af["trend"], 3),
            "source":           g.get("source", ""),
            "venue":            g.get("venue", ""),
        })

    # Sort: confidence tier → probability edge → games of data
    conf_order = {"HIGH": 3, "MEDIUM": 2, "LOW": 1}
    predictions.sort(
        key=lambda p: (conf_order[p["confidence"]], abs(p["over_probability"] - 0.5), p["home_games_used"] + p["away_games_used"]),
        reverse=True
    )

    top = predictions[:50]
    now = datetime.now(timezone.utc).isoformat()

    # Counts by confidence
    by_conf = {c: sum(1 for p in predictions if p["confidence"] == c) for c in ["HIGH","MEDIUM","LOW"]}
    no_history = sum(1 for p in predictions if p["home_games_used"] == 0 and p["away_games_used"] == 0)

    output = {
        "generated_at":         now,
        "total_games_analysed": len(predictions),
        "games_skipped_final":  skipped_final,
        "games_with_no_history":no_history,
        "by_confidence":        by_conf,
        "top_predictions":      top,
    }

    os.makedirs("data",        exist_ok=True)
    os.makedirs("public/data", exist_ok=True)
    for path in ["data/predictions.json", "public/data/predictions.json"]:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(output, f, indent=2)

    print(f"[predict] {len(predictions)} predictions → {len(top)} saved")
    print(f"  HIGH={by_conf['HIGH']}  MEDIUM={by_conf['MEDIUM']}  LOW={by_conf['LOW']}")
    print(f"  {no_history} games had zero history (will show league baseline only)")

if __name__ == "__main__":
    main()
