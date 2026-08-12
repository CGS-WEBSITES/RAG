import requests
import json

tests = [
    {
        "name": "Manual Rule: Movement Across Levels",
        "question": "How does movement across different levels work in Drunagor?"
    },
    {
        "name": "Manual Rule: Crushing Chests",
        "question": "What happens when a Large Monster stomps a Chest in Drunagor?"
    }
]

for t in tests:
    print("=" * 70)
    print("TEST:", t["name"])
    payload = {
        "question": t["question"],
        "project": "Drunagor",
        "language": "en"
    }
    try:
        res = requests.post("http://3.23.4.11:5001/api/rag/tickets", json=payload, timeout=20)
        data = res.json()
        print("ANSWER:\n", data.get("answer"))
        print("MANUAL SOURCES:", [m.get("title") for m in data.get("sources", {}).get("manual", [])])
    except Exception as e:
        print("ERROR:", e)
