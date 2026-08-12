import os
import sys
import json
import logging
from pathlib import Path
import fitz  # PyMuPDF
import pypdf
import psycopg2
from openai import OpenAI

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

from api.config import Config

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

BOOKS_TO_PROCESS = [
    {
        "filename": "Rulebook.pdf",
        "folder": "BATTLEFORGE_EN",
        "project": "Battleforge",
        "title_prefix": "Battleforge Rulebook (EN)",
        "tag": "[BATTLEFORGE RULE]",
        "language": "en",
        "manual_id": 20
    },
    {
        "filename": "Rulebook PTBR 0.5.3 - Pages Cut.pdf",
        "folder": "BATTLEFORGE_PT",
        "project": "Battleforge",
        "title_prefix": "Manual de Regras Battleforge (PT-BR)",
        "tag": "[BATTLEFORGE RULE PT]",
        "language": "pt",
        "manual_id": 21
    }
]


def get_db_connection():
    hosts_to_try = [
        Config.get_db_dsn(),
        f"host=localhost port={Config.DB_PORT} dbname={Config.DB_NAME} user={Config.DB_USER} password={Config.DB_PASSWORD}",
        f"host=127.0.0.1 port={Config.DB_PORT} dbname={Config.DB_NAME} user={Config.DB_USER} password={Config.DB_PASSWORD}"
    ]

    for dsn in hosts_to_try:
        try:
            conn = psycopg2.connect(dsn)
            return conn
        except Exception:
            continue

    return None


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


def render_and_export_images(doc_path: Path, output_folder: Path) -> dict[int, str]:
    """Renders high resolution images for each PDF page and returns page_num -> db_image_path dict"""
    output_folder.mkdir(parents=True, exist_ok=True)
    doc = fitz.open(str(doc_path))
    image_paths = {}

    for page_idx in range(len(doc)):
        page_num = page_idx + 1
        page = doc[page_idx]
        pix = page.get_pixmap(dpi=150)
        filename = f"{page_num:02d}.01.png"
        img_file_path = output_folder / filename
        pix.save(str(img_file_path))

        db_img_path = f"/RAG/{output_folder.name}/{filename}"
        image_paths[page_num] = db_img_path

    logger.info(f"Exported {len(image_paths)} images to {output_folder}")
    return image_paths


def process_book(item: dict, sql_statements: list[str], conn, client):
    pdf_path = ROOT_DIR / item["filename"]
    if not pdf_path.exists():
        pdf_path = ROOT_DIR / "books" / item["filename"]

    if not pdf_path.exists():
        logger.error(f"PDF not found: {item['filename']}")
        return

    logger.info(f"=== Processing {item['title_prefix']} ({item['filename']}) ===")
    
    output_img_dir = ROOT_DIR / "extracted_images" / item["folder"]
    img_paths_map = render_and_export_images(pdf_path, output_img_dir)

    reader = pypdf.PdfReader(str(pdf_path))
    num_pages = len(reader.pages)
    logger.info(f"PDF has {num_pages} pages.")

    manual_id = item["manual_id"]
    manual_title_escaped = item['title_prefix'].replace("'", "''")

    sql_statements.append(f"-- Ingestion statements for {item['title_prefix']} (manual_id = {manual_id})")
    sql_statements.append(f"DELETE FROM public.manual_segments_embedding_store WHERE id IN (SELECT id FROM public.manual_segments WHERE manual_id = {manual_id});")
    sql_statements.append(f"DELETE FROM public.manual_segments WHERE manual_id = {manual_id};")

    total_chunks = 0
    seg_id_counter = (manual_id * 10000) + 1

    cur = conn.cursor() if conn else None

    for page_num, page in enumerate(reader.pages, start=1):
        page_text = page.extract_text()
        if not page_text or not page_text.strip():
            continue

        chunks = chunk_text(page_text, max_chars=500)
        section_title = f"{item['title_prefix']} (p.{page_num})"
        section_title_escaped = section_title.replace("'", "''")
        db_img_path = img_paths_map.get(page_num, "")

        for chunk_seq, chunk in enumerate(chunks, start=1):
            formatted_content = f"{item['tag']} (p.{page_num}): {chunk}"
            content_escaped = formatted_content.replace("'", "''")
            seg_id = seg_id_counter
            seg_id_counter += 1

            # Build SQL statement
            sql_seg = f"INSERT INTO public.manual_segments (id, manual_id, project, page_number, section_title, content, image_path, created_at) VALUES ({seg_id}, {manual_id}, '{item['project']}', {page_num}, '{section_title_escaped}', '{content_escaped}', '{db_img_path}', CURRENT_TIMESTAMP);"
            sql_statements.append(sql_seg)

            vec = generate_embedding(client, formatted_content)
            vec_literal = "[" + ",".join(f"{x:.8f}" for x in vec) + "]"
            sql_emb = f"INSERT INTO public.manual_segments_embedding_store (id, chunk_seq, chunk, embedding) VALUES ({seg_id}, {chunk_seq}, '{content_escaped}', '{vec_literal}'::vector);"
            sql_statements.append(sql_emb)

            # Insert into live DB if connected
            if cur:
                try:
                    cur.execute(
                        """
                        INSERT INTO public.manual_segments (id, manual_id, project, page_number, section_title, content, image_path, created_at)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
                        ON CONFLICT (id) DO UPDATE SET content = EXCLUDED.content, image_path = EXCLUDED.image_path;
                        """,
                        (seg_id, manual_id, item['project'], page_num, section_title, formatted_content, db_img_path)
                    )
                    cur.execute(
                        """
                        INSERT INTO public.manual_segments_embedding_store (id, chunk_seq, chunk, embedding)
                        VALUES (%s, %s, %s, (%s)::vector)
                        ON CONFLICT (id, chunk_seq) DO UPDATE SET chunk = EXCLUDED.chunk, embedding = EXCLUDED.embedding;
                        """,
                        (seg_id, chunk_seq, formatted_content, vec_literal)
                    )
                except Exception as db_err:
                    logger.warning(f"Live DB insert failed for chunk {seg_id}: {db_err}")

            total_chunks += 1

    if conn and cur:
        conn.commit()
        cur.close()
        logger.info(f"Direct DB commit complete for {item['title_prefix']}!")

    logger.info(f"Processed {total_chunks} chunks for {item['title_prefix']}.")


def main():
    conn = get_db_connection()
    if conn:
        logger.info("Connected to PostgreSQL database successfully!")
    else:
        logger.info("PostgreSQL database is currently offline or unreachable. Generating SQL seed file for import...")

    client = get_openai_client()
    sql_statements = [
        "-- Battleforge Rulebooks Seed Script (EN & PT-BR)",
        "-- Generated automatically by ingest_battleforge_rulebooks.py",
        ""
    ]

    for item in BOOKS_TO_PROCESS:
        process_book(item, sql_statements, conn, client)

    if conn:
        conn.close()

    # Save SQL Seed File
    sql_seed_path = ROOT_DIR / "scripts" / "battleforge_manual_segments_seed.sql"
    with open(sql_seed_path, "w", encoding="utf-8") as f:
        f.write("\n".join(sql_statements))

    logger.info("=" * 70)
    logger.info("INGESTION & EMBEDDING GENERATION COMPLETE!")
    logger.info(f"Images directory: {ROOT_DIR / 'extracted_images'}")
    logger.info(f"SQL Seed File: {sql_seed_path} ({len(sql_statements)} statements generated)")
    logger.info("=" * 70)


if __name__ == "__main__":
    main()
