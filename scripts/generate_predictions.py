import json

LEAGUE_BASELINES = {

    "NBA": 228,
    "WNBA": 164,
    "Euroleague": 164,
    "NBL": 184,
    "BSN": 178,
    "Liga A": 170

}

DEFAULT_BASELINE = 170

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

    league = (
        game.get(
            "league",
            {}
        )
        .get(
            "name",
            "Unknown"
        )
    )

    baseline = (
        LEAGUE_BASELINES
        .get(
            league,
            DEFAULT_BASELINE
        )
    )

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
        or 80
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
        or 80
    )

    recent_total = (
        home_score +
        away_score
    )

    predicted_total = (

        0.70
        *
        recent_total

        +

        0.30
        *
        baseline

    )

    market_total = (
        baseline - 3
    )

    edge = (
        predicted_total
        -
        market_total
    )

    over_probability = min(

        0.92,

        max(

            0.40,

            0.50 +

            edge
            /
            40

        )

    )

    if over_probability >= 0.75:
        confidence = "HIGH"

    elif over_probability >= 0.60:
        confidence = "MEDIUM"

    else:
        confidence = "LOW"

    predictions.append({

        "league": league,

        "game":
        f"{away} vs {home}",

        "baseline":
        baseline,

        "recent_total":
        recent_total,

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
    "league model complete"
)
