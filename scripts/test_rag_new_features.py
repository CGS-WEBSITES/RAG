import requests
import json

tests = [
    {
        "name": "Drunagor Logistics (USA)",
        "payload": {
            "question": "How is shipping status for Drunagor in USA?",
            "project": "Drunagor",
            "region": "USA",
            "product_language": "English",
            "language": "en"
        }
    },
    {
        "name": "Battleforge Logistics (Europe)",
        "payload": {
            "question": "How is shipping status for Battleforge in Europe?",
            "project": "Battleforge",
            "region": "Europe",
            "product_language": "English",
            "language": "en"
        }
    },
    {
        "name": "Tracking Number / Individual Order Query",
        "payload": {
            "question": "Can you check my tracking number #987654 for my Drunagor pledge in USA?",
            "project": "Drunagor",
            "region": "USA",
            "product_language": "English",
            "language": "en"
        }
    }
]

for t in tests:
    print("=" * 60)
    print("TEST:", t["name"])
    try:
        res = requests.post("http://3.23.4.11:5001/api/rag/tickets", json=t["payload"], timeout=20)
        data = res.json()
        print("ANSWER:\n", data.get("answer"))
        print("LOGISTICS SOURCE:", data.get("sources", {}).get("logistics"))
    except Exception as e:
        print("ERROR:", e)
