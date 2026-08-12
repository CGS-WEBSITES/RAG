import requests
import json

payload = {
    "question": "How does the Wermunggdir's Assault mechanic work in Desert of Hellscar?",
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
