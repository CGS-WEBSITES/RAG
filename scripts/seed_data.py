import json
import logging
import re
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

from api.config import Config
from api.database import init_pool, close_pool, get_cursor

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("seed_data")

SCRIPTS_DIR = Path(__file__).resolve().parent


def _count_by_source(source: str) -> int:
    with get_cursor() as cur:
        cur.execute(
            "SELECT COUNT(*) as total FROM documents WHERE metadata->>'source' = %s",
            (source,),
        )
        row = cur.fetchone()
        return row["total"] if row else 0


def _create_document(title: str, content: str, metadata: dict) -> None:
    with get_cursor() as cur:
        cur.execute(
            "INSERT INTO documents (title, content, metadata) VALUES (%s, %s, %s)",
            (title, content, json.dumps(metadata)),
        )


JUNK_PATTERNS = [
    # Notificações do Freshworks
    r"Your Freshworks account.*?(?:All Rights Reserved\.?)",
    r"Your profile details were updated.*?(?:All Rights Reserved\.?)",
    r"Freshworks Inc\..*?(?:All Rights Reserved\.?)",
    # Assinaturas corporativas
    r"-{3,}.*?Due to high volume.*?(?:response|$)",
    r"-{3,}.*?(?:contents of this email|confidential).*?(?:future\.?|$)",
    r"The contents of this email.*?(?:in\s*the\s*future\.?|$)",
    r"Due to high volume.*?(?:response|$)",
    # Headers de ticket do Freshworks
    r"Please take a look at ticket\s*\n?#\d+\s*\n?raised by.*?(?:\)|\.)",
    r"Creative Games Studio powered by Freshdesk",
    # Citações de email
    r"Em \d{4}-\d{2}-\d{2}.*?escreveu:",
    r"On \w+,\s+\w+\s+\d+,\s+\d{4}\s+at\s+\d+:\d+\s*(?:AM|PM).*?wrote:",
    r"On \w{3}, \w{3} \d+, \d{4} at \d+:\d+ (?:AM|PM).*?wrote:",
]

# Padrões de dados sensíveis
SENSITIVE_PATTERNS = [
    (r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}", ""),
    (r"https?://[^\s\)]+", ""),
    (r"\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b", ""),
    (r"(?:Crowdox\s*)?Order\s*ID\s*#?\s*\d+", ""),
    (r"\b\d{3}\.\d{3}\.\d{3}[-]\d{2}\b", ""),  # CPF
    (r"\b\d{2}\.\d{3}\.\d{3}/\d{4}[-]\d{2}\b", ""),  # CNPJ
]

# Padrões de nomes (remover nomes próprios comuns em saudações/assinaturas)
NAME_PATTERNS = [
    # Saudações com nome
    r"(?:Hi|Hello|Dear|Thanks|Thank you|Regards|Best regards|Kind regards|"
    r"Obrigado|Olá|Prezado|Caro|Att|Atenciosamente|Oi)\s*[,;.:!]?\s*"
    r"[A-ZÀ-Ü][a-zà-ü]+(?:\s+[A-ZÀ-Ü][a-zà-ü]+){0,3}",
    # Assinaturas com cargo
    r"[A-ZÀ-Ü][a-zà-ü]+(?:\s+[A-ZÀ-Ü][a-zà-ü]+){0,2}\s+"
    r"(?:SALES|Sales|EXECUTIVE|Executive|MANAGER|Manager|SUPPORT|Support|"
    r"CUSTOMER SERVICE|Customer Service|ATENDIMENTO|Atendimento)",
    # Nome + CREATIVE GAMES STUDIO
    r"[A-ZÀ-Ü][a-zà-ü]+(?:\s+[A-ZÀ-Ü][a-zà-ü]+){0,2}\s*\n\s*CREATIVE GAMES STUDIO",
]

# Endereços (padrão simples)
ADDRESS_PATTERNS = [
    r"\d+\s+[A-Z][a-z]+(?:\s+[A-Z]?[a-z]+)*\s+"
    r"(?:Street|St|Avenue|Ave|Road|Rd|Drive|Dr|Lane|Ln|Park|Blvd|Way|Rua|Avenida|Av)\b",
    # Blocos com CEP/Postal Code
    r"[A-Z]{1,2}\d{1,2}\s?\d[A-Z]{2}",  # UK postal
    r"\b\d{5}[-]?\d{3}\b",  # BR CEP
]


