import logging
from flask_restx import Namespace, Resource, fields

from api.services.tickets_service import TicketsService

logger = logging.getLogger(__name__)

ns = Namespace("tickets", description="Consultas de tickets de suporte")

# Parser para busca
search_parser = ns.parser()
search_parser.add_argument(
    "q", type=str, required=True, help="Texto para busca", location="args"
)
search_parser.add_argument(
    "limite", type=int, default=10, help="Número máximo de resultados", location="args"
)

ticket_item = ns.model(
    "TicketItem",
    {
        "id_original": fields.String(description="ID original do ticket"),
        "pergunta": fields.String(description="Pergunta do cliente"),
        "resposta": fields.String(description="Resposta consolidada"),
        "projeto": fields.String(description="Projeto relacionado"),
    },
)


@ns.route("/search")
class TicketsSearch(Resource):
    @ns.doc("search_tickets")
    @ns.expect(search_parser)
    @ns.marshal_list_with(ticket_item)
    def get(self):
        """Busca tickets por texto"""
        try:
            args = search_parser.parse_args()
            texto_busca = args["q"]
            limite = args.get("limite", 10)

            service = TicketsService()
            result = service.buscar_por_texto(texto_busca, limite)

            return result

        except Exception as e:
            logger.error(f"Erro ao buscar tickets: {e}")
            ns.abort(500, f"Erro na busca: {str(e)}")
