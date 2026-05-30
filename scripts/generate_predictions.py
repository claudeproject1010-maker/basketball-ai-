import json

with open(
    "data/fixtures.json",
    "r"
) as f:
    fixtures = json.load(f)

predictions = []

for game in fixtures.get("response", []):

    home = (
        game.get("teams", {})
        .get("home", {})
        .get("name", "Unknown")
    )

    away = (
        game.get("teams", {})
        .get("away", {})
        .get("name", "Unknown")
    )

    home_score = (
        game.get("scores", {})
        .get("home", {})
        .get("total")
    )

    away_score = (
        game.get("scores", {})
        .get("away", {})
        .get("total")
    )

    if home_score is None:
        home_score = 75

    if away_score is None:
        away_score = 75

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

    confidence = (
        "HIGH"
        if over_probability >= 0.65
        else "MEDIUM"
    )

    predictions.append({

        "league":
        game.get(
            "league",
            {}
        ).get(
            "name",
            "Unknown"
        ),

        "game":
        f"{away} vs {home}",

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
        confidence

    })

predictions = sorted(
    predictions,
    key=lambda x:
    x["over_probability"],
    reverse=True
)

output = {

    "generated":
    len(
        predictions
    ),

    "top_predictions":
    predictions[:30]

}

with open(
    "data/predictions.json",
    "w"
) as f:

    json.dump(
        output,
        f,
        indent=2
    )

print(
    f"generated {len(predictions)} predictions"
)
