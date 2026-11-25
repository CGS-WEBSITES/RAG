"""Carrega segmentos de manual já transcritos (JSON) e gera os embeddings.

    python scripts/load_manual_json.py segmentos.json

Cada item: {project, manual_id, page, section, text, image}. Um manual_id que já
existe é pulado, então rodar de novo não duplica.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from api.database import get_cursor, init_pool
from api.internal.llm import embed, vector_literal


def main(path: str) -> None:
    init_pool(1, 2)
    items = json.loads(Path(path).read_text(encoding="utf-8"))
    with get_cursor() as cur:
        cur.execute("SELECT DISTINCT manual_id FROM manual_segments")
        existing = {r["manual_id"] for r in cur.fetchall()}
    items = [i for i in items if i["manual_id"] not in existing]
    for start in range(0, len(items), 64):
        batch = items[start:start + 64]
        vectors = embed([f"{i['section']}\n{i['text']}" for i in batch])
        with get_cursor() as cur:
            for item, vec in zip(batch, vectors):
                cur.execute(
                    """INSERT INTO manual_segments (manual_id, project, page_number, section_title, content, image_path)
                       VALUES (%s, %s, %s, %s, %s, %s) RETURNING id""",
                    (item["manual_id"], item["project"], item["page"], item["section"], item["text"], item["image"]),
                )
                new_id = cur.fetchone()["id"]
                cur.execute(
                    """INSERT INTO manual_segments_embedding_store (id, chunk_seq, chunk, embedding)
                       VALUES (%s, 0, %s, %s::vector)""",
                    (new_id, item["text"], vector_literal(vec)),
                )
    print("Carregados:", len(items))


if __name__ == "__main__":
    main(sys.argv[1])
