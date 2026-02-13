import logging
from typing import List, Dict, Any
import pandas as pd
from sentence_transformers import SentenceTransformer
from api.database import get_cursor

logger = logging.getLogger(__name__)


class LogisticsService:
    def __init__(self):
        self.model = SentenceTransformer("all-MiniLM-L6-v2")

    @staticmethod
    def _converter_data(data_str):
        """Converte string de data para formato date"""
        try:
            return pd.to_datetime(data_str, dayfirst=True).date()
        except Exception:
            return None

    def processar_csv(self, caminho_csv: str) -> Dict[str, Any]:
        """
        Processa arquivo CSV de logística e insere/atualiza no banco

        Args:
            caminho_csv: Caminho para o arquivo CSV

        Returns:
            Dict com estatísticas do processamento
        """
        try:
            logger.info(f"Lendo planilha de logística: {caminho_csv}")
            df = pd.read_csv(caminho_csv, sep=";")

            total_processados = 0
            total_erros = 0

            with get_cursor(dict_cursor=False) as cur:
                logger.info(f"Processando {len(df)} atualizações de logística...")

                for _, row in df.iterrows():
                    try:
                        # Cria contexto para a IA
                        texto_ia = (
                            f"Projeto: {row['PROJETO']} | Região: {row['REGIAO']} | "
                            f"Status: {row['STATUS_ATUAL']} | Previsão: {row['CONCLUSAO_ESTIMADA']} | "
                            f"Nota: {row['OBSERVACOES_BACKER']}"
                        )

                        vetor = self.model.encode(texto_ia).tolist()
                        data_formatada = self._converter_data(row["DATA_RELATORIO"])

                        cur.execute(
                            """
                            INSERT INTO logistica_status (
                                id_update, data_relatorio, projeto, regiao,
                                parceiro_logistico, status_atual, eta_warehouse,
                                inicio_envios, conclusao_estimada, ocorrencias,
                                links_visuais, observacoes_backer, descricao, embedding
                            )
                            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                            ON CONFLICT (id_update) DO UPDATE SET
                                status_atual = EXCLUDED.status_atual,
                                conclusao_estimada = EXCLUDED.conclusao_estimada,
                                observacoes_backer = EXCLUDED.observacoes_backer,
                                embedding = EXCLUDED.embedding
                            """,
                            (
                                row["ID_UPDATE"],
                                data_formatada,
                                row["PROJETO"],
                                row["REGIAO"],
                                row["PARCEIRO_LOGISTICO"],
                                row["STATUS_ATUAL"],
                                row["ETA_WAREHOUSE"],
                                row["INICIO_ENVIOS"],
                                row["CONCLUSAO_ESTIMADA"],
                                row["OCORRENCIAS"],
                                row["LINKS_VISUAIS"],
                                row["OBSERVACOES_BACKER"],
                                row["DESCRIÇÃO"],
                                vetor,
                            ),
                        )
                        total_processados += 1

                    except Exception as e:
                        logger.error(f"Erro ao processar linha {_}: {e}")
                        total_erros += 1
                        continue

            logger.info(
                f"Processamento concluído: {total_processados} sucessos, {total_erros} erros"
            )

            return {
                "status": "success",
                "total_registros": len(df),
                "processados": total_processados,
                "erros": total_erros,
            }

        except Exception as e:
            logger.error(f"Erro ao processar CSV de logística: {e}")
            raise

    def buscar_por_projeto(self, projeto: str) -> List[Dict[str, Any]]:
        """Busca atualizações de logística por projeto"""
        with get_cursor() as cur:
            cur.execute(
                """
                SELECT id_update, data_relatorio, projeto, regiao,
                      status_atual, conclusao_estimada, observacoes_backer
                FROM logistica_status
                WHERE projeto ILIKE %s
                ORDER BY data_relatorio DESC
                """,
                (f"%{projeto}%",),
            )
            return cur.fetchall()
