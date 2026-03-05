import json
import logging
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
            "SELECT COUNT(*) as total FROM documents " "WHERE metadata->>'source' = %s",
            (source,),
        )
        row = cur.fetchone()
        return row["total"] if row else 0


def _create_document(title: str, content: str, metadata: dict) -> None:
    with get_cursor() as cur:
        cur.execute(
            """
            INSERT INTO documents (title, content, metadata)
            VALUES (%s, %s, %s)
            """,
            (title, content, json.dumps(metadata)),
        )


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
    for item in dados:
        try:
            id_ticket = item.get("id", "")
            pergunta = item.get("texto_original", "")
            respostas = "\n---\n".join(item.get("respostas", []))

            title = f"Ticket {id_ticket}"
            content = f"Pergunta: {pergunta}\n\nResposta:\n{respostas}"

            _create_document(
                title=title,
                content=content,
                metadata={"source": source, "id_original": str(id_ticket)},
            )
            count += 1
        except Exception as e:
            logger.error("Erro no ticket %s: %s", item.get("id"), e)

    logger.info("Tickets: %d registros inseridos", count)
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
                    metadata={
                        "source": source,
                        "ip": ip_nome,
                        "categoria": categoria,
                    },
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
                metadata={
                    "source": source,
                    "jogo": jogo,
                    "nota": nota,
                    "data": data,
                },
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
