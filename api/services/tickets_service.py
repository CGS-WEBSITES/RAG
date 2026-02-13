import json
import logging
from typing import Dict, Any, List
from sentence_transformers import SentenceTransformer

from api.database import get_cursor

logger = logging.getLogger(__name__)


class TicketsService:
    def __init__(self):
        self.model = SentenceTransformer("all-MiniLM-L6-v2")

    def buscar_por_texto(self, texto: str, limite: int = 10) -> List[Dict[str, Any]]:
        """Busca tickets por similaridade semântica"""
        try:
            embedding = self.model.encode(texto).tolist()

            with get_cursor(dict_cursor=True) as cur:
                cur.execute(
                    """
                    SELECT id_original, pergunta, resposta, projeto,
                           1 - (embedding <=> %s::vector) AS similaridade
                    FROM tickets
                    ORDER BY embedding <=> %s::vector
                    LIMIT %s
                    """,
                    (embedding, embedding, limite),
                )
                results = cur.fetchall()

            return [dict(row) for row in results]

        except Exception as e:
            logger.error(f"Erro ao buscar tickets: {e}")
            raise

    def processar_json(self, filepath: str, batch_size: int = 200) -> Dict[str, Any]:
        """Processa arquivo JSON consolidado de tickets e insere no banco em lotes"""
        try:
            logger.info(f"Lendo arquivo consolidado de tickets: {filepath}")
            with open(filepath, "r", encoding="utf-8") as f:
                dados = json.load(f)

            total = len(dados)
            registros_processados = 0
            erros = []

            logger.info(f"Processando {total} tickets em lotes de {batch_size}...")

            with get_cursor(dict_cursor=False) as cur:
                # Processar em lotes
                for batch_start in range(0, total, batch_size):
                    batch_end = min(batch_start + batch_size, total)
                    batch = dados[batch_start:batch_end]

                    logger.info(
                        f"Processando lote {batch_start // batch_size + 1}/{(total + batch_size - 1) // batch_size} ({batch_start + 1}-{batch_end}/{total})"
                    )

                    # Preparar textos do lote para encoding em batch
                    textos_batch = []
                    tickets_batch = []

                    for item in batch:
                        id_ticket = item.get("id")
                        pergunta = item.get("texto_original", "")
                        resposta = "\n---\n".join(item.get("respostas", []))
                        texto_para_ia = f"PERGUNTA: {pergunta} | RESPOSTA: {resposta}"

                        textos_batch.append(texto_para_ia)
                        tickets_batch.append(
                            {
                                "id": id_ticket,
                                "pergunta": pergunta,
                                "resposta": resposta,
                            }
                        )

                    # Gerar embeddings em lote (MUITO MAIS RÁPIDO)
                    logger.info(
                        f"Gerando embeddings para {len(textos_batch)} tickets..."
                    )
                    embeddings = self.model.encode(
                        textos_batch, show_progress_bar=False
                    )

                    # Inserir no banco
                    for idx, ticket_data in enumerate(tickets_batch):
                        try:
                            cur.execute(
                                """
                                INSERT INTO tickets (id_original, pergunta, resposta, projeto, embedding)
                                VALUES (%s, %s, %s, %s, %s)
                                ON CONFLICT (id_original) DO NOTHING
                                """,
                                (
                                    ticket_data["id"],
                                    ticket_data["pergunta"],
                                    ticket_data["resposta"],
                                    "Dante/Drunagor",
                                    embeddings[idx].tolist(),
                                ),
                            )

                            if cur.rowcount > 0:
                                registros_processados += 1

                        except Exception as e:
                            erro_msg = f"Erro no ticket {ticket_data['id']}: {e}"
                            logger.error(erro_msg)
                            erros.append(erro_msg)

                    logger.info(
                        f"Lote concluído: {registros_processados}/{batch_end} tickets inseridos"
                    )

            logger.info("Processamento de tickets concluído")
            return {
                "success": True,
                "total_registros": total,
                "registros_processados": registros_processados,
                "registros_duplicados": total - registros_processados,
                "erros": erros[:10],
            }

        except Exception as e:
            logger.error(f"Erro ao processar JSON de tickets: {e}")
            raise
