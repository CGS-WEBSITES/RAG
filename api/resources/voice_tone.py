import logging
from flask_restx import Namespace, Resource, fields

from api.services.voice_tone_service import VoiceToneService

logger = logging.getLogger(__name__)

ns = Namespace("voice-tone", description="Consultas de Tom de Voz e IPs")

voice_tone_item = ns.model(
    "VoiceToneItem",
    {
        "ip_nome": fields.String(description="Nome do IP"),
        "categoria": fields.String(description="Categoria da diretriz"),
        "conteudo": fields.String(description="Conteúdo da diretriz"),
    },
)


@ns.route("/ips")
class IPsList(Resource):
    @ns.doc("list_ips")
    @ns.response(200, "Lista de IPs")
    def get(self):
        """Lista todos os IPs cadastrados"""
        try:
            service = VoiceToneService()
            ips = service.listar_ips()

            return {"ips": ips, "total": len(ips)}

        except Exception as e:
            logger.error(f"Erro ao listar IPs: {e}")
            ns.abort(500, f"Erro ao listar IPs: {str(e)}")


@ns.route("/ip/<string:ip_nome>")
@ns.param("ip_nome", "Nome do IP")
class VoiceToneByIP(Resource):
    @ns.doc("get_voice_tone_by_ip")
    @ns.marshal_list_with(voice_tone_item)
    @ns.response(404, "IP não encontrado")
    def get(self, ip_nome):
        """Busca diretrizes de Tom de Voz por IP"""
        try:
            service = VoiceToneService()
            result = service.buscar_por_ip(ip_nome)

            if not result:
                ns.abort(404, f"Nenhuma diretriz encontrada para o IP: {ip_nome}")

            return result

        except Exception as e:
            logger.error(f"Erro ao buscar tom de voz: {e}")
            ns.abort(500, f"Erro na busca: {str(e)}")
