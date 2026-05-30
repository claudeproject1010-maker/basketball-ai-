import json
from collections import defaultdict

LEAGUE_BASELINES = {

    "NBA": 228,
    "WNBA": 164,
    "Euroleague": 164,
    "NBL": 184,
    "BSN": 178

}

DEFAULT_BASELINE = 170

with open(
    "data/fixtures.json",
    "r"
) as f:

    fixtures = json.load(f)

games = fixtures.get(
    "response",
    []
)

team_history = defaultdict(list)

for game in games:

    try:

        home = (
            game["teams"]["home"]["name"]
        )

        away = (
            game["teams"]["away"]["name"]
        )

        hs = (
            game["scores"]["home"]["total"]
            or 80
        )

        aw = (
            game["scores"]["away"]["total"]
            or 80
        )

        total = hs + aw

        team_history[
            home
        ].append(
            total
        )

        team_history[
            away
        ].append(
            total
        )

    except:
        pass

predictions = []

for game in games:

    try:

        league = (
            game["league"]["name"]
        )

        baseline = (
            LEAGUE_BASELINES
            .get(
                league,
                DEFAULT_BASELINE
            )
        )

        home = (
            game["teams"]["home"]["name"]
        )

        away = (
            game["teams"]["away"]["name"]
        )

        home_avg = (

            sum(
                team_history[home][-5:]
            )

            /

            max(
                1,
                len(
                    team_history[
                        home
                    ][-5:]
                )
            )

        )

        away_avg = (

            sum(
                team_history[away][-5:]
            )

            /

            max(
                1,
                len(
                    team_history[
                        away
                    ][-5:]
                )
            )

        )

        recent_total = (

            home_avg
            +
            away_avg

        ) / 2

        predicted_total = (

            0.50
            *
            recent_total

            +

            0.50
            *
            baseline

        )

        market_total = (
            baseline
            -
            3
        )

        edge = (
            predicted_total
            -
            market_total
        )

        probability = min(

            0.92,

            max(

                0.40,

                0.50
                +
                edge
                /
                50

            )

        )

        predictions.append({

            "league":
            league,

            "game":
            f"{away} vs {home}",

            "baseline":
            baseline,

            "recent_form":
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
                probability,
                2
            ),

            "confidence":

            (
                "HIGH"

                if probability
                >= 0.75

                else

                "MEDIUM"

            )

        })

    except:
        pass

predictions = sorted(

    predictions,

    key=lambda x:
    (
        x[
            "over_probability"
        ],
        x[
            "edge"
        ]
    ),

    reverse=True

)

with open(
    "data/predictions.json",
    "w"
) as f:

    json.dump(

        {

            "generated":
            len(
                predictions
            ),

            "top_predictions": sorted(
    predictions,
    key=lambda x: (
        x["confidence"] == "HIGH",
        x["over_probability"]
    ),
    reverse=True
)[:30]]

        },

        f,

        indent=2

    )

print(
    "recent-form model complete"
)
