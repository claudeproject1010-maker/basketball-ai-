import os
import json
import requests

API_KEY = os.getenv(
    "API_SPORTS_KEY"
)

url = (
    "https://v1.basketball.api-sports.io/games"
)

headers = {
    "x-apisports-key": API_KEY
}

params = {
    "date": "2026-05-30"
}

response = requests.get(
    url,
    headers=headers,
    params=params
)

data = response.json()

with open(
    "data/fixtures.json",
    "w"
) as f:

    json.dump(
        data,
        f,
        indent=2
    )

print("fixtures saved")
