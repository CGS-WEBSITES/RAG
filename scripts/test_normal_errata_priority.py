import requests
import json

tests = [
    {
        "name": "Normal Question 1: Elvish Bow Accuracy (No mention of Errata)",
        "question": "What is the accuracy check requirement for Elvish Bow?"
    },
    {
        "name": "Normal Question 2: Command Monster Loop (No mention of Errata)",
        "question": "Can a monster with Command target another monster that has Command?"
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
        print("QUESTION:", t["question"])
        print("BOT ANSWER:\n", data.get("answer"))
        print("MANUAL SOURCES:", [m.get("title") for m in data.get("sources", {}).get("manual", [])])
    except Exception as e:
        print("ERROR:", e)
