import json

with open(
    "data/fixtures.json",
    "r"
) as f:

    fixtures = json.load(f)

predictions = []

for game in fixtures.get(
    "response",
    []
):

    try:

        home = game["teams"]["home"]["name"]
        away = game["teams"]["away"]["name"]

        home_score = (
    game.get("scores", {})
        .get("home", {})
        .get("total", 0)
)

away_score = (
    game.get("scores", {})
        .get("away", {})
        .get("total", 0)
)

actual_total = (
    home_score +
    away_score
)

predicted_total = max(
    140,
    actual_total
)

market_total = (
    predicted_total - 4
)

over_probability = min(
    0.80,
    predicted_total / 300
)

predictions.append({

    "league":
    game["league"]["name"],

    "game":
    away + " vs " + home,

    "predicted_total":
    round(
        predicted_total,
        1
    ),

    "market_total":
    round(
        market_total,
        1
    ),

    "over_probability":
    round(
        over_probability,
        2
    ),

    "confidence":
    (
        "HIGH"
        if over_probability > 0.65
        else "MEDIUM"
    )

})

    except:
        continue

with open(
    "data/predictions.json",
    "w"
) as f:

    json.dump(
        {
            "predictions":
            predictions
        },
        f,
        indent=2
    )

print(
    "predictions generated"
)
