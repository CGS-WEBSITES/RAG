import json
import logging
import tempfile
import os

import pandas as pd
from flask import request
from flask_restx import Namespace, Resource

from api.services.document_service import create_document
from werkzeug.datastructures import FileStorage

logger = logging.getLogger(__name__)

ns = Namespace(
    "import", description="Importação de dados (logística, tickets, tom de voz)"
)

csv_parser = ns.parser()
csv_parser.add_argument(
    "file", location="files", type=FileStorage, required=True, help="Arquivo CSV"
)

json_parser = ns.parser()
json_parser.add_argument(
    "file", location="files", type=FileStorage, required=True, help="Arquivo JSON"
)


def _save_temp(file) -> str:
    temp_path = os.path.join(tempfile.gettempdir(), file.filename)
    file.save(temp_path)
    return temp_path


def _remove_temp(path: str):
    try:
        os.remove(path)
    except OSError:
        pass


@ns.route("/logistics")
class ImportLogistics(Resource):
    @ns.doc("import_logistics")
    @ns.expect(csv_parser)
    @ns.response(201, "Dados importados com sucesso")
    @ns.response(400, "Arquivo inválido")
    def post(self):
        """Importar CSV de logística para o RAG"""
        if "file" not in request.files:
            ns.abort(400, "Nenhum arquivo enviado")

        file = request.files["file"]
        if not file.filename.endswith(".csv"):
            ns.abort(400, "Apenas arquivos CSV são aceitos")

        temp_path = _save_temp(file)
        processados = 0
        erros = 0

        try:
            df = pd.read_csv(temp_path, sep=";")

            for _, row in df.iterrows():
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
                        f"Descrição: {row.get('DESCRIÇÃO', '')}"
                    )
                    create_document(
                        title=title,
                        content=content,
                        metadata={
                            "source": "logistics",
                            "id_update": str(row["ID_UPDATE"]),
                        },
                    )
                    processados += 1
                except Exception as e:
                    logger.error(f"Erro na linha {_}: {e}")
                    erros += 1

        finally:
            _remove_temp(temp_path)

        return {
            "status": "success",
            "total_registros": len(df),
            "processados": processados,
            "erros": erros,
        }, 201


@ns.route("/tickets")
class ImportTickets(Resource):
    @ns.doc("import_tickets")
    @ns.expect(json_parser)
    @ns.response(201, "Dados importados com sucesso")
    @ns.response(400, "Arquivo inválido")
    def post(self):
        """Importar JSON de tickets para o RAG"""
        if "file" not in request.files:
            ns.abort(400, "Nenhum arquivo enviado")

        file = request.files["file"]
        if not file.filename.endswith(".json"):
            ns.abort(400, "Apenas arquivos JSON são aceitos")

        temp_path = _save_temp(file)
        processados = 0
        erros = []

        try:
            with open(temp_path, "r", encoding="utf-8") as f:
                dados = json.load(f)

            for item in dados:
                try:
                    id_ticket = item.get("id", "")
                    pergunta = item.get("texto_original", "")
                    respostas = "\n---\n".join(item.get("respostas", []))

                    title = f"Ticket {id_ticket}"
                    content = f"Pergunta: {pergunta}\n\nResposta:\n{respostas}"

                    create_document(
                        title=title,
                        content=content,
                        metadata={"source": "tickets", "id_original": str(id_ticket)},
                    )
                    processados += 1
                except Exception as e:
                    msg = f"Erro no ticket {item.get('id')}: {e}"
                    logger.error(msg)
                    erros.append(msg)

        finally:
            _remove_temp(temp_path)

        return {
            "status": "success",
            "total_registros": len(dados),
            "processados": processados,
            "erros": erros[:10],
        }, 201


@ns.route("/voice-tone")
class ImportVoiceTone(Resource):
    @ns.doc("import_voice_tone")
    @ns.expect(json_parser)
    @ns.response(201, "Dados importados com sucesso")
    @ns.response(400, "Arquivo inválido")
    def post(self):
        """Importar JSON de Tom de Voz para o RAG"""
        if "file" not in request.files:
            ns.abort(400, "Nenhum arquivo enviado")

        file = request.files["file"]
        if not file.filename.endswith(".json"):
            ns.abort(400, "Apenas arquivos JSON são aceitos")

        temp_path = _save_temp(file)
        processados = 0
        erros = 0

        try:
            with open(temp_path, "r", encoding="utf-8") as f:
                dados = json.load(f)

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

                        create_document(
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
                        logger.error(f"Erro em {ip_nome}/{categoria}: {e}")
                        erros += 1

        finally:
            _remove_temp(temp_path)

        return {
            "status": "success",
            "processados": processados,
            "erros": erros,
        }, 201
