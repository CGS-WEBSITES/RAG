import os
import sys
import json
import logging
from pathlib import Path
import psycopg2
from psycopg2.extras import RealDictCursor
from openai import OpenAI

# Add parent directory to sys.path to import api modules
ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

from api.config import Config

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

DEFAULT_JSON_PATH = Path("/app/scripts/keywords.json")
SQL_FILE = ROOT_DIR / "scripts" / "create_keywords_table.sql"


def get_db_connection():
    return psycopg2.connect(Config.get_db_dsn())


def run_migration(conn):
    logger.info("Executing database migration from create_keywords_table.sql...")
    with open(SQL_FILE, "r", encoding="utf-8") as f:
        sql = f.read()
    with conn.cursor() as cur:
        cur.execute(sql)
    conn.commit()
    logger.info("Migration applied successfully.")


def generate_embeddings_batch(texts: list[str]) -> list[list[float]]:
    if not Config.OPENAI_API_KEY:
        raise RuntimeError("OPENAI_API_KEY is not configured in .env")
    client = OpenAI(api_key=Config.OPENAI_API_KEY)
    
    response = client.embeddings.create(
        model=Config.EMBEDDING_MODEL,
        input=texts,
        dimensions=Config.EMBEDDING_DIMENSIONS,
    )
    return [data.embedding for data in response.data]


def import_keywords(json_path: Path):
    if not json_path.exists():
        alt_path = Path("C:/Users/luise/Documents/GitHub/drunagor_app_front/src/locales/en_US/keywords.json")
        if alt_path.exists():
            json_path = alt_path
        else:
            raise FileNotFoundError(f"Keywords JSON file not found at {json_path}")

    logger.info(f"Loading keywords from {json_path}...")
    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)


    keywords_list = data.get("keyword", [])
    logger.info(f"Found {len(keywords_list)} keywords to import.")

    conn = get_db_connection()
    try:
        run_migration(conn)

        # 1. Upsert keywords into public.keywords
        logger.info("Upserting records into public.keywords...")
        upsert_keyword_sql = """
            INSERT INTO public.keywords (id, keyword, description, icon, project, language)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (id) DO UPDATE SET
                keyword = EXCLUDED.keyword,
                description = EXCLUDED.description,
                icon = EXCLUDED.icon,
                project = EXCLUDED.project,
                language = EXCLUDED.language;
        """
        with conn.cursor() as cur:
            for item in keywords_list:
                item_id = item["id"].strip()
                keyword_title = item["keyword"].strip()
                description = item.get("description", "").strip()
                icon = item.get("icon", None)
                if icon:
                    icon = icon.strip()

                cur.execute(
                    upsert_keyword_sql,
                    (item_id, keyword_title, description, icon, "Drunagor", "en"),
                )
        conn.commit()
        logger.info("Successfully saved keywords table records.")

        # 2. Generate embeddings and upsert into public.keywords_embedding_store
        logger.info("Generating vector embeddings in batches...")
        batch_size = 20
        upsert_emb_sql = """
            INSERT INTO public.keywords_embedding_store (id, chunk, embedding)
            VALUES (%s, %s, %s::vector)
            ON CONFLICT (id) DO UPDATE SET
                chunk = EXCLUDED.chunk,
                embedding = EXCLUDED.embedding::vector;
        """

        items_to_embed = []
        for item in keywords_list:
            item_id = item["id"].strip()
            keyword_title = item["keyword"].strip()
            description = item.get("description", "").strip()
            chunk_text = f"Keyword: {keyword_title}\nDescription: {description}"
            items_to_embed.append((item_id, chunk_text))

        with conn.cursor() as cur:
            for i in range(0, len(items_to_embed), batch_size):
                batch = items_to_embed[i : i + batch_size]
                batch_texts = [chunk for _, chunk in batch]
                logger.info(f"Processing embeddings batch {i // batch_size + 1}/{(len(items_to_embed) + batch_size - 1) // batch_size}...")
                embeddings = generate_embeddings_batch(batch_texts)

                for (item_id, chunk_text), emb in zip(batch, embeddings):
                    vec_literal = "[" + ",".join(f"{x:.8f}" for x in emb) + "]"
                    cur.execute(upsert_emb_sql, (item_id, chunk_text, vec_literal))
                conn.commit()

        logger.info("Keyword embeddings successfully generated and saved!")

    finally:
        conn.close()


if __name__ == "__main__":
    custom_json = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_JSON_PATH
    import_keywords(custom_json)
