import json
import logging
import os
import re
import tempfile

import pandas as pd
from flask import request
from flask_restx import Namespace, Resource, fields
from werkzeug.datastructures import FileStorage

from api.database import get_cursor

logger = logging.getLogger(__name__)

ns = Namespace("import", description="Importação e atualização de dados")

ALLOWED_EXTENSIONS = {".json", ".xlsx", ".xls", ".csv"}

file_parser = ns.parser()
file_parser.add_argument(
    "file",
    location="files",
    type=FileStorage,
    required=True,
    help="Arquivo JSON, Excel (.xlsx/.xls) ou CSV",
)

document_input = ns.model(
    "DocumentInput",
    {
        "title": fields.String(required=True),
        "content": fields.String(required=True),
        "metadata": fields.Raw(required=True),
    },
)

document_update = ns.model(
    "DocumentUpdate",
    {
        "title": fields.String(),
        "content": fields.String(),
        "metadata": fields.Raw(),
    },
)

MANUAL_PROJECT_MAP = {
    8: "Battleforge",
    9: "Drunagor",
    10: "Dante",
}


def _get_file_extension(filename: str) -> str:
    return os.path.splitext(filename)[1].lower()


def _validate_file(file) -> str:
    if not file or not file.filename:
        raise ValueError("Nenhum arquivo enviado")
    ext = _get_file_extension(file.filename)
    if ext not in ALLOWED_EXTENSIONS:
        raise ValueError(
            f"Formato não suportado: {ext}. Use: {', '.join(ALLOWED_EXTENSIONS)}"
        )
    return ext


def _file_to_records(file) -> list[dict]:
    ext = _get_file_extension(file.filename)
    temp_path = os.path.join(tempfile.gettempdir(), file.filename)
    file.save(temp_path)

    try:
        if ext == ".json":
            with open(temp_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                return [data]
            return data

        if ext in (".xlsx", ".xls"):
            df = pd.read_excel(
                temp_path, engine="openpyxl" if ext == ".xlsx" else "xlrd"
            )
        else:
            df = pd.read_csv(temp_path, encoding="utf-8")

        df.columns = df.columns.str.strip()
        df = df.fillna("")
        return df.to_dict(orient="records")
    finally:
        try:
            os.remove(temp_path)
        except OSError:
            pass


def _create_document(title: str, content: str, metadata: dict) -> int:
    with get_cursor() as cur:
        cur.execute(
            "INSERT INTO documents (title, content, metadata) VALUES (%s, %s, %s) RETURNING id",
            (title, content, json.dumps(metadata)),
        )
        return cur.fetchone()["id"]


def _update_document(
    doc_id: int, title: str | None, content: str | None, metadata: dict | None
) -> bool:
    parts = []
    params = []
    if title is not None:
        parts.append("title = %s")
        params.append(title)
    if content is not None:
        parts.append("content = %s")
        params.append(content)
    if metadata is not None:
        parts.append("metadata = %s")
        params.append(json.dumps(metadata))
    if not parts:
        return False
    params.append(doc_id)
    with get_cursor() as cur:
        cur.execute(f"UPDATE documents SET {', '.join(parts)} WHERE id = %s", params)
        return cur.rowcount > 0


def _delete_documents_by_source(source: str) -> int:
    with get_cursor() as cur:
        cur.execute("DELETE FROM documents WHERE metadata->>'source' = %s", (source,))
        return cur.rowcount


def _count_by_source(source: str) -> int:
    with get_cursor() as cur:
        cur.execute(
            "SELECT COUNT(*) as total FROM documents WHERE metadata->>'source' = %s",
            (source,),
        )
        row = cur.fetchone()
        return row["total"] if row else 0


def _count_manual_segments(project: str | None = None) -> int:
    if project:
        with get_cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) as total FROM manual_segments WHERE project = %s",
                (project,),
            )
            row = cur.fetchone()
            return row["total"] if row else 0
    with get_cursor() as cur:
        cur.execute("SELECT COUNT(*) as total FROM manual_segments")
        row = cur.fetchone()
        return row["total"] if row else 0


