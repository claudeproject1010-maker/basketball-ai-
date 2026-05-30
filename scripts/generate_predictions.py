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

        predictions.append({

            "league":
            game["league"]["name"],

            "game":
            away + " vs " + home,

            "predicted_total":
            160,

            "market_total":
            156.5,

            "over_probability":
            0.58,

            "confidence":
            "MEDIUM"

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
