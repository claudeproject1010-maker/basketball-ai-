import json

BASELINE_TOTAL = 160

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

    home = (
        game.get(
            "teams",
            {}
        )
        .get(
            "home",
            {}
        )
        .get(
            "name",
            "Unknown"
        )
    )

    away = (
        game.get(
            "teams",
            {}
        )
        .get(
            "away",
            {}
        )
        .get(
            "name",
            "Unknown"
        )
    )

    home_score = (
        game.get(
            "scores",
            {}
        )
        .get(
            "home",
            {}
        )
        .get(
            "total"
        )
    )

    away_score = (
        game.get(
            "scores",
            {}
        )
        .get(
            "away",
            {}
        )
        .get(
            "total"
        )
    )

    if home_score is None:
        home_score = 80

    if away_score is None:
        away_score = 80

    recent_total = (
        home_score +
        away_score
    )

    predicted_total = (

        0.60
        *
        recent_total

        +

        0.40
        *
        BASELINE_TOTAL

    )

    market_total = (
        predicted_total - 5
    )

    edge = (
        predicted_total
        -
        market_total
    )

    over_probability = min(
        0.90,
        0.50 +
        (
            edge
            /
            50
        )
    )

    confidence = "LOW"

    if over_probability >= 0.70:
        confidence = "HIGH"

    elif over_probability >= 0.60:
        confidence = "MEDIUM"

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

        "recent_total":
        round(
            recent_total,
            1
        ),

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

        "edge":
        round(
            edge,
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
    (
        x["over_probability"],
        x["edge"]
    ),

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
    "weighted model complete"
)
