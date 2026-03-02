import json
import logging
import tempfile
import os

from flask import request
from flask_restx import Namespace, Resource

from api.services.document_service import create_document
from werkzeug.datastructures import FileStorage

logger = logging.getLogger(__name__)

ns = Namespace("import", description="Importação de dados de logística")

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
    @ns.expect(json_parser)
    @ns.response(201, "Dados importados com sucesso")
    @ns.response(400, "Arquivo inválido")
    def post(self):
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
                    logger.error("Erro ao importar registro: %s", e)
                    erros += 1

        finally:
            _remove_temp(temp_path)

        return {
            "status": "success",
            "total_registros": len(dados),
            "processados": processados,
            "erros": erros,
        }, 201
