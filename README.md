# Basketball AI — Statistical Over/Under Predictions

A fully automated basketball prediction platform using **free, no-key APIs** and real statistical modelling.

## Architecture

```
Free APIs (TheSportsDB, ESPN, balldontlie)
          │
          ▼
  collect_fixtures.py
    ├── data/fixtures.json      (today + tomorrow's games)
    └── data/team_history.json  (last 10 results per team)
          │
          ▼
  generate_predictions.py
    ├── Pace-adjusted scoring averages
    ├── Home/away split features
    ├── Recent form trend (last 3 vs last 10)
    ├── Z-score probability model
    └── Data-quality confidence scoring
          │
          ▼
  data/predictions.json
  public/data/predictions.json
          │
          ▼
  Vercel Dashboard (public/index.html)
```

## Data Sources (all free, no API key required)

| Source | Data | Leagues |
|--------|------|---------|
| TheSportsDB (free tier) | Fixtures + last-10 team history | NBA, WNBA, EuroLeague, ACB, BBL, NBL, Turkish BSL, NCAA |
| ESPN hidden JSON API | Fixtures + team schedules | NBA, WNBA, NCAA |
| balldontlie.io (free tier) | NBA fixtures + enrichment | NBA |

## Prediction Model

The engine avoids the common mistake of using live/final scores for prediction.
It only ever uses **completed historical games** to predict **future games**.

Features used per game:
- `avg_scored` — average points scored per game (last 10)
- `avg_allowed` — average points allowed per game (last 10)
- `trend` — ratio of last-3-game avg vs last-10 avg
- `home_advantage` — league-specific points adjustment
- `league_baseline` — fallback when history is sparse
- `std_total` — variance in game totals (used for probability model)

Over probability is calculated via a **z-score / normal approximation**:
```
P(total > predicted) = 1 − Φ((predicted − historical_mean) / historical_std)
```

Confidence is determined by **data quality**, not just probability:
- **HIGH**: 16+ combined games of history + strong probability edge (>65% or <35%)
- **MEDIUM**: 10+ combined games + moderate edge
- **LOW**: sparse data or weak edge

## Setup

### 1. Push to GitHub
Upload this repo to a new GitHub repository.

### 2. Connect to Vercel
- Import the repo in [vercel.com](https://vercel.com)
- Framework: **Other**
- Output directory: `public`
- No environment variables needed

### 3. Enable GitHub Actions
The workflow runs automatically at **06:00 UTC and 14:00 UTC** every day.
You can also trigger it manually via Actions → Basketball Predictions → Run workflow.

No secrets or API keys needed — all data sources are free.

## Local Testing

```bash
python scripts/collect_fixtures.py
python scripts/generate_predictions.py
```

Then open `public/index.html` in a browser (or serve with `python -m http.server 8000 --directory public`).

## Extending

To add a new league:
1. Add it to `LEAGUE_BASELINE`, `LEAGUE_PACE`, and `HOME_ADV` in `generate_predictions.py`
2. Add its TheSportsDB or ESPN league ID to `collect_fixtures.py`
