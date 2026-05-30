import json
import requests

URL = "https://api.balldontlie.io/v1/games"

headers = {}

response = requests.get(
    URL,
    headers=headers
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