def _clean_ticket_text(text: str) -> str:
    if not text:
        return ""
    lines = text.split("\n")
    cleaned_lines = [line for line in lines if not line.strip().startswith(">")]
    text = "\n".join(cleaned_lines)
    junk_patterns = [
        r"Your Freshworks account.*?(?:All Rights Reserved\.?)",
        r"Your profile details were updated.*?(?:All Rights Reserved\.?)",
        r"Freshworks Inc\..*?(?:All Rights Reserved\.?)",
        r"-{3,}.*?Due to high volume.*?(?:response|$)",
        r"-{3,}.*?(?:contents of this email|confidential).*?(?:future\.?|$)",
        r"Due to high volume.*?(?:response|$)",
        r"Please take a look at ticket\s*\n?#?\d+\s*\n?(?:raised by.*?(?:\)|\.|\n))?",
        r"-{5,}\s*Forwarded message\s*-{5,}.*?(?:\n\n|\Z)",
        r"From:.*?\nDate:.*?\nSubject:.*?\nTo:.*?\n",
        r"Sent from (?:Yahoo Mail|my iPhone|my iPad|Mail for Windows|Samsung|Outlook).*",
        r"@[A-ZÀ-Ü][a-zà-ü]+(?:\s+[A-ZÀ-Ü][a-zà-ü]+){0,2}",
        r"(?:Name:\*?\s*[A-ZÀ-Ü].*?\n)",
        r"(?:backer\s*(?:number|#|num)\s*(?:is\s*)?)?#\d{3,6}\b",
    ]
    for pattern in junk_patterns:
        text = re.sub(pattern, "", text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"#yiv\d+[^\n]*", "", text)
    text = re.sub(
        r"\{[^}]*(?:margin|padding|border|display|height|width|font)[^}]*\}", "", text
    )
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}", "", text)
    text = re.sub(r"https?://[^\s\)]+", "", text)
    text = re.sub(
        r"(?:www\.)?[a-zA-Z0-9-]+\.(?:com|com\.br|org|net|io|app)(?:\.[a-z]{2,3})?",
        "",
        text,
    )
    text = re.sub(r"\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b", "", text)
    text = re.sub(r"(?:Crowdox\s*)?Order\s*ID\s*#?\s*\d+", "", text)
    text = re.sub(r"Pledge\s*(?:id|ID)\s*\w+", "", text)
    text = re.sub(r"\$\d+[\d,.]*\s*(?:usd|USD)?", "", text)
    text = re.sub(r"[\+]?\d[\d\s\-\(\)]{8,}\d", "", text)
    text = re.sub(r"\b\d{3}\.\d{3}\.\d{3}[-]\d{2}\b", "", text)
    text = re.sub(r"\b\d{2}\.\d{3}\.\d{3}/\d{4}[-]\d{2}\b", "", text)
    text = re.sub(
        r"(?:Hi|Hello|Dear|Thanks|Thank you|Regards|Best regards|Kind regards|Warm regards|"
        r"Many thanks|Obrigado|Olá|Prezado|Caro|Att|Atenciosamente|Oi|At\.te|Ei)\s*[,;.:!]?\s*"
        r"[A-ZÀ-Ü][a-zà-ü]+(?:\s+[A-ZÀ-Ü][a-zà-ü]+){0,3}",
        "",
        text,
    )
    text = re.sub(
        r"^[A-ZÀ-Ü][a-zà-üA-Z]{1,20}(?:\s+[A-ZÀ-Ü][a-zà-üA-Z]{1,20}){0,3}\s*$",
        "",
        text,
        flags=re.MULTILINE,
    )
    text = re.sub(r"CREATIVE GAMES STUDIO", "", text, flags=re.IGNORECASE)
    text = re.sub(r".*raised by.*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"[\u200b\u200c\u200d\ufeff\xa0]", " ", text)
    text = re.sub(r"^.{1,2}$", "", text, flags=re.MULTILINE)
    text = re.sub(r"^[\s\-\*=_\.,:;]{3,}$", "", text, flags=re.MULTILINE)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r" {2,}", " ", text)
    return text.strip()


def _detect_language(text: str) -> str:
    pt_words = {
        "obrigado",
        "pedido",
        "entrega",
        "por favor",
        "olá",
        "endereço",
        "reembolso",
        "estorno",
        "atraso",
        "envio",
        "prazo",
        "aguardando",
    }
    text_lower = text.lower()
    pt_count = sum(1 for w in pt_words if w in text_lower)
    return "pt" if pt_count >= 2 else "en"


