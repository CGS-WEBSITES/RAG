import os
import sys
import json
import logging
from pathlib import Path
import pypdf
import psycopg2
from openai import OpenAI

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

from api.config import Config

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


def get_db_connection():
    return psycopg2.connect(Config.get_db_dsn())


def get_openai_client():
    return OpenAI(api_key=Config.OPENAI_API_KEY)


def generate_embedding(client, text: str) -> list[float]:
    response = client.embeddings.create(
        model=Config.EMBEDDING_MODEL,
        input=text,
        dimensions=768
    )
    return response.data[0].embedding


def chunk_text(text: str, max_chars: int = 500) -> list[str]:
    paragraphs = [p.strip() for p in text.split("\n") if p.strip()]
    chunks = []
    current = ""
    for p in paragraphs:
        if len(current) + len(p) + 1 <= max_chars:
            current = f"{current}\n{p}".strip()
        else:
            if current:
                chunks.append(current)
            current = p
    if current:
        chunks.append(current)
    return chunks


def ingest_pdf(pdf_path: str, project: str = "Drunagor", title_prefix: str = "APOCALYPSE EXPANSION", expansion_tag: str = "[APOCALYPSE EXPANSION RULE]"):
    path = Path(pdf_path)
    if not path.exists():
        logger.error(f"File not found: {pdf_path}")
        return

    logger.info(f"Opening PDF: {path.name}")
    reader = pypdf.PdfReader(str(path))
    num_pages = len(reader.pages)
    logger.info(f"Found {num_pages} pages in PDF.")

    conn = get_db_connection()
    client = get_openai_client()

    try:
        with conn.cursor() as cur:
            # Determine next manual_id safely
            cur.execute("SELECT COALESCE(MAX(manual_id), 0) + 1 FROM public.manual_segments;")
            next_manual_id = cur.fetchone()[0]
            logger.info(f"Using manual_id = {next_manual_id} for this ingestion.")

            total_inserted = 0

            for page_num, page in enumerate(reader.pages, start=1):
                page_text = page.extract_text()
                if not page_text or not page_text.strip():
                    continue

                chunks = chunk_text(page_text, max_chars=500)
                section_title = f"{title_prefix} (p.{page_num})"

                for chunk_seq, chunk in enumerate(chunks, start=1):
                    # Format chunk content with expansion tag for clear Corebox vs Expansion differentiation
                    formatted_content = f"{expansion_tag} (p.{page_num}): {chunk}"
                    
                    # Insert into manual_segments
                    insert_seg_sql = """
                        INSERT INTO public.manual_segments
                        (manual_id, project, page_number, section_title, content, created_at)
                        VALUES (%s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
                        RETURNING id;
                    """
                    cur.execute(insert_seg_sql, (next_manual_id, project, page_num, section_title, formatted_content))
                    new_id = cur.fetchone()[0]

                    # Generate embedding
                    vec = generate_embedding(client, formatted_content)
                    vec_literal = "[" + ",".join(f"{x:.8f}" for x in vec) + "]"

                    # Insert into manual_segments_embedding_store
                    insert_emb_sql = """
                        INSERT INTO public.manual_segments_embedding_store
                        (id, chunk_seq, chunk, embedding)
                        VALUES (%s, %s, %s, (%s)::vector);
                    """
                    cur.execute(insert_emb_sql, (new_id, chunk_seq, formatted_content, vec_literal))
                    total_inserted += 1

            conn.commit()
            logger.info(f"SUCCESS! Safe ingestion complete. Inserted {total_inserted} new {title_prefix} chunks into DB.")

            # Print updated table counts
            cur.execute("SELECT count(*) FROM public.manual_segments;")
            count_seg = cur.fetchone()[0]
            cur.execute("SELECT count(*) FROM public.manual_segments_embedding_store;")
            count_emb = cur.fetchone()[0]
            logger.info(f"Total manual_segments in DB: {count_seg} | Total embeddings: {count_emb}")

    finally:
        conn.close()


if __name__ == "__main__":
    pdf_file = sys.argv[1] if len(sys.argv) > 1 else "/home/luise/GitHub/RAG/books/APOC_Rules_InteractionsBook_v2.pdf"
    proj = sys.argv[2] if len(sys.argv) > 2 else "Drunagor"
    title = sys.argv[3] if len(sys.argv) > 3 else "APOCALYPSE EXPANSION"
    tag = sys.argv[4] if len(sys.argv) > 4 else "[APOCALYPSE EXPANSION RULE]"
    ingest_pdf(pdf_file, project=proj, title_prefix=title, expansion_tag=tag)
