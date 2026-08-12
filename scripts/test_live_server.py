import requests
import json

SERVER_URL = "http://3.23.4.11:5001"

print("--- 1. Testing /health ---")
r = requests.get(f"{SERVER_URL}/health")
print("Health status code:", r.status_code)
print("Health payload:", r.json())

print("\n--- 2. Testing Logistics Query (/api/rag/tickets) ---")
payload_logistics = {
    "question": "Qual é o status de envio do Dante na Europa?",
    "project": "Dante",
    "region": "Europe",
    "product_language": "English",
    "language": "pt"
}
r = requests.post(f"{SERVER_URL}/api/rag/tickets", json=payload_logistics, timeout=30)
print("Logistics Status Code:", r.status_code)
data = r.json()
print("Answer:\n", data.get("answer"))
print("Logistics Sources count:", len(data.get("sources", {}).get("logistics", [])))
print("Logistics Sources:", data.get("sources", {}).get("logistics"))

print("\n--- 3. Testing Game Rules Query (/api/rag/tickets) ---")
payload_rules = {
    "question": "Como funcionam os Trauma Cubes em Chronicles of Drunagor?",
    "project": "Drunagor",
    "language": "pt"
}
r = requests.post(f"{SERVER_URL}/api/rag/tickets", json=payload_rules, timeout=30)
print("Rules Status Code:", r.status_code)
data = r.json()
print("Answer:\n", data.get("answer"))
print("Manual Sources count:", len(data.get("sources", {}).get("manual", [])))