def _detect_project(text: str) -> str | None:
    projects = ["drunagor", "dante", "forfun", "oathfall", "magnus", "frosthaven"]
    text_lower = text.lower()
    for p in projects:
        if p in text_lower:
            return p.capitalize()
    return None


@ns.route("/logistics")
class ImportLogistics(Resource):
    @ns.doc("import_logistics")
    @ns.expect(file_parser)
    def post(self):
        if "file" not in request.files:
            ns.abort(400, "Nenhum arquivo enviado")
        file = request.files["file"]

        try:
            _validate_file(file)
            dados = _file_to_records(file)
        except ValueError as e:
            ns.abort(400, str(e))
        except Exception as e:
            ns.abort(400, f"Erro ao ler arquivo: {e}")

        deleted = _delete_documents_by_source("logistics")
        logger.info("Logística: %d registros antigos removidos", deleted)

        processados = 0
        erros = 0
        for row in dados:
            try:
                projeto = str(row.get("PROJETO", ""))
                regiao = str(row.get("REGIAO", ""))
                id_update = str(row.get("ID_UPDATE", ""))

                if not projeto or not regiao or not id_update:
                    erros += 1
                    continue

                title = f"{projeto} | {regiao} | {id_update}"
                content = (
                    f"Projeto: {projeto}\n"
                    f"Região: {regiao}\n"
                    f"Parceiro Logístico: {row.get('PARCEIRO_LOGISTICO', '')}\n"
                    f"Status Atual: {row.get('STATUS_ATUAL', '')}\n"
                    f"ETA Warehouse: {row.get('ETA_WAREHOUSE', '')}\n"
                    f"Início dos Envios: {row.get('INICIO_ENVIOS', '')}\n"
                    f"Conclusão Estimada: {row.get('CONCLUSAO_ESTIMADA', '')}\n"
                    f"Ocorrências: {row.get('OCORRENCIAS', '')}\n"
                    f"Observações: {row.get('OBSERVACOES_BACKER', '')}\n"
                    f"Descrição: {row.get('DESCRICAO', '')}"
                )
                _create_document(
                    title=title,
                    content=content,
                    metadata={"source": "logistics", "id_update": id_update},
                )
                processados += 1
            except Exception as e:
                logger.error("Erro ao importar logística: %s", e)
                erros += 1

        return {
            "status": "success",
            "deleted": deleted,
            "inserted": processados,
            "errors": erros,
        }, 201


@ns.route("/tickets")
class ImportTickets(Resource):
    @ns.doc("import_tickets")
    @ns.expect(file_parser)
    def post(self):
        if "file" not in request.files:
            ns.abort(400, "Nenhum arquivo enviado")
        file = request.files["file"]

        try:
            _validate_file(file)
            dados = _file_to_records(file)
        except ValueError as e:
            ns.abort(400, str(e))
        except Exception as e:
            ns.abort(400, f"Erro ao ler arquivo: {e}")

        deleted = _delete_documents_by_source("tickets")
        logger.info("Tickets: %d registros antigos removidos", deleted)

        processados = 0
        descartados = 0
        erros = 0
        for item in dados:
            try:
                id_ticket = str(item.get("id", ""))
                pergunta_raw = str(item.get("texto_original", ""))
                respostas_raw = item.get("respostas", [])
                if isinstance(respostas_raw, str):
                    respostas_raw = [respostas_raw]

                pergunta = _clean_ticket_text(pergunta_raw)
                respostas = [_clean_ticket_text(str(r)) for r in respostas_raw]
                respostas = [r for r in respostas if r and len(r.strip()) > 10]

                parts = []
                if pergunta:
                    parts.append(f"Pergunta: {pergunta}")
                if respostas:
                    parts.append(f"Resposta: {respostas[0]}")
                    for i, r in enumerate(respostas[1:], 2):
                        parts.append(f"Continuação {i}: {r}")

                content = "\n\n".join(parts)
                clean = re.sub(r"\s+", " ", content).strip()
                without_labels = re.sub(r"(?:Pergunta|Resposta)\s*:", "", clean).strip()
                if len(clean) < 30 or len(without_labels) < 20:
                    descartados += 1
                    continue

                full_text = pergunta_raw + " " + " ".join(str(r) for r in respostas_raw)
                language = _detect_language(full_text)
                project = _detect_project(full_text)

                metadata = {
                    "source": "tickets",
                    "id_original": id_ticket,
                    "language": language,
                }
                if project:
                    metadata["project"] = project

                _create_document(
                    title=f"Ticket {id_ticket}", content=content, metadata=metadata
                )
                processados += 1
            except Exception as e:
                logger.error("Erro no ticket %s: %s", item.get("id"), e)
                erros += 1

        return {
            "status": "success",
            "deleted": deleted,
            "inserted": processados,
            "discarded": descartados,
            "errors": erros,
        }, 201


