"""
generate_predictions.py
-----------------------
Statistical Over/Under prediction engine.

Model pipeline:
  1. Load fixtures + team history (last 10 games each side)
  2. For each upcoming game compute features:
       - home/away avg points scored (last 10)
       - home/away avg points allowed (last 10)
       - implied total via pace-adjusted blending
       - home advantage adjustment
       - recent form trend (last 3 vs last 10)
       - variance / consistency of totals
  3. Predicted total = weighted blend of scoring/defending averages
  4. Over probability via z-score against historical std dev
  5. Confidence = data quality score (how many games of history we have)
  6. Output top predictions sorted by edge then confidence
"""

import json
import math
import os
from datetime import datetime, timezone


# ─── Constants ────────────────────────────────────────────────────────────────

# League-specific home advantage in points (empirical)
HOME_ADV = {
    "NBA": 2.5,
    "WNBA": 2.0,
    "NCAA": 3.5,
    "EuroLeague": 3.0,
    "Liga ACB": 3.5,
    "BBL": 3.0,
    "NBL": 2.5,
    "Turkish BSL": 4.0,
    "default": 3.0,
}

# League pace factors — relative to NBA baseline of 100
# Used to normalise across leagues when history is sparse
LEAGUE_PACE = {
    "NBA": 1.00,
    "WNBA": 0.88,
    "NCAA": 0.93,
    "EuroLeague": 0.87,
    "Liga ACB": 0.88,
    "BBL": 0.85,
    "NBL": 0.90,
    "Turkish BSL": 0.86,
    "default": 0.90,
}

# League baseline totals (fallback when we have no history at all)
LEAGUE_BASELINE = {
    "NBA": 226,
    "WNBA": 162,
    "NCAA": 150,
    "EuroLeague": 152,
    "Liga ACB": 158,
    "BBL": 154,
    "NBL": 180,
    "Turkish BSL": 155,
    "default": 160,
}

MIN_GAMES_FOR_CONFIDENCE = 5   # fewer → LOW confidence
GOOD_GAMES_FOR_CONFIDENCE = 8  # 8+ → HIGH confidence possible


# ─── Helpers ──────────────────────────────────────────────────────────────────

def load_json(path):
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def safe_mean(values):
    vals = [v for v in values if v is not None]
    return sum(vals) / len(vals) if vals else None


def safe_std(values):
    vals = [v for v in values if v is not None]
    if len(vals) < 2:
        return None
    m = sum(vals) / len(vals)
    variance = sum((v - m) ** 2 for v in vals) / (len(vals) - 1)
    return math.sqrt(variance)


def trend_factor(history, field="total"):
    """
    Returns a multiplier: >1 means recent games are scoring MORE than
    the last-10 average (upward trend), <1 means downward.
    Only uses the 3 most recent vs 10 most recent.
    """
    vals = [g[field] for g in history if g.get(field) is not None]
    if len(vals) < 4:
        return 1.0
    recent3 = safe_mean(vals[:3])
    avg10 = safe_mean(vals)
    if not recent3 or not avg10 or avg10 == 0:
        return 1.0
    return recent3 / avg10


def z_score_probability(predicted, historical_mean, historical_std, direction="over"):
    """
    P(total > predicted) using normal approximation.
    If we don't have std dev, use a league-typical value.
    """
    std = historical_std or 18.0   # ~18 pts is typical game-total std in NBA
    if std < 5:
        std = 5.0
    z = (predicted - historical_mean) / std
    # Approximate P(X > predicted) using logistic approximation to normal CDF
    # P(Z < z) ≈ 1 / (1 + exp(-1.7 * z))
    p_under = 1.0 / (1.0 + math.exp(-1.7 * z))
    p_over = 1.0 - p_under
    return round(min(max(p_over, 0.10), 0.92), 3)


# ─── Feature extraction ───────────────────────────────────────────────────────

def extract_team_features(team_name, history, side="home"):
    """
    Given last-N game history for a team, return a dict of features:
      - avg_scored     : average points scored per game
      - avg_allowed    : average points allowed per game
      - avg_total      : average game total (both teams)
      - std_total      : std dev of game totals
      - trend          : recent scoring trend multiplier
      - games_used     : how many games were actually used
    """
    if not history:
        return {
            "avg_scored": None,
            "avg_allowed": None,
            "avg_total": None,
            "std_total": None,
            "trend": 1.0,
            "games_used": 0,
        }

    scored = [g["team_score"] for g in history if g.get("team_score") is not None]
    allowed = [g["opp_score"] for g in history if g.get("opp_score") is not None]
    totals = [g["total"] for g in history if g.get("total") is not None]

    return {
        "avg_scored": safe_mean(scored),
        "avg_allowed": safe_mean(allowed),
        "avg_total": safe_mean(totals),
        "std_total": safe_std(totals),
        "trend": trend_factor(history),
        "games_used": len(history),
    }


