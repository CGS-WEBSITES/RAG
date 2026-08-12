import requests
import json

payload = {
    "question": "What is the official Errata rule for Command when two monsters have it?",
    "project": "Drunagor",
    "language": "en"
}

try:
    res = requests.post("http://3.23.4.11:5001/api/rag/tickets", json=payload, timeout=20)
    print("STATUS:", res.status_code)
    print("RESPONSE:\n", json.dumps(res.json(), indent=2, ensure_ascii=False))
except Exception as e:
    print("ERROR:", e)
