import requests
import json

payload = {
    "question": "How does Darkness Spawning work in the Apocalypse expansion compared to the Corebox?",
    "project": "Drunagor",
    "language": "en"
}

try:
    res = requests.post("http://3.23.4.11:5001/api/rag/tickets", json=payload, timeout=25)
    print("STATUS:", res.status_code)
    data = res.json()
    print("ANSWER:\n", data.get("answer"))
    print("MANUAL SOURCES:", [m.get("title") for m in data.get("sources", {}).get("manual", [])])
except Exception as e:
    print("ERROR:", e)
