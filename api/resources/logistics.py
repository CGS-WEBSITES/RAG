import logging
from flask_restx import Namespace, Resource, fields

from api.services.logistics_service import LogisticsService

logger = logging.getLogger(__name__)

ns = Namespace("logistics", description="Consultas de logística")

logistics_item = ns.model(
    "LogisticsItem",
    {
        "id_update": fields.String(description="ID da atualização"),
        "data_relatorio": fields.String(description="Data do relatório"),
        "projeto": fields.String(description="Nome do projeto"),
        "regiao": fields.String(description="Região"),
        "status_atual": fields.String(description="Status atual"),
        "conclusao_estimada": fields.String(description="Data estimada de conclusão"),
        "observacoes_backer": fields.String(description="Observações para backers"),
    },
)


@ns.route("/projeto/<string:projeto>")
@ns.param("projeto", "Nome do projeto")
class LogisticsByProject(Resource):
    @ns.doc("get_logistics_by_project")
    @ns.marshal_list_with(logistics_item)
    @ns.response(404, "Projeto não encontrado")
    def get(self, projeto):
        """Busca atualizações de logística por projeto"""
        try:
            service = LogisticsService()
            result = service.buscar_por_projeto(projeto)

            if not result:
                ns.abort(
                    404, f"Nenhuma atualização encontrada para o projeto: {projeto}"
                )

            return result

        except Exception as e:
            logger.error(f"Erro ao buscar logística: {e}")
            ns.abort(500, f"Erro na busca: {str(e)}")
