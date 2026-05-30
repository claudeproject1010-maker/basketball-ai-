import json
from datetime import datetime

predictions = {
    "generated_at": datetime.utcnow().isoformat(),
    "predictions": []
}

with open("data/predictions.json","w") as f:
    json.dump(predictions,f,indent=2)
