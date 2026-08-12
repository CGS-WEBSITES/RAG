import os
import sys
from pathlib import Path
import fitz  # PyMuPDF

ROOT_DIR = Path("/home/luise/GitHub/RAG")
BOOKS_DIR = ROOT_DIR / "books"
OUTPUT_DIR = ROOT_DIR / "extracted_images"

BOOKS_MAP = [
    {
        "filename": "AOD_Rulebook-2022-1.5.pdf",
        "folder": "CoD1.5",
        "manual_id": 18,
        "title": "Corebox Rulebook 1.5"
    },
    {
        "filename": "AoD_Remake_Errata_1.2_1-7.pdf",
        "folder": "ERRATA1.2",
        "manual_id": 11,
        "title": "Errata 1.2 Remake"
    },
    {
        "filename": "APOC_Rules_InteractionsBook_v2.pdf",
        "folder": "APOC",
        "manual_id": 12,
        "title": "Apocalypse Expansion"
    },
    {
        "filename": "AOD_DH_AdventureBook_3.0-1.pdf",
        "folder": "DH",
        "manual_id": 13,
        "title": "Desert of Hellscar"
    },
    {
        "filename": "AOD_UD_AdventureBook-_v4.pdf",
        "folder": "UD",
        "manual_id": 14,
        "title": "Rise of Undead Dragon"
    },
    {
        "filename": "AOD_AP_Luccanor_v5.0.pdf",
        "folder": "LUCCANOR",
        "manual_id": 15,
        "title": "Ruin of Luccanor"
    },
    {
        "filename": "AOD_AP_ShadowWorld_v5.pdf",
        "folder": "SHADOW_WORLD",
        "manual_id": 16,
        "title": "The Shadow World"
    },
    {
        "filename": "Awakenings_Adventure_Draft_1.0.pdf",
        "folder": "AWAKENINGS",
        "manual_id": 17,
        "title": "Awakenings Expansion"
    }
]


def render_all_books():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    sql_updates = []

    print("=" * 70)
    print("Exporting Page Images from PDFs to local directory:", OUTPUT_DIR)
    print("=" * 70)

    for item in BOOKS_MAP:
        pdf_path = BOOKS_DIR / item["filename"]
        if not pdf_path.exists():
            print(f"Skipping (not found): {item['filename']}")
            continue

        book_out_dir = OUTPUT_DIR / item["folder"]
        book_out_dir.mkdir(parents=True, exist_ok=True)

        doc = fitz.open(str(pdf_path))
        num_pages = len(doc)
        print(f"\nProcessing '{item['title']}' ({item['filename']}): {num_pages} pages -> {item['folder']}/")

        for page_idx in range(num_pages):
            page_num = page_idx + 1
            page = doc[page_idx]
            
            # Render page at 150 DPI for crisp readability
            pix = page.get_pixmap(dpi=150)
            
            # Format filename as XX.01.png (matching standard RAG schema, e.g., 04.01.png or 12.01.png)
            filename = f"{page_num:02d}.01.png"
            img_file_path = book_out_dir / filename
            pix.save(str(img_file_path))

            # Database image_path format (e.g., /RAG/APOC/08.01.png)
            db_img_path = f"/RAG/{item['folder']}/{filename}"
            
            # Generate SQL statement to update manual_segments on production later
            sql_updates.append(
                f"UPDATE public.manual_segments SET image_path = '{db_img_path}' "
                f"WHERE manual_id = {item['manual_id']} AND page_number = {page_num};"
            )

        print(f"Done! Saved {num_pages} images to extracted_images/{item['folder']}/")

    # Save SQL update script for database image paths
    sql_script_path = OUTPUT_DIR / "update_database_image_paths.sql"
    with open(sql_script_path, "w", encoding="utf-8") as f:
        f.write("-- SQL script to link page images to manual_segments in PostgreSQL\n")
        f.write("\n".join(sql_updates))

    print("=" * 70)
    print("Export Complete!")
    print(f"Images directory: {OUTPUT_DIR}")
    print(f"SQL update script: {sql_script_path}")
    print("=" * 70)


if __name__ == "__main__":
    render_all_books()
