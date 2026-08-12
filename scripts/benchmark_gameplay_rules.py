import requests
import json
import time

test_questions = [
    {
        "id": 1,
        "question": "What does Bleed 2 do in Drunagor?",
        "topic": "Bleed Condition",
        "expected_key_facts": ["damage", "start of turn/activation", "non-preventable"]
    },
    {
        "id": 2,
        "question": "What is Relentless?",
        "topic": "Monster Targeting Keyword",
        "expected_key_facts": ["Most Tired Hero", "fewer available Action Cubes"]
    },
    {
        "id": 3,
        "question": "How does Trauma Cube work?",
        "topic": "Trauma Cubes & Death",
        "expected_key_facts": ["allocated to skill", "blocks skill", "second TC kills hero"]
    },
    {
        "id": 4,
        "question": "What happens when a hero performs a Recall Action?",
        "topic": "Action Cubes & Recall",
        "expected_key_facts": ["retrieve/recover Action Cubes", "Curse Cube"]
    },
    {
        "id": 5,
        "question": "What does Armor X mean?",
        "topic": "Armor Keyword",
        "expected_key_facts": ["reduces incoming damage", "mitigate"]
    },
    {
        "id": 6,
        "question": "How does Bear Trap work?",
        "topic": "Bear Trap Keyword",
        "expected_key_facts": ["2 non-preventable damage", "BLEED 2", "discard token"]
    }
]

results = []

print("Running Gameplay Rules Benchmark against Live RAG API...")
print("=" * 70)

for item in test_questions:
    payload = {
        "question": item["question"],
        "project": "Drunagor",
        "language": "en"
    }
    
    start_t = time.time()
    try:
        res = requests.post("http://3.23.4.11:5001/api/rag/tickets", json=payload, timeout=25)
        elapsed = round(time.time() - start_t, 2)
        if res.status_code == 200:
            data = res.json()
            ans = data.get("answer", "")
            kw_sources = data.get("sources", {}).get("keywords", [])
            manual_sources = data.get("sources", {}).get("manual", [])
            
            # Check key facts
            ans_lower = ans.lower()
            matched_facts = [fact for fact in item["expected_key_facts"] if fact.lower() in ans_lower]
            accuracy_score = f"{len(matched_facts)}/{len(item['expected_key_facts'])}"
            is_pass = len(matched_facts) >= 1
            
            results.append({
                "id": item["id"],
                "topic": item["topic"],
                "question": item["question"],
                "answer": ans,
                "sources_keywords": [k.get("title") for k in kw_sources],
                "sources_manual_count": len(manual_sources),
                "accuracy": accuracy_score,
                "passed": is_pass,
                "latency_sec": elapsed
            })
            print(f"[{'PASS' if is_pass else 'FAIL'}] Q{item['id']}: {item['topic']} ({elapsed}s)")
        else:
            print(f"[ERROR] Q{item['id']} HTTP {res.status_code}")
    except Exception as e:
        print(f"[ERROR] Q{item['id']} Exception: {e}")

print("=" * 70)
print(json.dumps(results, indent=2, ensure_ascii=False))
