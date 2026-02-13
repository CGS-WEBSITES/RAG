import logging
from flask import request
from flask_restx import Namespace, Resource
from werkzeug.datastructures import FileStorage

from api.services.logistics_service import LogisticsService
from api.services.tickets_service import TicketsService
from api.services.voice_tone_service import VoiceToneService

logger = logging.getLogger(__name__)

ns = Namespace(
    "import", description="Importação de dados (logística, tickets, tom de voz)"
)

# Parser para upload CSV
csv_parser = ns.parser()
csv_parser.add_argument(
    "file",
    location="files",
    type=FileStorage,
    required=True,
    help="Arquivo CSV",
)

# Parser para upload JSON
json_parser = ns.parser()
json_parser.add_argument(
    "file",
    location="files",
    type=FileStorage,
    required=True,
    help="Arquivo JSON",
)


def _save_temp(file):
    """Salva arquivo em diretório temporário e retorna o caminho."""
    import tempfile
    import os

    temp_dir = tempfile.gettempdir()
    temp_path = os.path.join(temp_dir, file.filename)
    file.save(temp_path)
    return temp_path


def _remove_temp(path):
    """Remove arquivo temporário."""
    import os

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
    @ns.response(500, "Erro no processamento")
    def post(self):
        """Importar arquivo CSV de logística"""
        try:
            if "file" not in request.files:
                ns.abort(400, "Nenhum arquivo enviado")

            file = request.files["file"]

            if file.filename == "":
                ns.abort(400, "Nome de arquivo vazio")

            if not file.filename.endswith(".csv"):
                ns.abort(400, "Apenas arquivos CSV são aceitos")

            temp_path = _save_temp(file)

            service = LogisticsService()
            result = service.processar_csv(temp_path)

            _remove_temp(temp_path)

            return result, 201

        except Exception as e:
            logger.error(f"Erro na importação de logística: {e}")
            ns.abort(500, f"Erro ao processar arquivo: {str(e)}")


@ns.route("/tickets")
class ImportTickets(Resource):
    @ns.doc("import_tickets")
    @ns.expect(json_parser)
    @ns.response(201, "Dados importados com sucesso")
    @ns.response(400, "Arquivo inválido")
    @ns.response(500, "Erro no processamento")
    def post(self):
        """Importar arquivo JSON de tickets consolidados"""
        try:
            if "file" not in request.files:
                ns.abort(400, "Nenhum arquivo enviado")

            file = request.files["file"]

            if file.filename == "":
                ns.abort(400, "Nome de arquivo vazio")

            if not file.filename.endswith(".json"):
                ns.abort(400, "Apenas arquivos JSON são aceitos")

            temp_path = _save_temp(file)

            service = TicketsService()
            result = service.processar_json(temp_path)

            _remove_temp(temp_path)

            return result, 201

        except Exception as e:
            logger.error(f"Erro na importação de tickets: {e}")
            ns.abort(500, f"Erro ao processar arquivo: {str(e)}")


@ns.route("/voice-tone")
class ImportVoiceTone(Resource):
    @ns.doc("import_voice_tone")
    @ns.expect(json_parser)
    @ns.response(201, "Dados importados com sucesso")
    @ns.response(400, "Arquivo inválido")
    @ns.response(500, "Erro no processamento")
    def post(self):
        """Importar arquivo JSON de diretrizes de Tom de Voz"""
        try:
            if "file" not in request.files:
                ns.abort(400, "Nenhum arquivo enviado")

            file = request.files["file"]

            if file.filename == "":
                ns.abort(400, "Nome de arquivo vazio")

            if not file.filename.endswith(".json"):
                ns.abort(400, "Apenas arquivos JSON são aceitos")

            temp_path = _save_temp(file)

            service = VoiceToneService()
            result = service.processar_json(temp_path)

            _remove_temp(temp_path)

            return result, 201

        except Exception as e:
            logger.error(f"Erro na importação de tom de voz: {e}")
            ns.abort(500, f"Erro ao processar arquivo: {str(e)}")
