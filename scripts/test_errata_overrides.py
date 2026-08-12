import requests
import json

questions = [
    {
        "num": 1,
        "topic": "Keyword: COMMAND Loop Prevention",
        "question": "Can a Monster with COMMAND receive COMMAND from another Monster according to the Errata?",
        "expected_errata": "No, a Monster that has COMMAND is not a valid target to receive COMMAND from another Monster."
    },
    {
        "num": 2,
        "topic": "Skill Removal: Shield of Light",
        "question": "What happened to the Shield of Light skill according to the Errata?",
        "expected_errata": "Shield of Light was removed/abandoned during development and replaced by Whirlwind of Steel for Vorn."
    },
    {
        "num": 3,
        "topic": "Pets & Conditions Triggering",
        "question": "When a Pet is activated through an effect, do conditions affecting it trigger?",
        "expected_errata": "Yes, when a Pet is activated this way, any Condition affecting them triggers as normal at the start of their special turn."
    },
    {
        "num": 4,
        "topic": "Resolution #06 Party Leader",
        "question": "Who must make the Skill Challenge in Resolution #06 according to the Errata?",
        "expected_errata": "The Party Leader must make the Skill Challenge (Difficulty 13)."
    },
    {
        "num": 5,
        "topic": "Elvish Bow Accuracy Value",
        "question": "What is the updated Accuracy for the Elvish Bow card in Errata 1.2?",
        "expected_errata": "Accuracy was lowered from 8 to 7."
    }
]

print("Running Errata 1.2 Overrides Test against Live RAG API...")
print("=" * 75)

for q in questions:
    payload = {
        "question": q["question"],
        "project": "Drunagor",
        "language": "en"
    }
    try:
        res = requests.post("http://3.23.4.11:5001/api/rag/tickets", json=payload, timeout=20)
        data = res.json()
        print(f"\n--- QUESTION {q['num']}: {q['topic']} ---")
        print("QUESTION:", q["question"])
        print("EXPECTED ERRATA FACT:", q["expected_errata"])
        print("BOT ANSWER:\n", data.get("answer"))
        print("SOURCES:", [m.get("title") for m in data.get("sources", {}).get("manual", [])])
    except Exception as e:
        print("ERROR:", e)

print("=" * 75)
