import json
import sys
import logging
from pathlib import Path
import psycopg2
from psycopg2.extras import RealDictCursor

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

from api.config import Config

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

JSON_FILE = ROOT_DIR / "dante_logistics_updates.json"


def get_db_connection():
    return psycopg2.connect(Config.get_db_dsn())


def update_logistics():
    candidates = [
        Path("/app/scripts/dante_logistics_updates.json"),
        ROOT_DIR / "dante_logistics_updates.json",
        Path("/app/dante_logistics_updates.json"),
        Path("dante_logistics_updates.json"),
        Path("/mnt/c/Users/luise/GitHub/RAG/dante_logistics_updates.json"),
    ]
    json_file = None
    for cand in candidates:
        if cand.exists():
            json_file = cand
            break

    if not json_file:
        raise FileNotFoundError(f"Logistics updates JSON file not found in candidates: {candidates}")

    logger.info(f"Reading logistics updates from {json_file}...")
    with open(json_file, "r", encoding="utf-8") as f:
        updates = json.load(f)

    logger.info(f"Loaded {len(updates)} logistics entries.")

    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            for item in updates:
                project = item.get("PROJECT", "Dante").strip()
                region = item.get("REGION", "").strip()
                language = item.get("LANGUAGE", "").strip()
                update_id = item.get("UPDATE_ID", "").strip()

                partner = item.get("LOGISTICS_PARTNER", "").strip()
                status = item.get("CURRENT_STATUS", "").strip()
                eta = item.get("ETA_WAREHOUSE", "").strip()
                shipments = item.get("SHIPMENTS_STARTED", "").strip()
                completion = item.get("ESTIMATED_COMPLETION", "").strip()
                issues = item.get("ISSUES", "").strip()
                notes = item.get("BACKER_NOTES", "").strip()
                desc = item.get("DESCRIPTION", "").strip()

                title = f"{project} | {region} | {language} | {update_id}"
                content = (
                    f"Projeto: {project}\n"
                    f"Região: {region}\n"
                    f"Idioma: {language}\n"
                    f"Parceiro Logístico: {partner}\n"
                    f"Status Atual: {status}\n"
                    f"ETA Warehouse: {eta}\n"
                    f"Início dos Envios: {shipments}\n"
                    f"Conclusão Estimada: {completion}\n"
                    f"Ocorrências: {issues}\n"
                    f"Observações: {notes}\n"
                    f"Descrição: {desc}"
                )

                metadata = json.dumps({"source": "logistics"})

                # Check if document exists for this project, region, language, and update_id
                check_sql = """
                    SELECT id FROM public.documents
                    WHERE metadata->>'source' = 'logistics'
                      AND title ILIKE %s
                      AND title ILIKE %s
                      AND title ILIKE %s
                    LIMIT 1;
                """
                cur.execute(check_sql, (f"%{project}%", f"%{region}%", f"%{language}%"))
                existing = cur.fetchone()

                if existing:
                    doc_id = existing[0]
                    update_sql = """
                        UPDATE public.documents
                        SET title = %s, content = %s, metadata = %s::jsonb
                        WHERE id = %s;
                    """
                    cur.execute(update_sql, (title, content, metadata, doc_id))
                    logger.info(f"Updated logistics document ID {doc_id}: '{title}'")
                else:
                    insert_sql = """
                        INSERT INTO public.documents (title, content, metadata)
                        VALUES (%s, %s, %s::jsonb);
                    """
                    cur.execute(insert_sql, (title, content, metadata))
                    logger.info(f"Inserted new logistics document: '{title}'")

        conn.commit()
        logger.info("Logistics data update committed successfully!")

    finally:
        conn.close()


if __name__ == "__main__":
    update_logistics()
