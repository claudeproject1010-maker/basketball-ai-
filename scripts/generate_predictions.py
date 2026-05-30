import json


def confidence(prob):
    if prob >= 0.70:
        return "HIGH"
    elif prob >= 0.60:
        return "MEDIUM"
    return "LOW"


with open("data/fixtures.json", "r", encoding="utf-8") as f:
    fixtures = json.load(f)

games = fixtures.get("response", [])

predictions = []

for game in games[:300]:

    try:
        home = game["scores"]["home"]["total"]
        away = game["scores"]["away"]["total"]

        if home is None:
            home = 95

        if away is None:
            away = 95

        market_total = home + away

        expected_total = round(
            market_total * 1.05
        )

        edge = expected_total - market_total

        over_probability = round(
            min(
                max(
                    0.50 + (edge / 40),
                    0.50
                ),
                0.95
            ),
            2
        )

        predictions.append(
            {
                "league":
                game["league"]["name"],

                "game":
                (
                    game["teams"]["home"]["name"]
                    + " vs "
                    + game["teams"]["away"]["name"]
                ),

                "predicted_total":
                expected_total,

                "market_total":
                market_total,

                "edge":
                edge,

                "over_probability":
                over_probability,

                "confidence":
                confidence(
                    over_probability
                )
            }
        )

    except Exception:
        continue


predictions = sorted(
    predictions,
    key=lambda x: (
        x["confidence"] == "HIGH",
        x["over_probability"]
    ),
    reverse=True
)


output = {
    "generated": len(predictions),

    "top_predictions":
    predictions[:30]
}


with open(
    "data/predictions.json",
    "w",
    encoding="utf-8"
) as f:

    json.dump(
        output,
        f,
        indent=2
    )

print(
    "prediction generation complete"
)
