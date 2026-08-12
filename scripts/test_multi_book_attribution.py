import requests
import json

tests = [
    {
        "name": "Comparison Test 1: Darkness Rules Across Expansions",
        "question": "What are the Darkness Spawning rules in the Corebox vs Shadow World vs Apocalypse?"
    },
    {
        "name": "Comparison Test 2: New Mechanics",
        "question": "What new mechanic is introduced in Desert of Hellscar?"
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
        res = requests.post("http://3.23.4.11:5001/api/rag/tickets", json=payload, timeout=25)
        data = res.json()
        print("QUESTION:", t["question"])
        print("BOT ANSWER:\n", data.get("answer"))
        print("SOURCES:", [m.get("title") for m in data.get("sources", {}).get("manual", [])])
    except Exception as e:
        print("ERROR:", e)

print("=" * 70)
