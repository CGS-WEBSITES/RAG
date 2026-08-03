import sys
import json
import logging
from pathlib import Path
import psycopg2

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

from api.config import Config

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

REGIONS = [
    "USA",
    "Canada",
    "Europe",
    "Brazil",
    "Asia",
    "Australia",
    "UK",
    "Rest of the World"
]

def update_manual_logistics():
    conn = psycopg2.connect(Config.get_db_dsn())
    try:
        with conn.cursor() as cur:
            # 1. Insert/Update Drunagor logistics documents for each region
            drunagor_entries = []
            for region in REGIONS:
                title = f"Drunagor | {region} | English | LOG-DRUNAGOR-01"
                content = (
                    f"Projeto: Drunagor\n"
                    f"Região: {region}\n"
                    f"Idioma: English\n"
                    f"Parceiro Logístico: Multiple\n"
                    f"Status Atual: Completed\n"
                    f"ETA Warehouse: Completed\n"
                    f"Início dos Envios: Completed\n"
                    f"Conclusão Estimada: Completed\n"
                    f"Ocorrências: None\n"
                    f"Observações: All regular pledge fulfillments for Chronicles of Drunagor are fully completed across all regions. If you have an isolated or specific issue with an order, please open a support ticket so our team can verify your case.\n"
                    f"Descrição: Chronicles of Drunagor fulfillment completed across all regions."
                )
                drunagor_entries.append((title, content))

            # 2. Insert/Update Battleforge logistics documents for each region
            battleforge_entries = []
            for region in REGIONS:
                title = f"Battleforge | {region} | English | LOG-BATTLEFORGE-01"
                content = (
                    f"Projeto: Battleforge\n"
                    f"Região: {region}\n"
                    f"Idioma: English\n"
                    f"Parceiro Logístico: Factory\n"
                    f"Status Atual: In Manufacturing\n"
                    f"ETA Warehouse: TBD\n"
                    f"Início dos Envios: TBD\n"
                    f"Conclusão Estimada: TBD\n"
                    f"Ocorrências: Production phase\n"
                    f"Observações: Battleforge is currently undergoing manufacturing and production at the factory. Shipping windows and fulfillment schedules will be announced as soon as production completes.\n"
                    f"Descrição: Battleforge project currently in manufacturing phase."
                )
                battleforge_entries.append((title, content))

            all_entries = drunagor_entries + battleforge_entries
            metadata = json.dumps({"source": "logistics"})

            for title, content in all_entries:
                # Extract project and region from title
                parts = title.split(" | ")
                project = parts[0]
                region = parts[1]

                check_sql = """
                    SELECT id FROM public.documents
                    WHERE metadata->>'source' = 'logistics'
                      AND title ILIKE %s
                      AND title ILIKE %s;
                """
                cur.execute(check_sql, (f"%{project}%", f"%{region}%"))
                existing = cur.fetchone()

                if existing:
                    doc_id = existing[0]
                    update_sql = """
                        UPDATE public.documents
                        SET title = %s, content = %s, metadata = %s::jsonb
                        WHERE id = %s;
                    """
                    cur.execute(update_sql, (title, content, metadata, doc_id))
                    logger.info(f"Updated logistics doc ID {doc_id}: '{title}'")
                else:
                    insert_sql = """
                        INSERT INTO public.documents (title, content, metadata)
                        VALUES (%s, %s, %s::jsonb);
                    """
                    cur.execute(insert_sql, (title, content, metadata))
                    logger.info(f"Inserted new logistics doc: '{title}'")

        conn.commit()
        logger.info("Successfully updated Drunagor and Battleforge logistics entries in DB!")

    finally:
        conn.close()

if __name__ == "__main__":
    update_manual_logistics()