@ns.route("/voice-tone")
class ImportVoiceTone(Resource):
    @ns.doc("import_voice_tone")
    @ns.expect(file_parser)
    def post(self):
        if "file" not in request.files:
            ns.abort(400, "Nenhum arquivo enviado")
        file = request.files["file"]

        try:
            _validate_file(file)
        except ValueError as e:
            ns.abort(400, str(e))

        ext = _get_file_extension(file.filename)
        temp_path = os.path.join(tempfile.gettempdir(), file.filename)
        file.save(temp_path)

        try:
            if ext == ".json":
                with open(temp_path, "r", encoding="utf-8") as f:
                    dados = json.load(f)
            else:
                df = (
                    pd.read_excel(temp_path, engine="openpyxl")
                    if ext in (".xlsx", ".xls")
                    else pd.read_csv(temp_path)
                )
                df.columns = df.columns.str.strip()
                df = df.fillna("")
                dados = {}
                for _, row in df.iterrows():
                    ip = str(row.get("ip_nome", row.get("IP", "")))
                    cat = str(row.get("categoria", row.get("CATEGORIA", "")))
                    val = str(
                        row.get("conteudo", row.get("CONTEUDO", row.get("valor", "")))
                    )
                    if ip and cat:
                        if ip not in dados:
                            dados[ip] = {}
                        dados[ip][cat] = val

            deleted = _delete_documents_by_source("voice_tone")
            logger.info("Tom de voz: %d registros antigos removidos", deleted)

            processados = 0
            erros = 0
            for ip_nome, info in dados.items():
                for categoria, valor in info.items():
                    try:
                        title = f"{ip_nome} | {categoria}"
                        if isinstance(valor, dict):
                            lines = []
                            for sub_cat, conteudo in valor.items():
                                if isinstance(conteudo, list):
                                    lines.append(
                                        f"{sub_cat}: {', '.join(map(str, conteudo))}"
                                    )
                                else:
                                    lines.append(f"{sub_cat}: {conteudo}")
                            content = (
                                f"IP: {ip_nome}\nCategoria: {categoria}\n"
                                + "\n".join(lines)
                            )
                        elif isinstance(valor, list):
                            content = f"IP: {ip_nome}\nCategoria: {categoria}\n{', '.join(map(str, valor))}"
                        else:
                            content = f"IP: {ip_nome}\nCategoria: {categoria}\n{valor}"

                        _create_document(
                            title=title,
                            content=content,
                            metadata={
                                "source": "voice_tone",
                                "ip": ip_nome,
                                "categoria": categoria,
                            },
                        )
                        processados += 1
                    except Exception as e:
                        logger.error("Erro em %s/%s: %s", ip_nome, categoria, e)
                        erros += 1
        finally:
            try:
                os.remove(temp_path)
            except OSError:
                pass

        return {
            "status": "success",
            "deleted": deleted,
            "inserted": processados,
            "errors": erros,
        }, 201