def _clean_ticket_text(text: str) -> str:
    if not text:
        return ""

    lines = text.split("\n")
    cleaned_lines = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith(">"):
            continue
        cleaned_lines.append(line)
    text = "\n".join(cleaned_lines)

    for pattern in JUNK_PATTERNS:
        text = re.sub(pattern, "", text, flags=re.IGNORECASE | re.DOTALL)

    for pattern, replacement in SENSITIVE_PATTERNS:
        text = re.sub(pattern, replacement, text)

    for pattern in NAME_PATTERNS:
        text = re.sub(pattern, "", text, flags=re.MULTILINE)

    for pattern in ADDRESS_PATTERNS:
        text = re.sub(pattern, "", text)

    text = re.sub(r"CREATIVE GAMES STUDIO", "", text)
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r".*raised by.*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"^[\s\-\*=_]{3,}$", "", text, flags=re.MULTILINE)
    text = re.sub(r"[\u200b\u200c\u200d\ufeff\xa0]", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = text.strip()

    return text


def _is_junk_ticket(text: str) -> bool:
    clean = re.sub(r"\s+", " ", text).strip()
    if len(clean) < 30:
        return True

    without_labels = re.sub(r"(?:Pergunta|Resposta)\s*:", "", clean).strip()
    if len(without_labels) < 20:
        return True
    return False


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


def seed_logistics():
    source = "logistics"
    filepath = SCRIPTS_DIR / "atualizacao_logistica.json"

    if not filepath.exists():
        logger.warning("Arquivo não encontrado: %s — pulando logística", filepath)
        return 0

    existing = _count_by_source(source)
    if existing > 0:
        logger.info("Logística: %d registros já existem — pulando", existing)
        return 0

    with open(filepath, "r", encoding="utf-8") as f:
        dados = json.load(f)

    count = 0
    for row in dados:
        try:
            title = f"{row['PROJETO']} | {row['REGIAO']} | {row['ID_UPDATE']}"
            content = (
                f"Projeto: {row['PROJETO']}\n"
                f"Região: {row['REGIAO']}\n"
                f"Parceiro Logístico: {row.get('PARCEIRO_LOGISTICO', '')}\n"
                f"Status Atual: {row['STATUS_ATUAL']}\n"
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
                metadata={"source": source, "id_update": str(row["ID_UPDATE"])},
            )
            count += 1
        except Exception as e:
            logger.error("Erro ao inserir logística %s: %s", row.get("ID_UPDATE"), e)

    logger.info("Logística: %d registros inseridos", count)
    return count


def seed_tickets():
    source = "tickets"
    filepath = SCRIPTS_DIR / "todos_os_tickets_consolidados.json"

    if not filepath.exists():
        logger.warning("Arquivo não encontrado: %s — pulando tickets", filepath)
        return 0

    existing = _count_by_source(source)
    if existing > 0:
        logger.info("Tickets: %d registros já existem — pulando", existing)
        return 0

    with open(filepath, "r", encoding="utf-8") as f:
        dados = json.load(f)

    count = 0
    skipped = 0
    for item in dados:
        try:
            id_ticket = item.get("id", "")
            pergunta_raw = item.get("texto_original", "")
            respostas_raw = item.get("respostas", [])

            pergunta = _clean_ticket_text(pergunta_raw)

            respostas = []
            for r in respostas_raw:
                cleaned = _clean_ticket_text(r)
                if cleaned and len(cleaned.strip()) > 10:
                    respostas.append(cleaned)

            parts = []
            if pergunta:
                parts.append(f"Pergunta: {pergunta}")
            if respostas:
                parts.append(f"Resposta: {respostas[0]}")

                for i, r in enumerate(respostas[1:], 2):
                    parts.append(f"Continuação {i}: {r}")

            content = "\n\n".join(parts)

            if _is_junk_ticket(content):
                skipped += 1
                continue

            title = f"Ticket {id_ticket}"

            full_text = pergunta_raw + " " + " ".join(respostas_raw)
            language = _detect_language(full_text)
            project = _detect_project(full_text)

            metadata = {
                "source": source,
                "id_original": str(id_ticket),
                "language": language,
            }
            if project:
                metadata["project"] = project

            _create_document(title=title, content=content, metadata=metadata)
            count += 1
        except Exception as e:
            logger.error("Erro no ticket %s: %s", item.get("id"), e)

    logger.info(
        "Tickets: %d registros inseridos, %d descartados (lixo)", count, skipped
    )
    return count


def seed_voice_tone():
    source = "voice_tone"
    filepath = SCRIPTS_DIR / "tabela_conhecimento_ips.json"

    if not filepath.exists():
        logger.warning("Arquivo não encontrado: %s — pulando tom de voz", filepath)
        return 0

    existing = _count_by_source(source)
    if existing > 0:
        logger.info("Tom de Voz: %d registros já existem — pulando", existing)
        return 0

    with open(filepath, "r", encoding="utf-8") as f:
        dados = json.load(f)

    count = 0
    for ip_nome, info in dados.items():
        for categoria, valor in info.items():
            try:
                title = f"{ip_nome} | {categoria}"

                if isinstance(valor, dict):
                    lines = []
                    for sub_cat, conteudo in valor.items():
                        if isinstance(conteudo, list):
                            lines.append(f"{sub_cat}: {', '.join(map(str, conteudo))}")
                        else:
                            lines.append(f"{sub_cat}: {conteudo}")
                    content = f"IP: {ip_nome}\nCategoria: {categoria}\n" + "\n".join(
                        lines
                    )
                elif isinstance(valor, list):
                    content = (
                        f"IP: {ip_nome}\nCategoria: {categoria}\n"
                        f"{', '.join(map(str, valor))}"
                    )
                else:
                    content = f"IP: {ip_nome}\nCategoria: {categoria}\n{valor}"

                _create_document(
                    title=title,
                    content=content,
                    metadata={"source": source, "ip": ip_nome, "categoria": categoria},
                )
                count += 1
            except Exception as e:
                logger.error("Erro em %s/%s: %s", ip_nome, categoria, e)

    logger.info("Tom de Voz: %d registros inseridos", count)
    return count


def seed_game_comments():
    source = "game_comments"
    filepath = SCRIPTS_DIR / "base_comentarios_jogos.json"

    if not filepath.exists():
        logger.warning(
            "Arquivo não encontrado: %s — pulando comentários de jogos", filepath
        )
        return 0

    existing = _count_by_source(source)
    if existing > 0:
        logger.info("Comentários de Jogos: %d registros já existem — pulando", existing)
        return 0

    with open(filepath, "r", encoding="utf-8") as f:
        dados = json.load(f)

    count = 0
    for item in dados:
        try:
            jogo = item.get("jogo", "")
            nota = item.get("nota")
            comentario = item.get("comentario", "")
            data = item.get("data", "")

            if not comentario or len(comentario.strip()) < 10:
                continue

            nota_str = f" | Nota: {nota}" if nota is not None else ""
            title = f"{jogo}{nota_str} | {data}"

            content = (
                f"Game: {jogo}\n"
                f"Rating: {nota if nota is not None else 'N/A'}\n"
                f"Date: {data}\n"
                f"Comment: {comentario}"
            )

            _create_document(
                title=title,
                content=content,
                metadata={"source": source, "jogo": jogo, "nota": nota, "data": data},
            )
            count += 1
        except Exception as e:
            logger.error("Erro no comentário de %s: %s", item.get("jogo"), e)

    logger.info("Comentários de Jogos: %d registros inseridos", count)
    return count


def main():
    logger.info("=" * 50)
    logger.info("SEED DE DADOS INICIAIS")
    logger.info("=" * 50)

    try:
        init_pool(min_conn=1, max_conn=3)
    except Exception as e:
        logger.error("Falha ao conectar ao banco: %s", e)
        return 1

    total = 0
    try:
        total += seed_logistics()
        total += seed_tickets()
        total += seed_voice_tone()
        total += seed_game_comments()
    except Exception as e:
        logger.error("Erro durante seed: %s", e)
        import traceback

        traceback.print_exc()
        return 1
    finally:
        close_pool()

    logger.info("=" * 50)
    logger.info("SEED CONCLUÍDO: %d documentos inseridos no total", total)
    logger.info("=" * 50)
    return 0


if __name__ == "__main__":
    sys.exit(main())
