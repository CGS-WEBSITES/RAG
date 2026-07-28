import json
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

KEYWORDS_FILE = ROOT_DIR / "scripts" / "keywords.json"

def update_keywords():
    print(f"Loading {KEYWORDS_FILE}...")
    with open(KEYWORDS_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)

    keywords = data.get("keyword", [])
    
    # 1. Update TRAUMA CUBE (TC)
    trauma_updated = False
    for kw in keywords:
        if kw.get("id") == "trauma-cube-(tc)" or kw.get("keyword") == "TRAUMA CUBE (TC)":
            kw["description"] = (
                "Purple cubes allocated to Hero or Dungeon Role skill slots, blocking their use. "
                "A Hero receives 1 Trauma Cube (TC) whenever their Health Points are reduced to 0 (Knocked Out) "
                "or from a specific Knock Out / Trauma effect. The Trauma Cube must be allocated to an available Hero or Role skill slot. "
                "Upon receiving a 2nd Trauma Cube, the Hero is killed and the Adventure ends in failure. "
                "(Page 15 of Age of Darkness Rulebook)"
            )
            trauma_updated = True
            print("Updated TRAUMA CUBE (TC) in keywords.json")

        if kw.get("id") == "curse-cubes-(cc)" or kw.get("keyword") == "CURSE CUBES (CC)":
            kw["description"] = (
                "Black cubes allocated to Hero or Dungeon Role skill slots, blocking their use. "
                "Received when hit by Curse X effects or when forced to take a Curse Cube. "
                "A Hero becomes Corrupted when they receive a 6th Curse Cube, causing the Adventure to end in failure. "
                "(Page 15 of Age of Darkness Rulebook)"
            )
            print("Updated CURSE CUBES (CC) in keywords.json")

    # 2. Add KNOCKED OUT if not present
    has_knocked_out = any(kw.get("id") == "knocked-out" or "KNOCKED OUT" in kw.get("keyword", "") for kw in keywords)
    if not has_knocked_out:
        keywords.append({
            "id": "knocked-out",
            "keyword": "KNOCKED OUT",
            "description": (
                "A Hero is Knocked Out when their Health Points (HP) reach 0 (or from a Knock Out effect). "
                "When a Hero is Knocked Out: "
                "1. The Hero immediately receives 1 Trauma Cube (TC), which must be allocated to an available Hero or Dungeon Role skill slot, blocking that skill. "
                "2. The Hero regains breath and recovers Health. "
                "3. If a Hero receives a 2nd Trauma Cube, the Hero is killed and the Adventure ends in failure. "
                "(Page 15 of Age of Darkness Rulebook)"
            )
        })
        print("Added KNOCKED OUT keyword to keywords.json")

    data["keyword"] = keywords
    with open(KEYWORDS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    print("Saved updated keywords.json successfully.")

if __name__ == '__main__':
    update_keywords()
