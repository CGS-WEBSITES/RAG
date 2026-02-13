import json
import logging
from typing import Dict, Any, List
from sentence_transformers import SentenceTransformer
from api.database import get_cursor

logger = logging.getLogger(__name__)


class VoiceToneService:
    def __init__(self):
        self.model = SentenceTransformer("all-MiniLM-L6-v2")

    def processar_json(self, caminho_json: str) -> Dict[str, Any]:
        """
        Processa arquivo JSON de diretrizes de IPs e Tom de Voz

        Args:
            caminho_json: Caminho para o arquivo JSON

        Returns:
            Dict com estatísticas do processamento
        """
        try:
            logger.info(f"Lendo diretrizes de IPs: {caminho_json}")

            with open(caminho_json, "r", encoding="utf-8") as f:
                dados = json.load(f)

            total_processados = 0
            total_erros = 0

            with get_cursor(dict_cursor=False) as cur:
                for ip_nome, info in dados.items():
                    logger.info(f"Processando diretrizes para: {ip_nome}")

                    for categoria, valor in info.items():
                        try:
                            # Tratamento especial para o dicionário de vocabulário
                            if isinstance(valor, dict):
                                for sub_cat, lista in valor.items():
                                    if isinstance(lista, list):
                                        texto_conhecimento = f"IP: {ip_nome} | {categoria} ({sub_cat}): {', '.join(map(str, lista))}"
                                        self._armazenar(
                                            cur,
                                            ip_nome,
                                            f"{categoria}_{sub_cat}",
                                            texto_conhecimento,
                                        )
                                        total_processados += 1
                                    else:
                                        texto_conhecimento = f"IP: {ip_nome} | {categoria} ({sub_cat}): {lista}"
                                        self._armazenar(
                                            cur,
                                            ip_nome,
                                            f"{categoria}_{sub_cat}",
                                            texto_conhecimento,
                                        )
                                        total_processados += 1

                            # Tratamento para listas
                            elif isinstance(valor, list):
                                texto_conhecimento = f"IP: {ip_nome} | {categoria}: {', '.join(map(str, valor))}"
                                self._armazenar(
                                    cur, ip_nome, categoria, texto_conhecimento
                                )
                                total_processados += 1

                            # Texto simples
                            else:
                                texto_conhecimento = (
                                    f"IP: {ip_nome} | {categoria}: {valor}"
                                )
                                self._armazenar(
                                    cur, ip_nome, categoria, texto_conhecimento
                                )
                                total_processados += 1

                        except Exception as e:
                            logger.error(
                                f"Erro ao processar {ip_nome}/{categoria}: {e}"
                            )
                            total_erros += 1
                            continue

            logger.info(
                f"Processamento concluído: {total_processados} sucessos, {total_erros} erros"
            )

            return {
                "status": "success",
                "total_processados": total_processados,
                "erros": total_erros,
            }

        except Exception as e:
            logger.error(f"Erro ao processar JSON de tom de voz: {e}")
            raise

    def _armazenar(self, cur, ip: str, cat: str, texto: str):
        """Armazena conhecimento no banco com embedding"""
        vetor = self.model.encode(texto).tolist()
        cur.execute(
            """
            INSERT INTO conhecimento_ips (ip_nome, categoria, conteudo, embedding)
            VALUES (%s, %s, %s, %s)
            """,
            (ip, cat, texto, vetor),
        )

    def buscar_por_ip(self, ip_nome: str) -> List[Dict[str, Any]]:
        """Busca diretrizes por IP"""
        with get_cursor() as cur:
            cur.execute(
                """
                SELECT ip_nome, categoria, conteudo
                FROM conhecimento_ips
                WHERE ip_nome = %s
                ORDER BY categoria
                """,
                (ip_nome,),
            )
            return cur.fetchall()

    def listar_ips(self) -> List[str]:
        """Lista todos os IPs cadastrados"""
        with get_cursor() as cur:
            cur.execute(
                """
                SELECT DISTINCT ip_nome
                FROM conhecimento_ips
                ORDER BY ip_nome
                """
            )
            return [row["ip_nome"] for row in cur.fetchall()]