def predict_game_total(home_feat, away_feat, league, home_adv_pts):
    """
    Predict the combined game total using team features.

    Formula:
      - home_expected = (home_avg_scored + away_avg_allowed) / 2
      - away_expected = (away_avg_scored + home_avg_allowed) / 2
      - predicted_total = home_expected + away_expected
      - Apply home advantage
      - Apply trend adjustment (blend 30% trend, 70% mean)
      - If either side missing, fall back to league baseline
    """
    baseline = LEAGUE_BASELINE.get(league, LEAGUE_BASELINE["default"])

    def side_score(offense_avg, defense_avg):
        if offense_avg and defense_avg:
            return (offense_avg + defense_avg) / 2
        elif offense_avg:
            return offense_avg
        elif defense_avg:
            return defense_avg
        return None

    home_exp = side_score(home_feat["avg_scored"], away_feat["avg_allowed"])
    away_exp = side_score(away_feat["avg_scored"], home_feat["avg_allowed"])

    if home_exp and away_exp:
        raw_total = home_exp + away_exp
        # blend in league baseline when sample is small
        home_games = home_feat["games_used"]
        away_games = away_feat["games_used"]
        weight = min((home_games + away_games) / 20, 1.0)  # full trust at 20+ games total
        predicted = weight * raw_total + (1 - weight) * baseline
    elif home_exp or away_exp:
        known = (home_exp or 0) + (away_exp or 0)
        predicted = known + baseline / 2
        predicted = 0.5 * predicted + 0.5 * baseline
    else:
        predicted = baseline

    # Home advantage
    predicted += home_adv_pts

    # Trend adjustment (blend)
    home_trend = home_feat["trend"]
    away_trend = away_feat["trend"]
    avg_trend = (home_trend + away_trend) / 2
    predicted = predicted * (0.7 + 0.3 * avg_trend)

    return round(predicted, 1)


def compute_over_probability(predicted_total, home_feat, away_feat, league):
    """
    Calculate P(actual total > predicted_total) using historical variance.
    """
    # Combine std devs from both teams' game totals
    stds = [s for s in [home_feat["std_total"], away_feat["std_total"]] if s]
    combined_std = safe_mean(stds) if stds else None

    # Historical mean total from the two teams' averages
    hist_means = [m for m in [home_feat["avg_total"], away_feat["avg_total"]] if m]
    historical_mean = safe_mean(hist_means) if hist_means else LEAGUE_BASELINE.get(league, 160)

    return z_score_probability(predicted_total, historical_mean, combined_std)


def confidence_label(home_games, away_games, over_prob):
    """
    Confidence based on data quality + probability edge.
    """
    total_games = home_games + away_games
    if total_games >= GOOD_GAMES_FOR_CONFIDENCE * 2 and (over_prob >= 0.65 or over_prob <= 0.35):
        return "HIGH"
    elif total_games >= MIN_GAMES_FOR_CONFIDENCE and (over_prob >= 0.60 or over_prob <= 0.40):
        return "MEDIUM"
    return "LOW"


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    fixtures_data = load_json("data/fixtures.json")
    history_data = load_json("data/team_history.json")

    if not fixtures_data:
        print("[predict] ERROR: data/fixtures.json not found")
        return

    games = fixtures_data.get("games", [])
    history_map = (history_data or {}).get("history", {})

    print(f"[predict] {len(games)} fixtures loaded, {len(history_map)} teams with history")

    predictions = []

    for game in games:
        home = game.get("home_team", "")
        away = game.get("away_team", "")
        league = game.get("league", "")
        date = game.get("date", "")
        status = game.get("status", "")

        # Only predict games that haven't started
        if status in ("STATUS_FINAL", "Final", "FT", "finished"):
            continue
        if not home or not away:
            continue

        # Fetch history
        home_history = history_map.get(home) or []
        away_history = history_map.get(away) or []

        # Feature extraction
        home_feat = extract_team_features(home, home_history, "home")
        away_feat = extract_team_features(away, away_history, "away")

        home_adv = HOME_ADV.get(league, HOME_ADV["default"])

        # Prediction
        predicted_total = predict_game_total(home_feat, away_feat, league, home_adv)
        over_prob = compute_over_probability(predicted_total, home_feat, away_feat, league)
        baseline = LEAGUE_BASELINE.get(league, LEAGUE_BASELINE["default"])

        # Edge = how far predicted is from league average (positive = expect high-scoring)
        edge = round(predicted_total - baseline, 1)

        conf = confidence_label(
            home_feat["games_used"],
            away_feat["games_used"],
            over_prob,
        )

        predictions.append({
            "league": league,
            "game": f"{home} vs {away}",
            "home_team": home,
            "away_team": away,
            "date": date,
            "predicted_total": predicted_total,
            "league_baseline": baseline,
            "edge": edge,
            "over_probability": over_prob,
            "under_probability": round(1 - over_prob, 3),
            "confidence": conf,
            "home_avg_scored": home_feat["avg_scored"],
            "away_avg_scored": away_feat["avg_scored"],
            "home_avg_allowed": home_feat["avg_allowed"],
            "away_avg_allowed": away_feat["avg_allowed"],
            "home_games_used": home_feat["games_used"],
            "away_games_used": away_feat["games_used"],
            "home_trend": round(home_feat["trend"], 3),
            "away_trend": round(away_feat["trend"], 3),
            "source": game.get("source", ""),
        })

    # Sort: HIGH confidence first, then by probability edge
    def sort_key(p):
        conf_order = {"HIGH": 2, "MEDIUM": 1, "LOW": 0}
        prob_edge = abs(p["over_probability"] - 0.5)
        return (conf_order[p["confidence"]], prob_edge)

    predictions.sort(key=sort_key, reverse=True)

    top = predictions[:50]
    generated_at = datetime.now(timezone.utc).isoformat()

    output = {
        "generated_at": generated_at,
        "total_games_analysed": len(predictions),
        "top_predictions": top,
    }

    # Write both copies so Vercel always has fresh data
    os.makedirs("data", exist_ok=True)
    os.makedirs("public/data", exist_ok=True)

    with open("data/predictions.json", "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2)

    with open("public/data/predictions.json", "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2)

    print(f"[predict] done — {len(predictions)} predictions, top {len(top)} saved")

    # Print a quick summary
    for conf in ["HIGH", "MEDIUM", "LOW"]:
        count = sum(1 for p in predictions if p["confidence"] == conf)
        print(f"  {conf}: {count}")


if __name__ == "__main__":
    main()