@ns.route("/manuals")
class ImportManuals(Resource):
    @ns.doc("import_manuals")
    @ns.expect(file_parser)
    def post(self):
        """Import game manual segments from CSV.
        Expected columns: manual_id, numero_pagina, titulo_secao, conteudo_texto, caminho_imagem, descricao_imagem
        """
        if "file" not in request.files:
            ns.abort(400, "No file uploaded")
        file = request.files["file"]

        try:
            _validate_file(file)
            records = _file_to_records(file)
        except ValueError as e:
            ns.abort(400, str(e))
        except Exception as e:
            ns.abort(400, f"Error reading file: {e}")

        if not records:
            ns.abort(400, "File is empty or has no valid records")

        first_manual_id = None
        for r in records:
            mid = r.get("manual_id")
            if mid:
                try:
                    first_manual_id = int(float(str(mid)))
                    break
                except (ValueError, TypeError):
                    pass

        project = (
            MANUAL_PROJECT_MAP.get(first_manual_id, f"Manual-{first_manual_id}")
            if first_manual_id
            else None
        )

        deleted = 0
        if project:
            with get_cursor() as cur:
                cur.execute(
                    "DELETE FROM manual_segments WHERE project = %s", (project,)
                )
                deleted = cur.rowcount
            logger.info(
                "Manuals: %d old segments removed for project %s", deleted, project
            )

        inserted = 0
        errors = 0
        for row in records:
            try:
                manual_id_raw = row.get("manual_id", "")
                if not manual_id_raw and manual_id_raw != 0:
                    errors += 1
                    continue

                manual_id = int(float(str(manual_id_raw)))
                row_project = MANUAL_PROJECT_MAP.get(manual_id, f"Manual-{manual_id}")

                content = str(row.get("conteudo_texto", "")).strip()
                if not content:
                    errors += 1
                    continue

                page_number = None
                page_raw = row.get("numero_pagina", "")
                if page_raw != "" and page_raw is not None:
                    try:
                        page_number = int(float(str(page_raw)))
                    except (ValueError, TypeError):
                        pass

                section_title = str(row.get("titulo_secao", "")).strip() or None
                image_path = str(row.get("caminho_imagem", "")).strip() or None
                image_description = str(row.get("descricao_imagem", "")).strip() or None

                with get_cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO manual_segments
                            (manual_id, project, page_number, section_title, content, image_path, image_description)
                        VALUES (%s, %s, %s, %s, %s, %s, %s)
                        """,
                        (
                            manual_id,
                            row_project,
                            page_number,
                            section_title,
                            content,
                            image_path,
                            image_description,
                        ),
                    )
                inserted += 1
            except Exception as e:
                logger.error("Error importing manual segment: %s", e)
                errors += 1

        return {
            "status": "success",
            "project": project,
            "deleted": deleted,
            "inserted": inserted,
            "errors": errors,
        }, 201


@ns.route("/documents")
class DocumentCreate(Resource):
    @ns.doc("create_document")
    @ns.expect(document_input)
    def post(self):
        data = ns.payload
        try:
            doc_id = _create_document(data["title"], data["content"], data["metadata"])
            return {"id": doc_id, "status": "created"}, 201
        except Exception as e:
            ns.abort(500, str(e))


@ns.route("/documents/<int:doc_id>")
class DocumentUpdate(Resource):
    @ns.doc("update_document")
    @ns.expect(document_update)
    def put(self, doc_id):
        data = ns.payload
        try:
            updated = _update_document(
                doc_id, data.get("title"), data.get("content"), data.get("metadata")
            )
            if not updated:
                ns.abort(404, "Documento não encontrado")
            return {"id": doc_id, "status": "updated"}
        except Exception as e:
            ns.abort(500, str(e))

    @ns.doc("delete_document")
    def delete(self, doc_id):
        try:
            with get_cursor() as cur:
                cur.execute("DELETE FROM documents WHERE id = %s", (doc_id,))
                if cur.rowcount == 0:
                    ns.abort(404, "Documento não encontrado")
            return {"id": doc_id, "status": "deleted"}
        except Exception as e:
            ns.abort(500, str(e))


@ns.route("/status")
class ImportStatus(Resource):
    @ns.doc("import_status")
    def get(self):
        with get_cursor() as cur:
            cur.execute("SELECT COUNT(*) as total FROM manual_segments")
            manual_count = cur.fetchone()["total"]
        return {
            "tickets": _count_by_source("tickets"),
            "logistics": _count_by_source("logistics"),
            "voice_tone": _count_by_source("voice_tone"),
            "game_comments": _count_by_source("game_comments"),
            "manual_segments": manual_count,
        }
